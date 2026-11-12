"""Backup speech recognition through Sarvam AI (online, paid per hour of audio)."""
import json
import os
import subprocess
import urllib.request
import uuid

from . import asr

API = "https://api.sarvam.ai/speech-to-text"
CODES = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN", "sa": "hi-IN"}


def _post_wav(key, wav_bytes, lang):
    b = uuid.uuid4().hex
    parts = []
    for name, val in (("model", "saarika:v2.5"), ("language_code", CODES.get(lang, "te-IN"))):
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, name, val)).encode())
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
                  'Content-Type: audio/wav\r\n\r\n' % b).encode() + wav_bytes + b"\r\n")
    parts.append(("--%s--\r\n" % b).encode())
    req = urllib.request.Request(API, data=b"".join(parts), headers={
        "api-subscription-key": key, "Content-Type": "multipart/form-data; boundary=" + b})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("transcript", "")


def transcribe_words(key, wav_path, lang, ffmpeg="ffmpeg", offset=0.0):
    audio, sr = asr.read_wav(wav_path)
    chunks = asr.make_chunks(asr.split_points(ffmpeg, wav_path), len(audio) / sr, target=20, max_len=28)
    words = []
    for s, e in chunks:
        tmp = wav_path + ".chunk.wav"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", "%.3f" % s, "-to", "%.3f" % e, "-i", wav_path,
                        "-ac", "1", "-ar", "16000", tmp], check=True)
        with open(tmp, "rb") as f:
            text = asr.clean_text(_post_wav(key, f.read(), lang))
        os.remove(tmp)
        ws = text.split()
        total = sum(len(w) for w in ws) or 1
        t = s
        for w in ws:  # spread the chunk's time over its words by length
            d = (e - s) * len(w) / total
            words.append({"w": w, "s": round(t + offset, 2), "e": round(t + d + offset, 2)})
            t += d
    return words
