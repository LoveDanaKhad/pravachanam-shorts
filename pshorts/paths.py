"""Where the app keeps its files on the user's computer."""
import json
import os
import sys

APP_NAME = "PravachanamShorts"


def app_root():
    """Folder with the program's own files (fonts, templates, ui, bin)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_root():
    """Per-user data: settings, models, projects, user templates, glossary."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def sub(*parts):
    p = os.path.join(data_root(), *parts)
    os.makedirs(p, exist_ok=True)
    return p


def output_root():
    d = os.path.join(os.path.expanduser("~"), "Videos", "Pravachanam Shorts")
    os.makedirs(d, exist_ok=True)
    return d


def tool(name):
    """ffmpeg / ffprobe: bundled copy in bin/ if present, else from PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    p = os.path.join(app_root(), "bin", exe)
    return p if os.path.exists(p) else name


DEFAULT_SETTINGS = {
    "ui_lang": "en",
    "asr_engine": "local",          # local | sarvam
    "deepseek_key": "",
    "sarvam_key": "",
    "send_ru_review": True,
    "reviewer_email": "",
    "smtp_user": "",                # sender Gmail address
    "smtp_password": "",            # Gmail app password
    "auto_update": True,
    "default_template": "jnana-prakasha",
}


def load_settings():
    p = os.path.join(data_root(), "settings.json")
    s = dict(DEFAULT_SETTINGS)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                s.update(json.load(f))
        except (OSError, ValueError):
            pass
    return s


def save_settings(s):
    p = os.path.join(data_root(), "settings.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
