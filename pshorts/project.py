"""A project = one source video and everything made from it. State lives in project.json."""
import json
import os
import re
import shutil
import threading
import time
import traceback
import urllib.request
import uuid

from . import asr, llm, paths
from . import render as R

LOCK = threading.RLock()
HF = "https://huggingface.co/%s/resolve/main/%s"
LANG_NAMES = {"te": "Telugu", "hi": "Hindi", "en": "English", "sa": "Sanskrit"}
SERIES_SCRIPT = {"te": "te", "hi": "hi", "en": "te", "sa": "hi"}


# ------------------------------------------------------------------ storage
def proj_dir(pid):
    return paths.sub("projects", pid)


def load(pid):
    with LOCK, open(os.path.join(proj_dir(pid), "project.json"), encoding="utf-8") as f:
        return json.load(f)


def save(p):
    with LOCK:
        fp = os.path.join(proj_dir(p["id"]), "project.json")
        with open(fp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=1)
        os.replace(fp + ".tmp", fp)


def update(pid, **kw):
    with LOCK:
        p = load(pid)
        p.update(kw)
        save(p)
        return p


def list_projects():
    out = []
    root = paths.sub("projects")
    for pid in os.listdir(root):
        try:
            p = load(pid)
            out.append({k: p.get(k) for k in ("id", "name", "status", "created", "lang", "progress", "error")})
        except (OSError, ValueError):
            pass
    return sorted(out, key=lambda x: x.get("created") or 0, reverse=True)


def create(src_path, opts):
    pid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    name = os.path.splitext(os.path.basename(src_path))[0]
    p = {
        "id": pid, "name": name, "src": src_path, "created": time.time(),
        "lang": opts.get("lang", "auto"), "series": opts.get("series", ""),
        "template": opts.get("template", "jnana-prakasha"),
        "versions": opts.get("versions", {"en": True, "ru": True}),
        "ru_review": bool(opts.get("ru_review", True)),
        "count": opts.get("count"), "length": opts.get("length", [35, 120]),
        "ranges": opts.get("ranges"), "crop_x": opts.get("crop_x", 0.5),
        "status": "processing", "progress": {"step": "start", "frac": 0}, "error": "",
        "fragments": [], "outputs": [], "ru_sent": False,
    }
    os.makedirs(proj_dir(pid), exist_ok=True)
    save(p)
    return p


# ------------------------------------------------------------------ glossary of corrections
def glossary_text(limit=40):
    fp = os.path.join(paths.data_root(), "corrections.json")
    if not os.path.exists(fp):
        return ""
    with open(fp, encoding="utf-8") as f:
        items = json.load(f)[-limit:]
    return "; ".join("%s → %s" % (a, b) for a, b in items)


def add_correction(before, after):
    if not before or before.strip() == after.strip():
        return
    fp = os.path.join(paths.data_root(), "corrections.json")
    items = []
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            items = json.load(f)
    items.append([before.strip(), after.strip()])
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(items[-500:], f, ensure_ascii=False, indent=0)


# ------------------------------------------------------------------ models
def ensure_model(lang, progress=None):
    """Download the AI4Bharat ONNX model for a language once (about 140 MB)."""
    d = paths.sub("models", lang)
    for i, fn in enumerate(asr.MODEL_FILES):
        dst = os.path.join(d, fn)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            continue
        url = HF % (asr.MODEL_REPOS[lang], fn)
        tmp = dst + ".part"
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                got += len(b)
                if progress and total:
                    progress((i + got / total) / len(asr.MODEL_FILES))
        os.replace(tmp, dst)
    return d


_RECOG = {}


def recognizer(lang):
    if lang not in _RECOG:
        _RECOG[lang] = asr.Recognizer(ensure_model(lang))
    return _RECOG[lang]


# ------------------------------------------------------------------ helpers
def words_to_segments(words, target=18.0):
    segs, cur = [], None
    for w in words:
        if cur is None or w["s"] - cur["start"] >= target:
            if cur:
                segs.append(cur)
            cur = {"start": w["s"], "end": w["e"], "text": w["w"]}
        else:
            cur["end"] = w["e"]
            cur["text"] += " " + w["w"]
    if cur:
        segs.append(cur)
    return segs


def slugify(s):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-").lower()
    return s[:40] or "short"


def title_words(title, accent):
    acc = (accent or "").strip(" .,!?:;«»\"'").lower()
    ws = title.split()
    out, found = [], False
    for w in ws:
        is_acc = (not found) and acc and w.strip(" .,!?:;«»\"'").lower() == acc
        found = found or is_acc
        out.append((w, bool(is_acc)))
    return out


def _sarvam_words(p, wav, offset, settings):
    """Backup recognition through Sarvam (online). Word times are spread over each chunk."""
    from . import sarvam
    return sarvam.transcribe_words(settings["sarvam_key"], wav, p["lang"], paths.tool("ffmpeg"), offset)


def detect_language(wav, settings):
    """Recognise a 40-second sample with the Telugu and Hindi models and let DeepSeek decide."""
    ff = paths.tool("ffmpeg")
    sample = wav + ".sample.wav"
    asr.extract_wav(ff, wav, sample, 60, 100)
    guesses = {}
    for lang in ("te", "hi"):
        guesses[lang] = " ".join(w["w"] for w in recognizer(lang).transcribe_words(sample, ff))[:600]
    os.remove(sample)
    sysm = ("Two speech recognisers (Telugu and Hindi) transcribed the same audio. Decide the spoken "
            "language: te, hi or en (English speech shows as nonsense or English words in Indic script). "
            "Return JSON {\"lang\":\"te|hi|en\"}.")
    try:
        return llm.chat(settings["deepseek_key"], sysm, json.dumps(guesses, ensure_ascii=False)).get("lang", "te")
    except Exception:
        return "te"


# ------------------------------------------------------------------ step 1: analyse
def analyse(pid, settings):
    try:
        p = load(pid)
        ff = paths.tool("ffmpeg")
        d = proj_dir(pid)
        wav = os.path.join(d, "audio.wav")
        update(pid, progress={"step": "audio", "frac": 0.02})
        asr.extract_wav(ff, p["src"], wav)
        lang = p["lang"]
        if lang == "auto":
            update(pid, progress={"step": "language", "frac": 0.05})
            lang = detect_language(wav, settings)
            p = update(pid, lang=lang)
        model_lang = lang if lang in asr.MODEL_REPOS else "te"

        # speech recognition, only inside the chosen time ranges
        ranges = p.get("ranges") or [[0, None]]
        words = []
        update(pid, progress={"step": "model", "frac": 0.08})
        rec = recognizer(model_lang) if settings.get("asr_engine") != "sarvam" else None
        for k, (a, b) in enumerate(ranges):
            part = os.path.join(d, "part%d.wav" % k)
            asr.extract_wav(ff, wav, part, a or 0, b)

            def prog(x, k=k):
                update(pid, progress={"step": "asr", "frac": 0.1 + 0.7 * (k + x) / len(ranges)})
            if rec:
                words += rec.transcribe_words(part, ff, offset=a or 0, progress=prog)
            else:
                words += _sarvam_words(p, part, a or 0, settings)
            os.remove(part)
        with open(os.path.join(d, "words.json"), "w", encoding="utf-8") as f:
            json.dump(words, f, ensure_ascii=False)

        # DeepSeek chooses complete-thought fragments
        update(pid, progress={"step": "select", "frac": 0.85})
        segs = words_to_segments(words)
        lo, hi = p.get("length") or [35, 120]
        frs = llm.select_fragments(settings["deepseek_key"], segs, count=p.get("count"),
                                   min_s=lo, max_s=hi, glossary=glossary_text())
        frags = []
        frs = [f for f in frs if float(f.get("end", 0)) - float(f.get("start", 0)) >= lo * 0.8]
        for i, f in enumerate(sorted(frs, key=lambda x: float(x.get("start", 0)))):
            frags.append({
                "id": i + 1, "start": float(f["start"]), "end": float(f["end"]),
                "title_en": f.get("title_en", ""), "title_ru": f.get("title_ru", ""),
                "accent_en": f.get("accent_en", ""), "accent_ru": f.get("accent_ru", ""),
                "why": f.get("why", ""), "summary_en": f.get("summary_en", ""),
                "summary_ru": f.get("summary_ru", ""), "status": None, "subs": [],
            })
        update(pid, fragments=frags, status="fragments", progress={"step": "done", "frac": 1})
        notify("Fragments are ready for approval", p["name"])
    except Exception as e:
        traceback.print_exc()
        update(pid, status="error", error=str(e))


def preview_clip(pid, fid):
    """Low-quality preview of a fragment straight from the source (for the approval screen)."""
    p = load(pid)
    f = next(x for x in p["fragments"] if x["id"] == fid)
    out = os.path.join(proj_dir(pid), "preview_%d_%d_%d.mp4" % (fid, f["start"] * 10, f["end"] * 10))
    if not os.path.exists(out):
        import subprocess
        subprocess.run([paths.tool("ffmpeg"), "-y", "-loglevel", "error", "-ss", "%.2f" % f["start"],
                        "-to", "%.2f" % f["end"], "-i", p["src"], "-vf", "scale=-2:360",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac",
                        "-b:a", "96k", "-movflags", "+faststart", out], check=True)
    return out


# ------------------------------------------------------------------ step 2: subtitles
def make_texts(pid, settings):
    try:
        p = load(pid)
        with open(os.path.join(proj_dir(pid), "words.json"), encoding="utf-8") as f:
            words = json.load(f)
        langs = tuple(l for l in ("en", "ru") if p["versions"].get(l))
        frs = [f for f in p["fragments"] if f["status"] == "ok"]
        for n, f in enumerate(frs):
            update(pid, progress={"step": "subs", "frac": n / max(len(frs), 1)})
            core = [w for w in words if f["start"] - 0.2 <= w["s"] < f["end"]]
            tail = [w for w in words if f["end"] <= w["s"] < min(f["end"] + 60, f["start"] + 178)]
            before = " ".join(w["w"] for w in words if f["start"] - 60 <= w["s"] < f["start"] - 0.2)
            after = " ".join(w["w"] for w in words if f["end"] + 60 <= w["s"] < f["end"] + 100)
            ws = core + tail
            subs = llm.make_subtitles(settings["deepseek_key"], ws, langs,
                                      src_lang_name=LANG_NAMES.get(p["lang"], "Telugu"),
                                      before=before, after=after, glossary=glossary_text(),
                                      last_core=len(core) - 1) if ws else []
            with LOCK:
                q = load(pid)
                for g in q["fragments"]:
                    if g["id"] == f["id"]:
                        g["subs"] = subs
                        if subs:
                            g["end"] = round(subs[-1]["end"] + 0.4, 2)
                save(q)
        update(pid, status="text", progress={"step": "done", "frac": 1})
        notify("Text is ready to check", p["name"])
    except Exception as e:
        traceback.print_exc()
        update(pid, status="error", error=str(e))


def edit_sub(pid, fid, idx, lang, text):
    with LOCK:
        p = load(pid)
        for f in p["fragments"]:
            if f["id"] == fid:
                old = f["subs"][idx].get(lang, "")
                f["subs"][idx][lang] = text
                f["subs"][idx]["flag"] = ""
                add_correction(old, text)
        save(p)


# ------------------------------------------------------------------ step 3: render
def template_dirs():
    out = {}
    for root in (os.path.join(paths.app_root(), "templates"), paths.sub("templates")):
        if os.path.isdir(root):
            for t in os.listdir(root):
                if os.path.exists(os.path.join(root, t, "template.json")):
                    out[t] = os.path.join(root, t)
    return out


def render_all(pid, settings, langs=None):
    try:
        p = load(pid)
        tdir = template_dirs().get(p["template"]) or template_dirs()["jnana-prakasha"]
        t = R.load_template(tdir)
        fonts = R.Fonts(os.path.join(paths.app_root(), "fonts"))
        out_dir = os.path.join(paths.output_root(), p["name"])
        os.makedirs(out_dir, exist_ok=True)
        overlay = os.path.join(proj_dir(pid), "overlay_%s.png" % t["id"])
        R.render_overlay(t, fonts, overlay)
        if langs is None:
            langs = [l for l in ("en", "ru") if p["versions"].get(l)]
            if "ru" in langs and p["ru_review"] and not p.get("ru_done"):
                langs.remove("ru")
        frs = [f for f in p["fragments"] if f["status"] == "ok"]
        outputs = [o for o in p.get("outputs", []) if o["lang"] not in langs]
        jobs = [(f, l) for f in frs for l in langs]
        for n, (f, lang) in enumerate(jobs):
            update(pid, status="rendering", progress={"step": "render", "frac": n / max(len(jobs), 1)})
            num = frs.index(f) + 1
            name = "%02d_%s_%s.mp4" % (num, slugify(f["title_en"]), lang.upper())
            dst = os.path.join(out_dir, name)
            cues = R.make_cues([(s["start"] - f["start"], s["end"] - f["start"], s.get(lang, ""))
                                for s in f["subs"]], 42 if lang == "en" else 40)
            ass = os.path.join(proj_dir(pid), "f%d_%s.ass" % (f["id"], lang))
            title = f["title_" + lang] or f["title_en"]
            R.build_ass(t, fonts, title_words(title, f.get("accent_" + lang)), lang, p.get("series", ""),
                        SERIES_SCRIPT.get(p["lang"], "te"), cues, f["end"] - f["start"], ass)
            R.render_short(p["src"], f["start"], f["end"], dst, overlay, ass,
                           os.path.join(paths.app_root(), "fonts"), t, ffmpeg=paths.tool("ffmpeg"),
                           ffprobe=paths.tool("ffprobe"), crop_x_frac=p.get("crop_x", 0.5))
            outputs.append({"fid": f["id"], "lang": lang, "file": dst, "name": name})
        update(pid, outputs=outputs, status="done", progress={"step": "done", "frac": 1})
        notify("Shorts are ready", p["name"])
        p = load(pid)
        if p["versions"].get("ru") and p["ru_review"] and not p.get("ru_sent") and not p.get("ru_done"):
            send_ru_review(pid, settings)
    except Exception as e:
        traceback.print_exc()
        update(pid, status="error", error=str(e))


# ------------------------------------------------------------------ Russian review by e-mail
def ru_review_text(p):
    lines = ["Pravachanam Shorts — %s" % p["name"], "PS-%s" % p["id"], "",
             "Исправьте текст после «|». Номера и знак «|» не меняйте. Сохраните файл и отправьте его ответом на это письмо.", ""]
    for n, f in enumerate([f for f in p["fragments"] if f["status"] == "ok"], 1):
        lines.append("## %d. %s" % (n, f.get("title_ru") or f.get("title_en")))
        for i, s in enumerate(f["subs"], 1):
            lines.append("F%d.%02d | %s" % (f["id"], i, s.get("ru", "")))
        lines.append("")
    return "\n".join(lines)


def send_ru_review(pid, settings):
    p = load(pid)
    if not (settings.get("smtp_user") and settings.get("smtp_password") and settings.get("reviewer_email")):
        update(pid, ru_note="no_email_settings")
        return
    import smtplib
    from email.message import EmailMessage
    m = EmailMessage()
    m["Subject"] = "[PS-%s] Russian subtitles for review — %s" % (p["id"], p["name"])
    m["From"] = settings["smtp_user"]
    m["To"] = settings["reviewer_email"]
    m.set_content("Namaste! Russian subtitles are attached. Please correct the file and reply with it attached.\n\n"
                  "Русские субтитры во вложении. Исправьте файл и отправьте его ответом на это письмо.")
    m.add_attachment(ru_review_text(p).encode("utf-8"), maintype="text", subtype="plain",
                     filename="RU_%s.txt" % slugify(p["name"]))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(settings["smtp_user"], settings["smtp_password"])
        s.send_message(m)
    update(pid, ru_sent=True, ru_note="sent")


def apply_ru_review(pid, text, settings):
    """Apply a corrected review file and render the Russian Shorts."""
    with LOCK:
        p = load(pid)
        by_id = {f["id"]: f for f in p["fragments"]}
        for m in re.finditer(r"^F(\d+)\.(\d+)\s*\|\s*(.*)$", text, re.M):
            f = by_id.get(int(m.group(1)))
            i = int(m.group(2)) - 1
            if f and 0 <= i < len(f["subs"]):
                new = m.group(3).strip()
                add_correction(f["subs"][i].get("ru", ""), new)
                f["subs"][i]["ru"] = new
        p["ru_done"] = True
        save(p)
    render_all(pid, settings, langs=["ru"])


def check_ru_mail(settings):
    """Look in the sender's Gmail inbox for replies with corrected files (called every few minutes)."""
    if not (settings.get("smtp_user") and settings.get("smtp_password")):
        return
    waiting = [x["id"] for x in list_projects()]
    waiting = [pid for pid in waiting if (lambda q: q.get("ru_sent") and not q.get("ru_done"))(load(pid))]
    if not waiting:
        return
    import email
    import imaplib
    with imaplib.IMAP4_SSL("imap.gmail.com") as M:
        M.login(settings["smtp_user"], settings["smtp_password"])
        M.select("INBOX")
        for pid in waiting:
            typ, data = M.search(None, '(SUBJECT "PS-%s")' % pid)
            for num in reversed(data[0].split()):
                typ, msg = M.fetch(num, "(RFC822)")
                em = email.message_from_bytes(msg[0][1])
                if em.get("From", "").lower().find(settings["smtp_user"].lower()) >= 0:
                    continue  # our own sent copy
                for part in em.walk():
                    fn = part.get_filename() or ""
                    if fn.lower().endswith(".txt"):
                        txt = part.get_payload(decode=True).decode("utf-8", "replace")
                        if "F" in txt and "|" in txt:
                            threading.Thread(target=apply_ru_review, args=(pid, txt, settings), daemon=True).start()
                            break
                else:
                    continue
                break


# ------------------------------------------------------------------ Windows notification
def notify(title, text):
    try:
        if os.name == "nt":
            import subprocess
            ps = ("[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
                  "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Information;"
                  "$n.Visible=$true;$n.ShowBalloonTip(8000,'%s','%s',[System.Windows.Forms.ToolTipIcon]::Info);"
                  "Start-Sleep 9;$n.Dispose()") % (title.replace("'", ""), text.replace("'", ""))
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                             creationflags=0x08000000)
    except Exception:
        pass


def delete(pid):
    shutil.rmtree(proj_dir(pid), ignore_errors=True)
