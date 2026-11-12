"""Local web server: serves the interface and a small JSON API on http://127.0.0.1:8765."""
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import paths, project as P

try:
    from .version import VERSION
except ImportError:
    VERSION = "0.0.0"
PORT = 8765
SECRET_KEYS = ("deepseek_key", "sarvam_key", "smtp_password")


def public_settings(s):
    out = {k: v for k, v in s.items() if k not in SECRET_KEYS}
    for k in SECRET_KEYS:
        out["has_" + k] = bool(s.get(k))
    return out


def templates_info():
    out = []
    for tid, d in sorted(P.template_dirs().items()):
        try:
            with open(os.path.join(d, "template.json"), encoding="utf-8") as f:
                t = json.load(f)
            out.append({"id": tid, "name": t.get("name", tid), "status": t.get("status", ""),
                        "colors": t.get("colors", {}), "brand": t.get("brand", ""),
                        "logo": "/tpl/%s/%s" % (tid, t.get("logo", "logo.png"))})
        except (OSError, ValueError):
            pass
    return out


def choose_file_dialog():
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$d=New-Object System.Windows.Forms.OpenFileDialog;"
          "$d.Filter='Video|*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v|All files|*.*';"
          "$d.Title='Choose a video';"
          "if($d.ShowDialog() -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8;$d.FileName}")
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    return r.stdout.decode("utf-8", "replace").strip()


def allowed_media(path):
    rp = os.path.realpath(path)
    return any(rp.startswith(os.path.realpath(r)) for r in (paths.data_root(), paths.output_root()))


class Handler(BaseHTTPRequestHandler):
    server_version = "PravachanamShorts/" + VERSION

    def log_message(self, *a):
        pass

    # ---------------------------------------------------------------- helpers
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def _file(self, path, ctype=None):
        if not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        size = os.path.getsize(path)
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                b = f.read(min(1 << 20, left))
                if not b:
                    break
                try:
                    self.wfile.write(b)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(b)

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        ui = os.path.join(paths.app_root(), "ui")
        if path in ("/", "/index.html"):
            return self._file(os.path.join(ui, "index.html"), "text/html; charset=utf-8")
        if path.startswith("/ui/fonts/"):
            fd = os.path.join(paths.app_root(), "fonts")
            fp = os.path.realpath(os.path.join(fd, os.path.basename(path)))
            return self._file(fp)
        if path.startswith("/ui/"):
            fp = os.path.realpath(os.path.join(ui, path[4:]))
            if fp.startswith(os.path.realpath(ui)):
                return self._file(fp)
        if path.startswith("/tpl/"):
            parts = path.split("/")
            d = P.template_dirs().get(parts[2])
            if d:
                fp = os.path.realpath(os.path.join(d, "/".join(parts[3:])))
                if fp.startswith(os.path.realpath(d)):
                    return self._file(fp)
        if path == "/api/state":
            return self._json({"version": VERSION, "settings": public_settings(paths.load_settings()),
                               "projects": P.list_projects(), "templates": templates_info(),
                               "output_root": paths.output_root()})
        m = re.match(r"^/api/project/([\w-]+)$", path)
        if m:
            p = P.load(m.group(1))
            p.pop("words", None)
            return self._json(p)
        m = re.match(r"^/api/project/([\w-]+)/preview/(\d+)$", path)
        if m:
            return self._file(P.preview_clip(m.group(1), int(m.group(2))), "video/mp4")
        if path == "/media" and q.get("path"):
            fp = q["path"][0]
            if allowed_media(fp):
                return self._file(fp)
        return self._json({"error": "not found"}, 404)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        s = paths.load_settings()
        try:
            if path == "/api/choose_file":
                return self._json({"path": choose_file_dialog()})
            if path == "/api/upload":
                name = os.path.basename(urllib.parse.parse_qs(u.query).get("name", ["video.mp4"])[0])
                dst = os.path.join(paths.sub("uploads"), name)
                n = int(self.headers.get("Content-Length") or 0)
                with open(dst, "wb") as f:
                    while n > 0:
                        b = self.rfile.read(min(1 << 20, n))
                        if not b:
                            break
                        f.write(b)
                        n -= len(b)
                return self._json({"path": dst})
            if path == "/api/template_add":
                n = int(self.headers.get("Content-Length") or 0)
                tmp = os.path.join(paths.data_root(), "tpl_upload.zip")
                with open(tmp, "wb") as f:
                    f.write(self.rfile.read(n))
                with zipfile.ZipFile(tmp) as z:
                    names = z.namelist()
                    tj = next(x for x in names if x.endswith("template.json"))
                    tid = json.loads(z.read(tj).decode("utf-8")).get("id") or "custom-%d" % time.time()
                    dst = paths.sub("templates", re.sub(r"[^\w-]", "-", tid))
                    prefix = tj[:-len("template.json")]
                    for x in names:
                        if x.startswith(prefix) and not x.endswith("/") and ".." not in x:
                            out = os.path.join(dst, x[len(prefix):])
                            os.makedirs(os.path.dirname(out), exist_ok=True)
                            with open(out, "wb") as f:
                                f.write(z.read(x))
                os.remove(tmp)
                return self._json({"ok": True, "templates": templates_info()})
            if path == "/api/settings":
                b = self._body()
                for k, v in b.items():
                    if k in paths.DEFAULT_SETTINGS and not (k in SECRET_KEYS and v in ("", None)):
                        s[k] = v
                paths.save_settings(s)
                return self._json({"settings": public_settings(s)})
            if path == "/api/open_folder":
                fp = self._body().get("path") or paths.output_root()
                if os.name == "nt" and os.path.exists(fp):
                    os.startfile(fp)
                return self._json({"ok": True})
            if path == "/api/project":
                b = self._body()
                if not s.get("deepseek_key"):
                    return self._json({"error": "no_deepseek_key"}, 400)
                p = P.create(b["path"], b.get("opts", {}))
                threading.Thread(target=P.analyse, args=(p["id"], s), daemon=True).start()
                return self._json(p)

            m = re.match(r"^/api/project/([\w-]+)/(\w+)$", path)
            if not m:
                return self._json({"error": "not found"}, 404)
            pid, action = m.group(1), m.group(2)
            b = self._body()
            if action == "fragment":
                with P.LOCK:
                    p = P.load(pid)
                    for f in p["fragments"]:
                        if f["id"] == b["fid"]:
                            if b["action"] in ("ok", "no"):
                                f["status"] = b["action"]
                            elif b["action"] == "shift":
                                v = max(0.0, f[b["field"]] + float(b["delta"]))
                                if (b["field"] == "start" and v < f["end"] - 5) or \
                                   (b["field"] == "end" and v > f["start"] + 5):
                                    f[b["field"]] = round(v, 2)
                                    f["subs"] = []
                    P.save(p)
                return self._json(p)
            if action == "texts":
                P.update(pid, status="processing", progress={"step": "subs", "frac": 0})
                threading.Thread(target=P.make_texts, args=(pid, s), daemon=True).start()
                return self._json({"ok": True})
            if action == "sub":
                P.edit_sub(pid, b["fid"], b["idx"], b["lang"], b["text"])
                return self._json({"ok": True})
            if action == "fields":
                with P.LOCK:
                    p = P.load(pid)
                    for k in ("template", "series", "crop_x"):
                        if k in b:
                            p[k] = b[k]
                    for f in p["fragments"]:
                        if f["id"] == b.get("fid"):
                            for k in ("title_en", "title_ru", "accent_en", "accent_ru"):
                                if k in b:
                                    f[k] = b[k]
                    P.save(p)
                return self._json(p)
            if action == "render":
                P.update(pid, status="rendering", progress={"step": "render", "frac": 0})
                threading.Thread(target=P.render_all, args=(pid, s), daemon=True).start()
                return self._json({"ok": True})
            if action == "ru_import":
                threading.Thread(target=P.apply_ru_review, args=(pid, b["text"], s), daemon=True).start()
                return self._json({"ok": True})
            if action == "status":
                return self._json(P.update(pid, status=b["status"]))
            if action == "delete":
                P.delete(pid)
                return self._json({"ok": True})
            return self._json({"error": "unknown action"}, 404)
        except Exception as e:  # report errors to the page instead of crashing
            return self._json({"error": str(e)}, 500)


def mail_loop():
    while True:
        time.sleep(300)
        try:
            P.check_ru_mail(paths.load_settings())
        except Exception:
            pass


def already_running():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            return True
    except OSError:
        return False


def main():
    url = "http://127.0.0.1:%d/" % PORT
    if already_running():
        webbrowser.open(url)
        return
    # projects interrupted by a restart go back to a state the user can continue from
    for x in P.list_projects():
        if x["status"] in ("processing", "rendering"):
            P.update(x["id"], status="error", error="interrupted")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=mail_loop, daemon=True).start()
    try:
        from . import updater
        threading.Thread(target=updater.check_and_install, args=(VERSION,), daemon=True).start()
    except Exception:
        pass
    def prefetch():  # download the speech models right away (Telugu and Sanskrit)
        for lang in ("te", "sa"):
            try:
                P.ensure_model(lang)
            except Exception:
                pass
    threading.Thread(target=prefetch, daemon=True).start()
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
