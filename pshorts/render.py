"""Render a vertical Short (1080x1920) from a source video using a design template.

Graphics (background, logo, frame) are drawn with Pillow into a PNG with a
transparent window for the video. All text is drawn by libass (ASS file), so
Telugu / Devanagari shaping works the same on every computer.
"""
import json
import os
import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from fontTools.ttLib import TTFont

W, H = 1080, 1920

FONT_FILES = {
    "PS Fraunces": "PSFraunces.ttf",
    "PS Fraunces Italic": "PSFrauncesItalic.ttf",
    "PS Cormorant": "PSCormorant.ttf",
    "PS Cormorant Italic": "PSCormorantItalic.ttf",
    "PS Inter SemiBold": "PSInterSemiBold.ttf",
    "PS Inter Medium": "PSInterMedium.ttf",
    "PS Telugu": "PSTelugu.ttf",
    "PS Devanagari": "PSDevanagari.ttf",
}


def load_template(tdir):
    with open(os.path.join(tdir, "template.json"), encoding="utf-8") as f:
        t = json.load(f)
    t["dir"] = tdir
    return t


def _rgb(hexs):
    hexs = hexs.lstrip("#")
    return tuple(int(hexs[i:i + 2], 16) for i in (0, 2, 4))


def _ass_color(hexs, alpha=0):
    r, g, b = _rgb(hexs)
    return "&H%02X%02X%02X%02X" % (alpha, b, g, r)


@lru_cache(None)
def _ass_scale(font_path):
    """libass sizes fonts by ascent+descent; convert a CSS em size to ASS size."""
    f = TTFont(font_path)
    os2 = f["OS/2"]
    upm = f["head"].unitsPerEm
    return (os2.usWinAscent + os2.usWinDescent) / upm


class Fonts:
    def __init__(self, fonts_dir):
        self.dir = fonts_dir

    def path(self, family):
        return os.path.join(self.dir, FONT_FILES[family])

    def pil(self, family, px):
        return ImageFont.truetype(self.path(family), px)

    def ass_size(self, family, css_px):
        return round(css_px * _ass_scale(self.path(family)), 1)

    def width(self, family, px, text, spacing=0.0):
        f = self.pil(family, px)
        return f.getlength(text) + spacing * max(len(text) - 1, 0)


# ---------------------------------------------------------------- overlay PNG
def render_overlay(t, fonts, out_png):
    c = t["colors"]
    v = t["video"]
    img = Image.new("RGBA", (W, H), _rgb(c["bg"]) + (255,))

    # soft glow at the top
    glow = Image.new("L", (W, 520), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-200, -420, W + 200, 420), fill=26)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    layer = Image.new("RGBA", (W, 520), _rgb(c["glow"]) + (0,))
    layer.putalpha(glow)
    img.alpha_composite(layer, (0, 0))

    d = ImageDraw.Draw(img)
    # decorative lines around the label (text itself is drawn by libass)
    lw = fonts.width("PS Inter SemiBold", 24, t["label"], 24 * 0.32)
    y = 70 + 14
    d.line((W / 2 - lw / 2 - 22 - 56, y, W / 2 - lw / 2 - 22, y), fill=_rgb(c["accent"]) + (153,), width=2)
    d.line((W / 2 + lw / 2 + 22, y, W / 2 + lw / 2 + 22 + 56, y), fill=_rgb(c["accent"]) + (153,), width=2)

    # logo medallion with gold ring and shadow
    logo_path = os.path.join(t["dir"], t["logo"])
    if os.path.exists(logo_path):
        size, lx, ly = 150, 60, 128
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse((lx, ly + 10, lx + size, ly + size + 10), fill=_rgb(c["accent"]) + (70,))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
        logo = Image.open(logo_path).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        img.paste(logo, (lx, ly), Image.composite(logo.getchannel("A"), Image.new("L", (size, size), 0), mask))
        d = ImageDraw.Draw(img)
        d.ellipse((lx - 3, ly - 3, lx + size + 2, ly + size + 2), outline=_rgb(c["gold"]), width=3)

    # video frame and terracotta corners
    x0, y0, s = v["x"], v["y"], v["size"]
    d.rounded_rectangle((x0 - 4, y0 - 4, x0 + s + 3, y0 + s + 3), radius=6, outline=_rgb(c["line"]), width=2)
    a = _rgb(c["accent"])
    L, k = 40, 3
    for cx, cy, dx, dy in ((x0 - 16, y0 - 16, 1, 1), (x0 + s + 15, y0 - 16, -1, 1),
                           (x0 - 16, y0 + s + 15, 1, -1), (x0 + s + 15, y0 + s + 15, -1, -1)):
        d.line((cx, cy, cx + dx * L, cy), fill=a, width=k)
        d.line((cx, cy, cx, cy + dy * L), fill=a, width=k)

    # decorative lines around the brand line
    bw = fonts.width("PS Inter SemiBold", 22, t["brand"], 22 * 0.3)
    by = H - 120 - 13
    d.line((W / 2 - bw / 2 - 18 - 46, by, W / 2 - bw / 2 - 18, by), fill=_rgb(c["line"]), width=2)
    d.line((W / 2 + bw / 2 + 18, by, W / 2 + bw / 2 + 18 + 46, by), fill=_rgb(c["line"]), width=2)

    # transparent window for the video
    hole = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(hole, (x0, y0))
    img.save(out_png)
    return out_png


# ---------------------------------------------------------------- title layout
def split_title(words, fonts, family, px, max_w=790):
    """Split title words into 1–2 balanced lines, shrinking the size if needed."""
    while px > 40:
        text = " ".join(w for w, _ in words)
        if len(words) <= 2 and fonts.width(family, px, text) <= max_w:
            return [words], px
        best = None
        for i in range(1, len(words)):
            a = " ".join(w for w, _ in words[:i])
            b = " ".join(w for w, _ in words[i:])
            wa, wb = fonts.width(family, px, a), fonts.width(family, px, b)
            if max(wa, wb) <= max_w and (best is None or max(wa, wb) < best[0]):
                best = (max(wa, wb), i)
        if best:
            i = best[1]
            return [words[:i], words[i:]], px
        px = int(px * 0.9)
    return [words], px


def _esc(s):
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


# ---------------------------------------------------------------- subtitles
def wrap_lines(text, max_chars=38):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def make_cues(chunks, max_chars=38):
    """chunks: [(start, end, text)] -> cues of at most 2 lines, time split by length."""
    cues = []
    for s, e, text in chunks:
        lines = wrap_lines(text, max_chars)
        groups = [lines[i:i + 2] for i in range(0, len(lines), 2)] or [[""]]
        total = sum(len(" ".join(g)) for g in groups) or 1
        t = s
        for g in groups:
            dur = (e - s) * len(" ".join(g)) / total
            cues.append((t, t + dur, "\\N".join(_esc(x) for x in g)))
            t += dur
    return cues


def _ts(x):
    x = max(0.0, x)
    h, m = int(x // 3600), int(x % 3600 // 60)
    s = x % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def build_ass(t, fonts, title_words, lang, series_text, series_script, cues, duration, out_ass):
    """title_words: [(word, is_accent)], lang: 'en' or 'ru'."""
    c = t["colors"]
    F = t["fonts"]
    ink, acc, muted = _ass_color(c["ink"]), _ass_color(c["accent"]), _ass_color(c["muted"])
    if lang == "ru":
        tf, tfi, tpx, ttop, lh = F["title_ru"], F["title_ru_italic"], 82, 122, 0.96
    else:
        tf, tfi, tpx, ttop, lh = F["title_en"], F["title_en_italic"], 76, 130, 1.04
    lines, tpx = split_title(title_words, fonts, tf, tpx)
    sub_px = 54
    z0, z1 = t["subtitle_zone"]
    sf = F["series_te"] if series_script == "te" else F["series_hi"]

    styles = [
        ("Sub", F["subtitle"], fonts.ass_size(F["subtitle"], sub_px), ink, 5),
        ("Text", F["label"], 20, ink, 7),
    ]
    head = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % W, "PlayResY: %d" % H,
            "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"]
    for name, font, size, col, al in styles:
        head.append("Style: %s,%s,%s,%s,%s,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,%d,0,0,0,1"
                    % (name, font, size, col, col, al))
    ev = ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    end = _ts(duration + 1)

    def static(text):
        ev.append("Dialogue: 1,0:00:00.00,%s,Text,,0,0,0,,%s" % (end, text))

    def tag(font, css_px, color, spacing_em=0.0, pos=None, an=7):
        size = fonts.ass_size(font, css_px)
        sp = round(css_px * spacing_em, 2)
        p = "\\pos(%d,%d)" % pos if pos else ""
        return "{\\an%d%s\\fn%s\\fs%s\\fsp%s\\c%s}" % (an, p, font, size, sp, color)

    # label, name line, series and brand
    static(tag(F["label"], 24, acc, 0.32, (W // 2, 70), 8) + _esc(t["label"]))
    static(tag(F["who"], 26, acc, 0.14, (W // 2, 318), 8) + _esc(t["who"]))
    if series_text:
        static(tag(sf, 30, muted, 0, (W // 2, H - 120 - 44), 2) + _esc(series_text))
    static(tag(F["label"], 22, _ass_color(c["ink"], 0x4D), 0.3, (W // 2, H - 120 + 2), 2) + _esc(t["brand"]))

    # title: 1–2 lines, accent word in italic + accent colour
    step = tpx * lh
    for i, line in enumerate(lines):
        parts = []
        for w, is_acc in line:
            if is_acc:
                parts.append("{\\fn%s\\c%s}%s{\\fn%s\\c%s}" % (tfi, acc, _esc(w), tf, ink))
            else:
                parts.append(_esc(w))
        static(tag(tf, tpx, ink, -0.01, (240, int(ttop + i * step)), 7) + " ".join(parts))

    # subtitles centred in the subtitle zone
    cy = (z0 + z1) // 2
    for s, e, text in cues:
        ev.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,{\\an5\\pos(%d,%d)}%s" % (_ts(s), _ts(e), W // 2, cy, text))

    with open(out_ass, "w", encoding="utf-8") as f:
        f.write("\n".join(head + ev) + "\n")
    return out_ass


# ---------------------------------------------------------------- ffmpeg
def probe_size(ffprobe, src):
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", src],
                         capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def render_short(src, start, end, out_mp4, overlay_png, ass_path, fonts_dir, t,
                 ffmpeg="ffmpeg", ffprobe="ffprobe", crop_x_frac=0.5, crf=20):
    vw, vh = probe_size(ffprobe, src)
    side = min(vw, vh)
    cx = int(round((vw - side) * crop_x_frac))
    cy = int(round((vh - side) / 2))
    v = t["video"]
    bg = t["colors"]["bg"].lstrip("#")

    def esc(p):  # ffmpeg filter path escaping (works for Windows paths too)
        return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    fc = (
        "[0:v]crop={s}:{s}:{cx}:{cy},scale={vs}:{vs},setsar=1[v];"
        "color=c=0x{bg}:s={W}x{H}:r=25[bgc];"
        "[bgc][v]overlay={vx}:{vy}:shortest=1[base];"
        "[base][1:v]overlay=0:0[ov];"
        "[ov]ass='{ass}':fontsdir='{fd}'[out]"
    ).format(s=side, cx=cx, cy=cy, vs=v["size"], bg=bg, W=W, H=H, vx=v["x"], vy=v["y"],
             ass=esc(ass_path), fd=esc(fonts_dir))
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", "%.3f" % start, "-to", "%.3f" % end, "-i", src,
           "-loop", "1", "-i", overlay_png, "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", out_mp4]
    subprocess.run(cmd, check=True)
    return out_mp4
