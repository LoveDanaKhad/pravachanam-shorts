"""Speech recognition with AI4Bharat IndicConformer ONNX models (MIT licence).

Audio is split at pauses (ffmpeg silencedetect) into short chunks; each chunk is
recognised separately. Short chunks give usable subtitle timing.
"""
import re
import subprocess
import wave

import numpy as np

MODEL_REPOS = {
    "te": "OpenVoiceOS/ai4bharat-indicconformer-te-onnx",
    "sa": "OpenVoiceOS/ai4bharat-indicconformer-sa-onnx",
    "hi": "OpenVoiceOS/ai4bharat-indicconformer-hi-onnx",
}
MODEL_FILES = ["config.json", "vocab.txt", "model.int8.onnx"]

# repeated vowel signs / viramas produced by the CTC decoder ("దిగేేసి" -> "దిగేసి")
_DUP_MARKS = re.compile(r"([ా-్ౕౖा-्ँ-ः])\1+")


def clean_text(s):
    s = _DUP_MARKS.sub(r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_wav(ffmpeg, src, out_wav, start=None, end=None):
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", "%.3f" % start]
    if end is not None:
        cmd += ["-to", "%.3f" % end]
    cmd += ["-i", src, "-ac", "1", "-ar", "16000", "-vn", out_wav]
    subprocess.run(cmd, check=True)
    return out_wav


def split_points(ffmpeg, wav_path, noise_db=-32, min_sil=0.2):
    out = subprocess.run([ffmpeg, "-i", wav_path, "-af",
                          "silencedetect=noise=%ddB:d=%.2f" % (noise_db, min_sil), "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ss = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    se = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return [(a + b) / 2 for a, b in zip(ss, se)]


def make_chunks(cuts, duration, target=7.0, max_len=10.0):
    """Group pause points into chunks of about `target` seconds (never above max_len)."""
    chunks, start = [], 0.0
    for c in cuts + [duration]:
        if c - start >= target or c == duration:
            while c - start > max_len:
                chunks.append((start, start + target))
                start += target
            if c - start > 0.3:
                chunks.append((start, c))
            start = c
    return chunks


def read_wav(path):
    w = wave.open(path)
    sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return a, sr


class Recognizer:
    def __init__(self, model_dir):
        import onnx_asr
        self.model = onnx_asr.load_model("nemo-conformer-ctc", model_dir, quantization="int8")
        self.ts_model = self.model.with_timestamps()

    def transcribe_words(self, wav_path, ffmpeg="ffmpeg", offset=0.0, target=14.0, max_len=22.0, progress=None):
        """Recognise at natural pauses and return words with their own times:
        [{"w": word, "s": start, "e": end}] (seconds, plus offset)."""
        audio, sr = read_wav(wav_path)
        dur = len(audio) / sr
        chunks = make_chunks(split_points(ffmpeg, wav_path), dur, target=target, max_len=max_len)
        words = []
        for n, (cs, ce) in enumerate(chunks):
            r = self.ts_model.recognize(audio[int(cs * sr):int(ce * sr)], sample_rate=sr)
            cur = None
            for tok, t in zip(r.tokens, r.timestamps):
                if tok.startswith(" ") or cur is None:
                    if cur:
                        words.append(cur)
                    cur = {"w": tok.strip(), "s": round(cs + t + offset, 2), "e": round(cs + t + offset + 0.1, 2)}
                else:
                    cur["w"] += tok
                    cur["e"] = round(cs + t + offset + 0.1, 2)
            if cur:
                words.append(cur)
            if progress:
                progress((n + 1) / len(chunks))
        for w in words:
            w["w"] = clean_text(w["w"])
        words = [w for w in words if w["w"]]
        for a, b in zip(words, words[1:]):  # a word lasts until the next one starts (max +0.6 s)
            a["e"] = round(min(b["s"], max(a["e"], a["s"] + 0.2) + 0.6), 2)
        return words

    def transcribe(self, wav_path, ffmpeg="ffmpeg", offset=0.0, target=7.0, progress=None):
        audio, sr = read_wav(wav_path)
        dur = len(audio) / sr
        chunks = make_chunks(split_points(ffmpeg, wav_path), dur, target=target)
        res = []
        for i, (s, e) in enumerate(chunks):
            txt = clean_text(self.model.recognize(audio[int(s * sr):int(e * sr)], sample_rate=sr))
            if txt:
                res.append({"start": round(s + offset, 2), "end": round(e + offset, 2), "text": txt})
            if progress:
                progress((i + 1) / len(chunks))
        return res
