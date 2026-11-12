"""Automatic updates from GitHub Releases (public repo, no password needed)."""
import json
import os
import subprocess
import tempfile
import time
import urllib.request

from . import paths

REPO = "LoveDanaKhad/pravachanam-shorts"


def _ver(s):
    return tuple(int(x) for x in s.lstrip("v").split(".") if x.isdigit())


def check_and_install(current):
    if os.name != "nt" or not paths.load_settings().get("auto_update", True):
        return
    time.sleep(20)  # let the app start first
    try:
        req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % REPO,
                                     headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            rel = json.loads(r.read().decode("utf-8"))
        if _ver(rel.get("tag_name", "0")) <= _ver(current):
            return
        asset = next(a for a in rel.get("assets", []) if a["name"].lower().endswith("setup.exe"))
        from . import project as P
        while any(x["status"] in ("processing", "rendering") for x in P.list_projects()):
            time.sleep(60)  # never interrupt work in progress
        dst = os.path.join(tempfile.gettempdir(), asset["name"])
        with urllib.request.urlopen(asset["browser_download_url"], timeout=120) as r, open(dst, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        P.notify("Pravachanam Shorts", "Installing update %s…" % rel["tag_name"])
        subprocess.Popen([dst, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         creationflags=0x00000008)  # DETACHED_PROCESS
    except Exception:
        pass
