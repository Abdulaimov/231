#!/usr/bin/env python3
"""Сборка сайта 231inc.

    python3 build.py

Берёт тексты, цены и списки работ из content.json, фото и видео из originals/,
стили, скрипт и шрифты из src/ и собирает готовый сайт в папку site/.
На хостинг выкладывается только site/.

Нужны Python 3.9+ и Pillow 11.2+ (pip install pillow): он сохраняет AVIF и WebP.
Без поддержки AVIF сайт соберётся с WebP и JPEG. Для видео нужен ffmpeg
(в PATH или путь в переменной окружения FFMPEG).
Повторная сборка пересжимает только новые и изменённые файлы.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import urllib.parse
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, features

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
ORIG = ROOT / "originals"
OUT = ROOT / "site"
CACHE = ROOT / ".cache"

C = json.loads((ROOT / "content.json").read_text("utf-8"))

WIDTHS = [480, 720, 960, 1280, 1600]
HAS_AVIF = features.check("avif")
QUALITY = {"avif": 58, "webp": 74, "jpg": 80}
SLANT_TAN = 0.19438  # tan(11°): фирменный наклон −11°

LOGO = re.search(r'd="([^"]+)"', (SRC / "logo.svg").read_text()).group(1)
WM = json.loads((SRC / "fonts" / "wordmark.json").read_text())


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def is_hex_id(key: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", key))


def short(key: str) -> str:
    return key[:10] if is_hex_id(key) else key


def bare(ref: str) -> str:
    return ref[2:] if ref.startswith("v:") else ref


def fresh(out: Path, src: Path) -> bool:
    return out.exists() and out.stat().st_mtime >= src.stat().st_mtime


# ---------------------------------------------------------------- тексты

def parse_prices(text):
    """Прайс видеопроизводства: «Название | цена», пункты с «•», «Примечание: …» (как на старом сайте)."""
    out, cur = {"plans": [], "note": ""}, None
    for line in str(text or "").split("\n"):
        l = line.strip()
        if not l or re.match(r"^https?://", l, re.I):
            continue
        m = re.match(r"^Примечание\s*:\s*(.*)$", l, re.I)
        if m:
            out["note"], cur = m.group(1), None
            continue
        if re.match(r"^[•\-–*·]", l):
            if cur:
                cur["items"].append(re.sub(r"^[•\-–*·]\s*", "", l))
            continue
        m = re.match(r"^(?:\d+[.)]\s*)?(.+?)\s*\|\s*(.+)$", l)
        if m:
            pr = m.group(2).strip()
            frm = bool(re.match(r"^от\s+", pr, re.I))
            v = re.sub(r"^от\s+", "", pr, flags=re.I)
            cm = re.match(r"^([\d\s]+)\s*(.*)$", v)
            cur = {"title": m.group(1).strip(), "from": frm, "items": [],
                   "amount": cm.group(1).strip() if cm else v, "cur": cm.group(2).strip() if cm else ""}
            out["plans"].append(cur)
            continue
        if cur:
            cur["items"].append(l)
    return out


def parse_smm(text):
    """Тарифы SMM: «НАЗВАНИЕ | цена», описание, пункты «Жирное начало. Пояснение», «Результат: …»."""
    plans, cur = [], None
    for line in str(text or "").split("\n"):
        l = line.strip()
        if not l or re.match(r"^[⸻—-]+$", l) or re.match(r"^в пакет входит", l, re.I):
            continue
        m = re.match(r"^(.+?)\s*\|\s*([\d\s]+)\s*(.*)$", l)
        if m:
            cur = {"title": m.group(1).strip(), "amount": m.group(2).strip(), "cur": m.group(3).strip(),
                   "desc": "", "items": [], "result": ""}
            plans.append(cur)
            continue
        if not cur:
            continue
        if re.match(r"^[•\-–*·]", l):
            it = re.sub(r"^[•\-–*·]\s*", "", l)
            k = it.find(". ")
            cur["items"].append({"b": it[:k + 1], "t": it[k + 2:]} if 0 < k < 44 else {"b": "", "t": it})
            continue
        r = re.match(r"^Результат\s*:\s*(.*)$", l, re.I)
        if r:
            cur["result"] = r.group(1)
            continue
        cur["desc"] = f'{cur["desc"]} {l}' if cur["desc"] else l
    return plans


def parse_all(text):
    out, cur = [], None
    for line in str(text or "").split("\n"):
        l = line.strip()
        if not l:
            continue
        m = re.match(r"^(\d{1,2})[.)]\s*(.+)$", l)
        if m:
            cur = {"n": m.group(1).zfill(2), "title": m.group(2), "text": ""}
            out.append(cur)
            continue
        if cur:
            cur["text"] = f'{cur["text"]} {l}' if cur["text"] else l
    return out


def yt_ok(u) -> bool:
    return bool(re.match(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", str(u or "").strip(), re.I))


def ig_name(u) -> str:
    m = re.search(r"instagram\.com/([^/?#]+)", str(u or ""), re.I)
    return "@" + m.group(1) if m else "Открыть"


# ---------------------------------------------------------------- фото и видео

MEDIA: dict[str, dict] = {}


def find_original(key: str) -> Path:
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = ORIG / f"{key}.{ext}"
        if p.exists():
            return p
    raise SystemExit(f"Нет файла для «{key}» в originals/")


def pick_widths(w: int, widths) -> list[int]:
    top = min(w, widths[-1])
    ws = [x for x in widths if x < top and top - x > 0.12 * top]
    return ws + [top]


def build_image(key: str, src: Path | None = None, crop=None, suffix: str = "", widths=WIDTHS,
                jpg_widths=(960, 1600), alt: str | None = None) -> dict:
    src = src or find_original(key)
    name = short(key) + suffix
    im = ImageOps.exif_transpose(Image.open(src))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if im.mode == "L":
        im = im.convert("RGB")
    if crop:
        W, H = im.size
        x0, y0, x1, y1 = crop
        im = im.crop((round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H)))
    W, H = im.size
    ws = pick_widths(W, widths)
    jws = sorted({min(W, j) for j in jpg_widths})
    c = im.resize((1, 1), Image.BOX).getpixel((0, 0))
    jobs = [(w, "webp") for w in ws] + [(w, "jpg") for w in jws]
    if HAS_AVIF:
        jobs += [(w, "avif") for w in ws]
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    for w, ext in jobs:
        out = OUT / "img" / f"{name}-{w}.{ext}"
        if fresh(out, src):
            continue
        r = im if w == W else im.resize((w, round(H * w / W)), Image.LANCZOS)
        if ext == "avif":
            r.save(out, "AVIF", quality=QUALITY["avif"], speed=6)
        elif ext == "webp":
            r.save(out, "WEBP", quality=QUALITY["webp"], method=6)
        else:
            r.save(out, "JPEG", quality=QUALITY["jpg"], optimize=True, progressive=True)
    meta = {"w": W, "h": H, "ws": ws, "jw": jws, "base": f"img/{name}", "c": "#%02x%02x%02x" % c[:3],
            "alt": alt if alt is not None else C["media"].get(key, {}).get("alt", "")}
    MEDIA[key + suffix] = meta
    return meta


def ffmpeg() -> str | None:
    for cand in (os.environ.get("FFMPEG"), shutil.which("ffmpeg"), str(Path.home() / ".local/opt/bin/ffmpeg")):
        if cand and Path(cand).exists():
            return cand
    return None


def build_video(key: str) -> dict:
    info = C["media"].get(key, {})
    src = ORIG / f"{key}.mp4"
    name = short(key)
    (OUT / "media").mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    out = OUT / "media" / f"{name}-720.mp4"
    poster = CACHE / f"{name}-poster.jpg"
    ff = ffmpeg()
    if ff:
        if not fresh(out, src):
            subprocess.run([ff, "-y", "-v", "error", "-i", str(src), "-vf", "scale=720:-2", "-c:v", "libx264",
                            "-preset", "slow", "-crf", "26", "-profile:v", "high", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-c:a", "aac", "-b:a", "96k", str(out)], check=True)
        if not fresh(poster, src):
            subprocess.run([ff, "-y", "-v", "error", "-ss", str(info.get("posterAt", 0.5)), "-i", str(src),
                            "-frames:v", "1", "-q:v", "2", str(poster)], check=True)
        dur = subprocess.run([ff, "-i", str(out)], capture_output=True, text=True).stderr
        m = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", dur)
        secs = round(int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100) if m else 0
    elif out.exists() and poster.exists():
        secs = 0
    else:
        raise SystemExit("Для видео нужен ffmpeg: установите его или укажите путь в переменной FFMPEG")
    pm = build_image(key, src=poster, suffix="-poster", widths=[480, 720], jpg_widths=(720,), alt=info.get("alt", ""))
    meta = {"type": "video", "src": f"media/{name}-720.mp4", "poster": key + "-poster", "alt": info.get("alt", ""),
            "mb": round(out.stat().st_size / 1048576, 1), "sec": secs, "w": pm["w"], "h": pm["h"], "c": pm["c"]}
    MEDIA["v:" + key] = meta
    return meta


def build_all_media():
    refs: list[str] = []
    for p in C["team"]:
        refs += p["works"] + ([p["photo"]] if p.get("photo") else [])
    refs += C["studio"].get("photos", []) + [c["logo"] for c in C["smm"]["clients"] if c.get("logo")]
    for w in C.get("works", []):
        refs += [r for r in (w.get("poster"),) if r] + w.get("bts", [])
        refs += ["v:" + bare(r) for r in (w.get("video"), w.get("preview")) if r]
    refs += [b["ref"] for b in C.get("backstage", [])]
    for z in C["studio"].get("zones", []):
        refs += z.get("photos", [])
    seen = set()
    logos = {c["logo"] for c in C["smm"]["clients"] if c.get("logo")}
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        key = bare(ref)
        if ref.startswith("v:") or C["media"].get(key, {}).get("type") == "video":
            build_video(key)
        elif key in logos:
            build_image(key, widths=[320, 640], jpg_widths=(640,))
        else:
            build_image(key)
    h = C["hero"]
    if h.get("mobileCrop"):
        build_image(h["image"], crop=h["mobileCrop"], suffix="-m")


# ---------------------------------------------------------------- куски разметки

SIZES = {
    "a1": "(min-width: 1440px) 764px, (min-width: 768px) 54vw, calc(100vw - 32px)",
    "a2": "(min-width: 1440px) 427px, (min-width: 768px) 30vw, 64vw",
    "b": "(min-width: 1440px) 427px, (min-width: 768px) 30vw, 64vw",
    "c1": "(min-width: 1440px) 427px, (min-width: 768px) 30vw, 64vw",
    "c2": "(min-width: 1440px) 604px, (min-width: 768px) 43vw, calc(100vw - 32px)",
    "d": "(min-width: 1440px) 1127px, (min-width: 768px) 80vw, calc(100vw - 32px)",
    "s": "(min-width: 1440px) 604px, (min-width: 768px) 43vw, calc(100vw - 32px)",
    "v": "(min-width: 1440px) 427px, (min-width: 768px) 30vw, calc(100vw - 32px)",
    "hero": "(min-width: 1440px) 620px, (min-width: 768px) 44vw, 100vw",
    "portrait": "(min-width: 768px) 300px, 96px",
    "portrait-lg": "(min-width: 960px) 260px, 64vw",
    "logo": "(min-width: 768px) 30vw, calc(100vw - 32px)",
    "teaser": "(min-width: 1440px) 380px, (min-width: 768px) 28vw, 46vw",
    "f35": "(min-width: 768px) 460px, 80vw",
    "teaser-wide": "(min-width: 1440px) 780px, (min-width: 768px) 56vw, calc(100vw - 32px)",
}

ARROW_OUT = '<span class="arr" aria-hidden="true">↗</span>'
ARROW_R = '<span class="arr" aria-hidden="true">→</span>'


def srcset(m, ext):
    return ", ".join(f'{m["base"]}-{w}.{ext} {w}w' for w in m["ws"])


def picture(key, sizes, alt=None, eager=False, art=None, pos=None):
    m = MEDIA[key]
    alt = m["alt"] if alt is None else alt
    s = ["<picture>"]
    if art:
        mq, akey, asizes = art
        am = MEDIA[akey]
        if HAS_AVIF:
            s.append(f'<source media="{mq}" type="image/avif" srcset="{srcset(am, "avif")}" sizes="{asizes}">')
        s.append(f'<source media="{mq}" type="image/webp" srcset="{srcset(am, "webp")}" sizes="{asizes}">')
    if HAS_AVIF:
        s.append(f'<source type="image/avif" srcset="{srcset(m, "avif")}" sizes="{sizes}">')
    s.append(f'<source type="image/webp" srcset="{srcset(m, "webp")}" sizes="{sizes}">')
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    style = f' style="object-position:{esc(pos)}"' if pos else ""
    s.append(f'<img src="{m["base"]}-{m["jw"][0]}.jpg" width="{m["w"]}" height="{m["h"]}" alt="{esc(alt)}" '
             f'{load} decoding="async"{style}>')
    s.append("</picture>")
    return "".join(s)


def mono_svg(cls="mono"):
    return f'<svg class="{cls}" viewBox="0 0 1578 1708" aria-hidden="true" focusable="false"><path d="{LOGO}"/></svg>'


def wordmark_svg(cls="wm", slanted=False, label=None):
    x0, y0, w, h = WM["viewBox"]
    aria = f'role="img" aria-label="{esc(label)}"' if label else 'aria-hidden="true" focusable="false"'
    if not slanted:
        return f'<svg class="{cls}" viewBox="0 0 {w} {h}" {aria}><path d="{WM["p231"]}{WM["pinc"]}"/></svg>'
    sh, pad = round(h * SLANT_TAN), 24
    # каждая буква отдельно: в подвале цифры выезжают по очереди, а контур «INC» прорисовывается
    glyphs = "".join(f'<path class="g" style="--gi:{i}" d="{d}"/>' for i, d in enumerate(WM["g231"]))
    glyphs += "".join(f'<path class="g wm-inc" style="--gi:{i + 3}" pathLength="1" d="{d}"/>' for i, d in enumerate(WM["ginc"]))
    return (f'<svg class="{cls}" viewBox="{-pad} {-pad} {w + sh + 2 * pad} {h + 2 * pad}" {aria}>'
            f'<g transform="translate({sh} 0) skewX(-11)">{glyphs}</g></svg>')


def digits(phone):
    return re.sub(r"\D", "", phone)


CT = C["contacts"]
PHONE_D = digits(CT["phone"])
TG = f"https://t.me/+{PHONE_D}"
TG_RENT = f'https://t.me/{CT["telegram"].lstrip("@")}' if CT.get("telegram") else TG
WA = f"https://wa.me/{PHONE_D}"
MAP = "https://yandex.ru/maps/?text=" + urllib.parse.quote(CT["address"], safe="")
EXT = 'target="_blank" rel="noopener"'
INSTAGRAM = CT.get("instagram", "")
TG_CHANNEL = CT.get("telegramChannel", "")
HEART = ('<svg class="heart" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
         '<path d="M12 20.5 4.6 13.2a4.8 4.8 0 0 1 0-6.8 4.9 4.9 0 0 1 6.9 0l.5.5.5-.5a4.9 4.9 0 0 1 6.9 0 4.8 4.8 0 0 1 0 6.8Z"/></svg>')


def ext_btn(href, label, cls="btn btn-line", extra=""):
    return f'<a class="{cls}" href="{esc(href)}" {EXT}{extra}>{esc(label)} {ARROW_OUT}</a>'


def words(text, start=0, accent=False, fill=False):
    """Слова в масках: каждое выезжает снизу (анимация в CSS). Возвращает разметку и следующий номер слова."""
    out, i = [], start
    for wd in str(text).split():
        inner = f'<span class="accent-word{" fill" if fill else ""}">{esc(wd)}</span>' if accent else esc(wd)
        out.append(f'<span class="w"><span class="wi" style="--wi:{i}">{inner}</span></span>')
        i += 1
    return " ".join(out), i


def split_heading(text, accent="", fill=False):
    head, i = words(text)
    if accent:
        tail, _ = words(accent, i, accent=True, fill=fill)
        head = f"{head} {tail}" if head else tail
    return head


def roll(text):
    return f'<span class="roll"><span>{esc(text)}</span><span aria-hidden="true">{esc(text)}</span></span>'


def preview_base(p):
    """Картинка для превью за курсором: первая работа с главной (у видео — его обложка)."""
    refs = [r for r in (p.get("showcase") or featured_of(p)) if r in p["works"]] or p["works"]
    if not refs:
        return ""
    m = MEDIA[refs[0]]
    return MEDIA[m["poster"]]["base"] if m.get("type") == "video" else m["base"]


def heart_btn(ref, alt):
    return (f'<button class="ph-heart" type="button" data-ref="{esc(ref)}" aria-pressed="false" '
            f'aria-label="Сохранить в референсы: {esc(alt)}">{HEART}</button>')


def ambient(refs, k=0.8):
    """Тон «комнаты» для раздела: средний цвет его кадров, сильно затемнённый (фон меняется при прокрутке)."""
    cols = []
    for r in refs:
        m = MEDIA.get(r)
        if m and m.get("c"):
            c = m["c"]
            cols.append([int(c[i:i + 2], 16) for i in (1, 3, 5)])
    if not cols:
        return "#0b0c0f"
    avg = [sum(c[i] for c in cols) / len(cols) for i in range(3)]
    mid = sum(avg) / 3
    sat = [mid + (v - mid) * 1.7 for v in avg]
    base = (9, 10, 13)
    out = [max(0, min(255, round(base[i] * k + sat[i] * (1 - k)))) for i in range(3)]
    return "#%02x%02x%02x" % tuple(out)


def featured_of(p):
    f = [x for x in p.get("featured", []) if x in p["works"]]
    for x in p["works"]:
        if len(f) >= 3:
            break
        if x not in f:
            f.append(x)
    return f[:3]


def plural(n, one, few, many):
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def price_html(p, cls="price-line"):
    if not p.get("priceFrom"):
        return ""
    frm = '<small>от</small> ' if p.get("priceIsFrom") else ""
    return (f'<p class="{cls}"><span class="price-label">{esc(p.get("priceLabel") or "Цена")}</span>'
            f'<span class="price-val">{frm}<b>{esc(p["priceFrom"])}</b> <span>{esc(p.get("priceUnit") or "сомони")}</span></span></p>')


# мозаика: модули-развороты, кадры без обрезки
MOD_SLOTS = {"a": ["a1", "a2"], "b": ["b", "b", "b"], "c": ["c1", "c2"], "d": ["d"], "s": ["s"], "v": ["v"]}


def is_land(ref):
    m = MEDIA[ref] if ref.startswith("v:") else MEDIA[bare(ref)]
    return m.get("type") != "video" and m["w"] / m["h"] > 1.15


def is_video(ref):
    return ref.startswith("v:")


def figure(ref, slot, gallery, index, total, d=0, yt=None, caption=True):
    if is_video(ref):
        return video_card(ref, slot, d)
    m = MEDIA[ref]
    num = f'<figcaption class="ph-cap">{index + 1:02d} / {total:02d}</figcaption>' if caption else ""
    inner = f'<span class="ph-frame">{picture(ref, SIZES[slot])}</span>'
    if yt:
        link = (f'<a class="ph-link" href="{esc(yt)}" {EXT} data-cursor="YouTube">{inner}'
                f'<span class="yt-tag">▶ Смотреть на YouTube</span></a>')
    else:
        link = (f'<a class="ph-link" href="{m["base"]}-{m["jw"][-1]}.jpg" data-lb="{gallery}" data-i="{index}" '
                f'data-cursor="Смотреть">{inner}</a>')
    heart = "" if yt else heart_btn(ref, m["alt"])
    return (f'<figure class="ph ph-{slot}" data-rv style="--r:{m["w"] / m["h"]:.4f};--c:{m["c"]};--d:{d}">'
            f'{link}{heart}{num}</figure>')


def video_card(ref, slot="v", d=0):
    m = MEDIA[ref]
    pm = MEDIA[m["poster"]]
    dur = f'{m["sec"] // 60}:{m["sec"] % 60:02d} · ' if m.get("sec") else ""
    size = f'{m["mb"]:.1f}'.replace(".", ",")
    return (f'<figure class="ph ph-{slot} ph-video" data-rv style="--r:{pm["w"] / pm["h"]:.4f};--c:{pm["c"]};--d:{d}">'
            f'<span class="ph-frame">{picture(m["poster"], SIZES[slot], alt="")}'
            f'<a class="vplay" href="{m["src"]}" data-video="{esc(ref)}" data-cursor="Видео">'
            f'<span class="vplay-ico" aria-hidden="true"></span><span class="vplay-t">Смотреть видео</span>'
            f'<span class="vplay-m">{dur}{size} МБ</span><span class="sr">: {esc(m["alt"])}</span></a></span>'
            f'<figcaption class="ph-cap ph-cap-text">{esc(m["alt"])}</figcaption></figure>')


def mosaic(refs, gallery, all_refs=None, pattern=("a", "b", "c", "b"), yt=None, caption=True):
    all_refs = all_refs or refs
    total = len(all_refs)
    mods, i, p = [], 0, 0
    while i < len(refs):
        r = refs[i]
        if is_video(r):
            mods.append(("v", [r]))
            i += 1
            continue
        if is_land(r):
            mods.append(("d", [r]))
            i += 1
            continue
        kind = pattern[p % len(pattern)]
        need = len(MOD_SLOTS[kind])
        group = []
        while i + len(group) < len(refs) and len(group) < need:
            nxt = refs[i + len(group)]
            if is_video(nxt) or is_land(nxt):
                break
            group.append(nxt)
        if len(group) < need:
            kind = {1: "s", 2: "c" if kind == "c" else "a"}[len(group)]
        mods.append((kind, group))
        i += len(group)
        p += 1
    out = []
    for kind, group in mods:
        cells = "".join(figure(r, MOD_SLOTS[kind][j], gallery, all_refs.index(r), total, d=j,
                               yt=(yt or {}).get(r), caption=caption)
                        for j, r in enumerate(group))
        out.append(f'<div class="mod mod-{kind}">{cells}</div>')
    return f'<div class="mosaic">{"".join(out)}</div>'


# ---------------------------------------------------------------- разделы главной

TEAM = C["team"]
CP = C["copy"]
PRICES = parse_prices(C["pricesText"])
SMM_PLANS = parse_smm(C["smm"]["plansText"])
SMM_ALL = parse_all(C["smm"].get("allText", ""))
WORKS = C.get("works", [])
BACKSTAGE = C.get("backstage", [])
STUDIO = C["studio"]


def marquee_items():
    items = [s["title"] for s in C["services"]] + ["Аренда студии", "SMM"]
    return "".join(f'<span class="mq-item"><span class="mq-t">{esc(t)}</span>{mono_svg()}</span>' for t in items)


def hero():
    h = C["hero"]
    credit = next((p for p in TEAM if p["id"] == h.get("credit")), None)
    art = ("(max-width: 767px)", h["image"] + "-m", "100vw") if h.get("mobileCrop") else None
    reel = C.get("reel") or {}
    reel_btn = ext_btn(reel["youtube"], "Смотреть шоурил", "btn btn-line") if yt_ok(reel.get("youtube")) else ""
    m = MEDIA[h["image"]]
    in_gallery = credit and h["image"] in credit["works"]
    open_attrs = (f' href="{m["base"]}-{m["jw"][-1]}.jpg" data-lb="{credit["id"]}" data-i="{credit["works"].index(h["image"])}" data-cursor="Смотреть"'
                  if in_gallery else "")
    tag = "a" if in_gallery else "span"
    cap = (f'<figcaption class="hero-cap">Фото: <a href="#p-{credit["id"]}">{esc(credit["name"])}</a></figcaption>'
           if credit else "")
    hud = ('<span class="hud" aria-hidden="true"><span class="hud-c tl"></span><span class="hud-c tr"></span>'
           '<span class="hud-c bl"></span><span class="hud-c br"></span>'
           '<span class="hud-t tl"><i class="rec"></i>REC</span><span class="hud-t tr" data-tc>00:00:00:00</span>'
           '<span class="hud-t bl">231INC · Сцена 1 · Дубль 1</span><span class="hud-t br">2 : 3</span></span>')
    return f'''
<section class="hero" aria-labelledby="hero-title" data-ambient="#0b0c0f" data-hero>
  <div class="wrap hero-grid">
    <div class="hero-copy">
      <div class="hero-top">
        <p class="kicker hero-in" style="--i:0"><span class="rec" aria-hidden="true"></span>{esc(h["kicker"])}</p>
        <h1 id="hero-title" class="h-hero">{split_heading(h["title"], h["titleAccent"])}</h1>
      </div>
      <div class="hero-foot">
        <p class="lead hero-in" style="--i:2">{esc(h["lead"])}</p>
        <div class="actions hero-in" style="--i:3">
          {ext_btn(TG, "Записаться в Telegram", "btn btn-accent", " data-magnet")}
          <a class="btn btn-line" href="#works">Смотреть работы {ARROW_R}</a>
          {reel_btn}
        </div>
        <a class="scroll-cue hero-in" style="--i:4" href="#works" tabindex="-1" aria-hidden="true"><i></i>Листайте</a>
      </div>
    </div>
    <figure class="hero-media">
      <{tag} class="hero-frame"{open_attrs} style="--c:{m["c"]}">{picture(h["image"], SIZES["hero"], eager=True, art=art)}<span class="vignette" aria-hidden="true"></span>{hud}<span class="shutter" aria-hidden="true"><span></span><span></span></span></{tag}>
      {cap}
    </figure>
  </div>
</section>
<div class="marquee" aria-hidden="true"><div class="marquee-track" data-marquee>{marquee_items() * 2}</div></div>'''


def strip_section():
    refs = [r for r in C.get("selected", []) if r in MEDIA]
    if not refs:
        return ""
    owner = {r: p for p in TEAM for r in p["works"]}
    frames = []
    for i, r in enumerate(refs):
        m = MEDIA[r]
        who = owner.get(r)
        frames.append(
            f'<figure class="f35" style="--r:{m["w"] / m["h"]:.4f};--c:{m["c"]}">'
            f'<a class="f35-link" href="{m["base"]}-{m["jw"][-1]}.jpg" data-lb="selected" data-i="{i}" data-cursor="Смотреть">'
            f'<span class="f35-img">{picture(r, SIZES["f35"])}</span></a>{heart_btn(r, m["alt"])}'
            f'<figcaption><span class="f35-code">231 ▸ {i + 1:02d}A</span><span>{esc(who["name"]) if who else ""}</span></figcaption></figure>')
    n = len(refs)
    return f'''
<section class="strip" id="selected" aria-labelledby="strip-title" data-strip data-ambient="#08080a">
  <div class="strip-pin">
    <header class="wrap sec-head sec-head-row strip-head">
      <div><p class="kicker" data-rv>Лента · {n} {plural(n, "кадр", "кадра", "кадров")}</p>
      <h2 id="strip-title" class="h2 split" data-rv>{split_heading(CP["selectedTitle"])}</h2></div>
      <p class="sec-lead" data-rv>{esc(CP["selectedLead"])}</p>
    </header>
    <div class="strip-film">
      <div class="strip-track" data-strip-track tabindex="0" role="region" aria-label="Лента избранных кадров">{"".join(frames)}</div>
    </div>
    <div class="wrap strip-foot" aria-hidden="true"><span class="strip-bar"><i data-strip-bar></i></span><span class="strip-hint">Листайте</span></div>
  </div>
</section>'''


def trail_section():
    refs = [r for r in C.get("trail", []) if r in MEDIA]
    if not refs:
        return ""
    total = sum(len(p["works"]) for p in TEAM)
    return f'''
<section class="trail" aria-labelledby="trail-title" data-trail data-ambient="#0b0c0f">
  <div class="wrap trail-in">
    <p class="kicker" data-rv>{total} {plural(total, "работа", "работы", "работ")} · {len(TEAM)} {plural(len(TEAM), "автор", "автора", "авторов")}</p>
    <h2 id="trail-title" class="trail-title split" data-rv>{split_heading(CP["trailTitle"], CP["trailAccent"])}</h2>
    <p class="trail-hint" data-rv><span class="hint-mouse">Проведите курсором по экрану</span><span class="hint-touch">Проведите пальцем в сторону</span></p>
  </div>
  <div class="trail-layer" aria-hidden="true"></div>
</section>'''


def author_spread(p, n, total):
    refs = [r for r in (p.get("showcase") or featured_of(p)) if r in p["works"]]
    count = len(p["works"])
    portrait = (f'<a class="author-portrait" href="#p-{p["id"]}" tabindex="-1" aria-hidden="true">'
                f'<span class="frame">{picture(p["photo"], SIZES["portrait"], alt="", pos=p.get("photoPosition"))}</span></a>'
                if p.get("photo") else "")
    works_word = plural(count, "работа", "работы", "работ")
    return f'''
    <article class="author" id="author-{p["id"]}" aria-labelledby="a-{p["id"]}" data-ambient="{ambient(refs)}">
      <div class="author-side" data-rv>
        {portrait}
        <p class="idx">{n + 1:02d} <span>/ {total:02d}</span></p>
        <p class="role">{esc(p["role"])}</p>
        <h3 id="a-{p["id"]}" class="author-name"><a href="#p-{p["id"]}">{esc(p["name"])}</a></h3>
        <p class="bio">{esc(p["bio"])}</p>
        {price_html(p)}
        <div class="actions">
          <a class="btn btn-ink" href="#p-{p["id"]}">Портфолио · {count} {works_word} {ARROW_R}</a>
          {ext_btn(TG, "Записаться в Telegram", "btn btn-line")}
        </div>
      </div>
      <div class="author-works">{mosaic(refs, p["id"], all_refs=p["works"], pattern=("a", "c"), yt=p.get("yt"), caption=False)}</div>
    </article>'''


def works_section():
    total_works = sum(len(p["works"]) for p in TEAM)
    rows = []
    for i, p in enumerate(TEAM):
        count = len(p["works"])
        rows.append(f'<li><a class="aidx-row" href="#p-{p["id"]}" data-pv="{preview_base(p)}" data-rv style="--d:{i}">'
                    f'<span class="aidx-n">{i + 1:02d}</span><span class="aidx-name">{esc(p["name"])}</span>'
                    f'<span class="aidx-role">{esc(p["role"])}</span>'
                    f'<span class="aidx-count"><span>{count} {plural(count, "работа", "работы", "работ")}</span>'
                    f'<span class="arr" aria-hidden="true">→</span></span></a></li>')
    authors = "".join(author_spread(p, i, len(TEAM)) for i, p in enumerate(TEAM))
    return f'''
<section class="sec works" id="works" aria-labelledby="works-title">
  <span class="anchor" id="photo"></span><span class="anchor" id="team"></span>{"" if BACKSTAGE else '<span class="anchor" id="backstage"></span>'}
  <div class="wrap">
    <header class="sec-head sec-head-row">
      <div><p class="kicker" data-rv>Портфолио · {len(TEAM)} {plural(len(TEAM), "автор", "автора", "авторов")} · {total_works} {plural(total_works, "работа", "работы", "работ")}</p>
      <h2 id="works-title" class="h2 split" data-rv>{split_heading(CP["worksTitle"])}</h2></div>
      <p class="sec-lead" data-rv>{esc(CP["worksLead"])}</p>
    </header>
    <ul class="aidx" aria-label="Авторы">{"".join(rows)}</ul>
    {authors}
  </div>
</section>'''


def cases_section():
    if not WORKS:
        return ""
    cats = ["Все"] + sorted({w["cat"] for w in WORKS if w.get("cat")}, key=lambda c: [w.get("cat") for w in WORKS].index(c))
    chips = "".join(f'<button type="button" aria-pressed="{"true" if c == "Все" else "false"}" data-v="{esc(c)}">{esc(c)}</button>' for c in cats)
    cards = []
    for i, w in enumerate(WORKS):
        poster = w.get("poster")
        media = (f'<span class="ph-frame">{picture(poster, SIZES["b"])}</span>' if poster and poster in MEDIA
                 else '<span class="ph-frame case-blank" aria-hidden="true"></span>')
        meta = " · ".join(x for x in (w.get("cat"), w.get("year")) if x)
        cards.append(f'''<article class="case" data-cat="{esc(w.get("cat", ""))}" data-rv style="--d:{i % 3}">
          <a class="case-link" href="#case-{esc(w["id"])}">{media}
            <span class="case-meta">{esc(meta)}</span>
            <span class="case-title">{esc(w.get("title"))}</span>
            <span class="case-client">{esc(w.get("client"))}</span></a>
          {ext_btn(w["youtube"], "YouTube", "pill") if yt_ok(w.get("youtube")) else ""}
        </article>''')
    return f'''
<section class="sec cases" id="cases" aria-labelledby="cases-title">
  <div class="wrap">
    <header class="sec-head sec-head-row" data-rv>
      <div><h2 id="cases-title" class="h2">{esc(CP["casesTitle"])}</h2><p class="sec-lead">{esc(CP["casesLead"])}</p></div>
      <div class="chips" role="group" aria-label="Фильтр проектов">{chips}</div>
    </header>
    <div class="case-grid">{"".join(cards)}</div>
  </div>
</section>'''


def case_templates():
    out = []
    for w in WORKS:
        paras = "".join(f"<p>{esc(t)}</p>" for t in re.split(r"\n\s*\n", w.get("text") or "") if t.strip())
        credits = "".join(f"<div><dt>{esc(r)}</dt><dd>{esc(n)}</dd></div>" for r, n in w.get("credits", []))
        vm = MEDIA.get("v:" + bare(w["video"])) if w.get("video") else None
        if vm:
            pm = MEDIA[vm["poster"]]
            media = f'<video controls playsinline preload="none" src="{vm["src"]}" poster="{pm["base"]}-{pm["jw"][0]}.jpg"></video>'

        elif w.get("poster") and w["poster"] in MEDIA:
            media = picture(w["poster"], "(min-width: 1100px) 1000px, 100vw")
        else:
            media = ""
        yt = ext_btn(w["youtube"], "Смотреть на YouTube", "btn btn-accent") if yt_ok(w.get("youtube")) else ""
        bts = "".join(figure(r, "b", f'case-{w["id"]}', i, len(w.get("bts", [])), caption=False) for i, r in enumerate(w.get("bts", [])) if r in MEDIA)
        meta = " · ".join(x for x in (w.get("cat"), w.get("client"), w.get("year")) if x)
        out.append(f'''<template id="tpl-case-{esc(w["id"])}">
  <p class="kicker">{esc(meta)}</p>
  <h2 class="case-h" id="case-title">{esc(w.get("title"))}</h2>
  {f'<div class="case-media">{media}</div>' if media else ""}
  {yt}
  <div class="case-body"><div class="case-text">{paras}</div>{f'<dl class="credits">{credits}</dl>' if credits else ""}</div>
  {f'<div class="case-bts"><p class="kicker">Бэкстейдж проекта</p><div class="bts-grid">{bts}</div></div>' if bts else ""}
</template>''')
    return "".join(out)


def services_section():
    items = "".join(
        f'<li data-rv style="--d:{i}"><span class="svc-n">{i + 1:02d}</span><span class="svc-label">{esc(s["label"])}</span>'
        f'<h3 class="svc-title">{esc(s["title"])}</h3><p>{esc(s["text"])}</p></li>'
        for i, s in enumerate(C["services"]))
    first = PRICES["plans"][0] if PRICES["plans"] else None
    n = len(PRICES["plans"])
    sub = (f'{n} {plural(n, "пакет", "пакета", "пакетов")}: от {esc(first["amount"])} {esc(first["cur"])}'
           if first else "Пакеты и стоимость")
    return f'''
<section class="sec services paper sheet" id="services" aria-labelledby="services-title">
  <div class="wrap">
    <header class="sec-head sec-head-row">
      <h2 id="services-title" class="h2 split" data-rv>{split_heading(CP["servicesTitle"])}</h2>
      <p class="sec-lead" data-rv>{esc(CP["teamLead"])}</p>
    </header>
    <ol class="svc-list">{items}</ol>
    {teaser("#prices", "Видеопроизводство", "Цены", sub, "price-teaser")}
  </div>
</section>'''


def teaser(href, kicker, title, sub, id_=None):
    idattr = f' id="{id_}"' if id_ else ""
    return (f'<a class="teaser"{idattr} href="{href}" data-rv><span class="teaser-txt"><span class="kicker">{esc(kicker)}</span>'
            f'<span class="teaser-title">{esc(title)}</span><span class="teaser-sub">{sub}</span></span>'
            f'<span class="teaser-go" aria-hidden="true" data-magnet>→</span></a>')


def smm_section():
    s = C["smm"]
    cards = []
    for i, c in enumerate(s["clients"]):
        logo = (f'<span class="client-logo{" full" if c.get("logoFull") else ""}">{picture(c["logo"], SIZES["logo"], alt=c["name"])}</span>'
                if c.get("logo") else f'<span class="client-logo"><span class="client-wm">{esc(c["name"])}</span></span>')
        body = (f'{logo}<span class="client-name">{esc(c["name"])}</span><span class="client-desc">{esc(c["desc"])}</span>'
                + (f'<span class="client-ig">{esc(ig_name(c["link"]))} <span aria-hidden="true">↗</span></span>' if c.get("link") else ""))
        inner = f'<a class="client-card" href="{esc(c["link"])}" {EXT}>{body}</a>' if c.get("link") else f'<div class="client-card">{body}</div>'
        cards.append(f'<li class="client" data-rv style="--d:{i}">{inner}</li>')
    first = SMM_PLANS[0] if SMM_PLANS else None
    n = len(SMM_PLANS)
    sub = (f'{n} {plural(n, "тариф", "тарифа", "тарифов")}: от {esc(first["amount"])} {esc(first["cur"])}' if first else "Тарифы")
    return f'''
<section class="sec smm paper" id="smm-clients" aria-labelledby="smm-title">
  <div class="wrap">
    <header class="sec-head sec-head-row">
      <div><p class="kicker" data-rv>Наши проекты</p><h2 id="smm-title" class="h2 split" data-rv>{split_heading(s["title"] or "SMM")}</h2></div>
      <p class="sec-lead" data-rv>{esc(s["text"])}</p>
    </header>
    <ul class="clients">{"".join(cards)}</ul>
    {teaser("#smm", "SMM-сопровождение", "Цены на SMM", sub)}
  </div>
</section>'''


def rates_inline():
    st = STUDIO
    parts = []
    if st.get("rate1"):
        parts.append(f'<span><b>{esc(st["rate1"])}</b> сомони / час</span>')
    if st.get("rate2"):
        parts.append(f'<span>{esc(st.get("rate2Label") or "От 2 часов")}: <b>{esc(st["rate2"])}</b> сомони / час</span>')
    return f'<p class="rates-inline">{"".join(parts)}</p>' if parts else ""


def rent_teaser():
    st = STUDIO
    picks = [r for r in (st.get("teaser") or st.get("photos", [])[:2]) if r in MEDIA][:2]
    imgs = "".join(
        f'<a class="rt-ph rt-ph-{i + 1}" href="#rent" style="--r:{MEDIA[r]["w"] / MEDIA[r]["h"]:.4f};--c:{MEDIA[r]["c"]};--d:{i}" '
        f'data-rv data-cursor="Студия" tabindex="-1" aria-hidden="true">'
        f'<span class="ph-frame">{picture(r, SIZES["teaser"], alt="")}</span></a>'
        for i, r in enumerate(picks))
    return f'''
<section class="sec rent-teaser sheet" id="rent-teaser" aria-labelledby="rt-title" data-ambient="{ambient(st.get("photos", []), 0.74)}" style="--amb:{ambient(st.get("photos", []), 0.74)}">
  <div class="wrap rt-grid">
    <div class="rt-copy">
      <p class="kicker" data-rv>Аренда · ул. Айни, 46</p>
      <h2 id="rt-title" class="h2 split" data-rv>{split_heading(st["title"])}</h2>
      <p class="sec-lead" data-rv>{esc(st["text"])}</p>
      <div data-rv>{rates_inline()}</div>
      <div class="actions" data-rv>
        <a class="btn btn-accent" href="#rent" data-magnet>Смотреть студию {ARROW_R}</a>
        {ext_btn(TG_RENT, "Написать в Telegram", "btn btn-line")}
      </div>
    </div>
    <div class="rt-media">{imgs}</div>
  </div>
</section>'''


def backstage_section():
    if not BACKSTAGE:
        return ""
    refs = [b["ref"] for b in BACKSTAGE]
    first = refs[:8]
    more = f'<a class="btn btn-line" href="#bts">Весь бэкстейдж · {len(refs)} {ARROW_R}</a>' if len(refs) > 8 else ""
    return f'''
<section class="sec backstage" id="backstage" aria-labelledby="bs-title">
  <div class="wrap">
    <header class="sec-head sec-head-row" data-rv><h2 id="bs-title" class="h2">{esc(CP["backstageTitle"])}</h2><p class="sec-lead">{esc(CP["backstageLead"])}</p></header>
    {mosaic(first, "bts", all_refs=refs, pattern=("b",))}
    {more}
  </div>
</section>'''


def contact_rows(phone_id="v-phone", mail_id="v-mail", tg=TG, compact=False):
    rows = [f'''<div class="crow" data-rv>
        <p class="label">Телефон · Telegram · WhatsApp</p>
        <p class="val" id="{phone_id}">{esc(CT["phone"])}</p>
        <div class="acts">
          <a class="pill pill-accent" href="{esc(tg)}" {EXT}>Telegram <span aria-hidden="true">↗</span></a>
          <a class="pill" href="{esc(WA)}" {EXT}>WhatsApp <span aria-hidden="true">↗</span></a>
          <a class="pill" href="tel:+{PHONE_D}">Позвонить</a>
          <button class="pill" type="button" data-copy="{phone_id}">Скопировать</button>
        </div>
      </div>''']
    if not compact and CT.get("email"):
        rows.append(f'''<div class="crow" data-rv style="--d:1">
        <p class="label">Почта</p>
        <p class="val" id="{mail_id}">{esc(CT["email"])}</p>
        <div class="acts">
          <a class="pill" href="mailto:{esc(CT["email"])}">Написать</a>
          <button class="pill" type="button" data-copy="{mail_id}">Скопировать</button>
        </div>
      </div>''')
    socials = []
    if INSTAGRAM:
        socials.append(f'<a class="pill" href="{esc(INSTAGRAM)}" {EXT}>Instagram @231inc <span aria-hidden="true">↗</span></a>')
    if TG_CHANNEL:
        socials.append(f'<a class="pill" href="{esc(TG_CHANNEL)}" {EXT}>Telegram-канал <span aria-hidden="true">↗</span></a>')
    if socials and not compact:
        rows.append(f'<div class="crow" data-rv style="--d:1"><p class="label">Соцсети</p><p class="val">@231inc</p><div class="acts">{"".join(socials)}</div></div>')
    rows.append(f'''<div class="crow" data-rv style="--d:2">
        <p class="label">Студия</p>
        <p class="val">{esc(CT["address"])}</p>
        <div class="acts"><a class="pill" href="{esc(MAP)}" {EXT}>На карте <span aria-hidden="true">↗</span></a></div>
      </div>''')
    return "".join(rows)


def contact_section():
    return f'''
<section class="sec contact" id="contact" aria-labelledby="contact-title">
  <div class="wrap contact-grid">
    <div class="contact-lead">
      <h2 id="contact-title" class="h-contact split" data-rv>{split_heading(CP["contactTitle"], CP["contactAccent"], fill=True)}</h2>
      <div class="actions contact-cta" data-rv>
        <a class="btn btn-accent" href="#contact" data-req data-magnet>Собрать заявку {ARROW_R}</a>
        <p class="contact-cta-note">Услуга, автор, дата и понравившиеся кадры — в одно сообщение для WhatsApp или Telegram.</p>
      </div>
    </div>
    <div class="contact-rows">{contact_rows()}</div>
  </div>
</section>'''


# ---------------------------------------------------------------- отдельные страницы

def back(href, label="Назад"):
    return f'<a class="back" href="{href}" data-back><span aria-hidden="true">←</span> {label}</a>'


def page_head(kicker, title, lead, id_):
    return (f'<header class="page-head"><p class="kicker">{esc(kicker)}</p>'
            f'<h1 id="{id_}" class="h-page" tabindex="-1">{esc(title)}</h1>'
            + (f'<p class="page-lead">{esc(lead)}</p>' if lead else "") + "</header>")


def prices_view():
    plans = []
    for i, p in enumerate(PRICES["plans"]):
        items = "".join(f"<li>{esc(it)}</li>" for it in p["items"])
        frm = "<small>от</small> " if p["from"] else ""
        plans.append(f'''<li class="plan" data-rv>
        <p class="plan-n" aria-hidden="true">{i + 1:02d}</p>
        <div class="plan-main"><h2 class="plan-title">{esc(p["title"])}</h2><ul class="plan-items">{items}</ul></div>
        <div class="plan-side">
          <p class="plan-price">{frm}<b>{esc(p["amount"])}</b> <span>{esc(p["cur"])}</span></p>
          {ext_btn(TG, "Обсудить в Telegram", "btn btn-line")}
        </div>
      </li>''')
    note = f'<p class="note" data-rv><b>Примечание.</b> {esc(PRICES["note"])}</p>' if PRICES["note"] else ""
    return f'''
<div class="view paper" id="prices" aria-labelledby="prices-title">
  <section class="page"><div class="wrap">
    {back("#works")}
    {page_head(CP["pricesKicker"], "Цены", CP["pricesLead"], "prices-title")}
    <ol class="plans">{"".join(plans)}</ol>
    {note}
    <nav class="next-links" aria-label="Другие цены">
      {teaser("#smm", "SMM-сопровождение", "Цены на SMM", "Тарифы на ведение соцсетей")}
      {teaser("#rent", "Аренда", esc(STUDIO["title"]), f'{esc(STUDIO.get("rate1", ""))} сомони / час' if STUDIO.get("rate1") else "")}
    </nav>
  </div></section>
</div>'''


def smm_view():
    s = C["smm"]
    cards = []
    for i, p in enumerate(SMM_PLANS):
        items = "".join(("<li>" + (f"<b>{esc(it['b'])}</b> " if it["b"] else "") + f"<span>{esc(it['t'])}</span></li>")
                        for it in p["items"])
        hot = " plan-hot" if i == 1 and len(SMM_PLANS) > 2 else ""
        cards.append(f'''<article class="tariff{hot}" data-rv style="--d:{i}">
        <header class="tariff-head"><p class="plan-n" aria-hidden="true">{i + 1:02d}</p><h2 class="tariff-title">{esc(p["title"])}</h2>
          <p class="plan-price"><b>{esc(p["amount"])}</b> <span>{esc(p["cur"])}</span></p></header>
        {f'<p class="tariff-desc">{esc(p["desc"])}</p>' if p["desc"] else ""}
        <p class="kicker">В пакет входит</p>
        <ul class="tariff-items">{items}</ul>
        {f'<p class="tariff-res"><b>Результат</b>{esc(p["result"])}</p>' if p["result"] else ""}
        {ext_btn(TG, "Обсудить в Telegram", "btn btn-accent" if hot else "btn btn-line")}
      </article>''')
    allin = ""
    if SMM_ALL:
        allin = (f'<section class="allin-wrap" aria-labelledby="allin-title"><h2 id="allin-title" class="h3" data-rv>Что входит во все тарифы</h2><ol class="allin">'
                 + "".join(f'<li data-rv style="--d:{i}"><span class="allin-n">{esc(a["n"])}</span><h3>{esc(a["title"])}</h3>'
                           + (f'<p>{esc(a["text"])}</p>' if a["text"] else "") + "</li>" for i, a in enumerate(SMM_ALL))
                 + "</ol></section>")
    return f'''
<div class="view paper" id="smm" aria-labelledby="smm-page-title">
  <section class="page"><div class="wrap">
    {back("#smm-clients")}
    {page_head(CP["smmKicker"], "Цены на SMM", s.get("intro", ""), "smm-page-title")}
    <div class="tariffs">{"".join(cards)}</div>
    {allin}
  </div></section>
</div>'''


def calc_html():
    st = STUDIO
    r1 = int(re.sub(r"\D", "", st.get("rate1") or "0") or 0)
    r2 = int(re.sub(r"\D", "", st.get("rate2") or "0") or 0)
    if not r1:
        return ""
    r2_from = int((re.search(r"\d+", st.get("rate2Label") or "") or re.search(r"2", "2")).group())
    return f'''<div class="calc" data-calc data-r1="{r1}" data-r2="{r2}" data-r2from="{r2_from}" hidden>
          <p class="kicker">Посчитать аренду</p>
          <div class="calc-row">
            <button class="calc-btn" type="button" data-step="-1" aria-label="Меньше часов">−</button>
            <p class="calc-h"><output data-hours>2</output> <span data-hours-word>часа</span></p>
            <button class="calc-btn" type="button" data-step="1" aria-label="Больше часов">+</button>
          </div>
          <input class="calc-range" type="range" min="1" max="12" step="1" value="2" aria-label="Часов аренды" data-range>
          <label class="field"><span class="kicker">Дата, если знаете</span><input type="date" data-calc-date></label>
          <p class="calc-total"><b data-total>{2 * (r2 or r1)}</b> сомони <span data-rate></span></p>
          <a class="btn btn-accent" data-calc-wa href="{esc(WA)}" {EXT}>Забронировать в WhatsApp {ARROW_OUT}</a>
          <p class="calc-note">Расчёт по ставкам с сайта. Свободное время и итог подтверждает студия.</p>
        </div>'''


def rent_view():
    st = STUDIO
    feats = "".join(f"<li>{esc(f)}</li>" for f in st.get("features", []))
    rates = []
    if st.get("rate1"):
        rates.append(f'<div class="rate"><span class="kicker">1 час</span><b>{esc(st["rate1"])}</b><em>сомони / час</em></div>')
    if st.get("rate2"):
        rates.append(f'<div class="rate rate-best"><span class="kicker">{esc(st.get("rate2Label") or "От 2 часов")}</span><b>{esc(st["rate2"])}</b><em>сомони / час</em></div>')
    facts = ""
    if st.get("price"):
        facts += f'<div><dt>Стоимость</dt><dd>{esc(st["price"])}</dd></div>'
    if st.get("hours"):
        facts += f'<div><dt>Время работы</dt><dd>{esc(st["hours"])}</dd></div>'
    facts += f'<div><dt>Телефон</dt><dd id="v-phone2">{esc(CT["phone"])}</dd></div><div><dt>Адрес</dt><dd>{esc(CT["address"])}</dd></div>'
    photos = [r for r in st.get("photos", []) if r in MEDIA]
    gallery = (mosaic(photos, "studio", pattern=("a", "b", "c"), caption=False) if photos else
               '<p class="empty">Напишите нам в Telegram, пришлём фото и видео студии.</p>')
    zones = ""
    if st.get("zones"):
        zl = []
        for z in st["zones"]:
            zp = [r for r in z.get("photos", []) if r in MEDIA]
            cover = (f'<a class="ph-link" href="{MEDIA[zp[0]]["base"]}-{MEDIA[zp[0]]["jw"][-1]}.jpg" data-lb="zone-{esc(z["id"])}" data-i="0">'
                     f'<span class="ph-frame">{picture(zp[0], SIZES["b"])}</span></a>') if zp else ""
            zl.append(f'<li class="zone" data-rv style="--r:.8">{cover}<h3>{esc(z.get("name"))}</h3><p>{esc(z.get("text"))}</p></li>')
        zones = f'<section class="zones-wrap"><h2 class="h3">Фотозоны</h2><ul class="zones">{"".join(zl)}</ul></section>'
    return f'''
<div class="view" id="rent" aria-labelledby="rent-title">
  <section class="page rent-hero" data-ambient="{ambient(st.get("photos", []), 0.74)}"><div class="wrap">
    {back("#rent-teaser")}
    <div class="rent-grid">
      <div class="rent-copy">
        <p class="kicker">Фотостудия · {esc(CT["city"])}</p>
        <h1 id="rent-title" class="h-page" tabindex="-1">{esc(st["title"])}</h1>
        <p class="page-lead">{esc(st["text"])}</p>
        {f'<ul class="feat">{feats}</ul>' if feats else ""}
      </div>
      <aside class="book" aria-label="Запись на съёмку">
        <p class="kicker">Запись на съёмку</p>
        {f'<div class="rates">{"".join(rates)}</div>' if rates else ""}
        {calc_html()}
        <p class="book-cta">{esc(st["cta"])}</p>
        <dl class="facts">{facts}</dl>
        <div class="actions">
          {ext_btn(TG_RENT, "Написать в Telegram", "btn btn-accent")}
          {ext_btn(WA, "WhatsApp", "btn btn-line")}
          <button class="btn btn-line" type="button" data-copy="v-phone2">Скопировать номер</button>
        </div>
      </aside>
    </div>
  </div></section>
  <section class="rent-gallery" aria-labelledby="studio-title"><div class="wrap">
    <header class="sec-head sec-head-row" data-rv><h2 id="studio-title" class="h2">{esc(CP["studioGalleryTitle"])}</h2><p class="sec-lead">{esc(CP["studioGalleryLead"])}</p></header>
    {gallery}
    {zones}
  </div></section>
  <section class="contact rent-contact" id="rent-contact" aria-labelledby="rc-title"><div class="wrap contact-grid">
    <h2 id="rc-title" class="h-contact h-contact-sm split" data-rv>{split_heading("Для записи пишите в", "Telegram", fill=True)}</h2>
    <div class="contact-rows">{contact_rows("v-phone3", tg=TG_RENT, compact=True)}</div>
  </div></section>
</div>'''


def person_view(p, i):
    others = [q for q in TEAM if q["id"] != p["id"]]
    count = len(p["works"])
    portrait = (f'<figure class="person-portrait"><span class="frame">{picture(p["photo"], SIZES["portrait-lg"], alt=p["name"], pos=p.get("photoPosition"))}</span></figure>'
                if p.get("photo") else "")
    works = (mosaic(p["works"], p["id"], pattern=("a", "b", "c", "b"), yt=p.get("yt")) if p["works"] else
             '<p class="empty"><b>Работы скоро здесь</b>Мы готовим портфолио.</p>')
    nxt = "".join(f'<a class="other" href="#p-{q["id"]}" data-pv="{preview_base(q)}"><span class="role">{esc(q["role"])}</span>'
                  f'<span class="other-name">{esc(q["name"])}</span>{ARROW_R}</a>' for q in others)
    return f'''
<div class="view" id="p-{p["id"]}" aria-labelledby="pt-{p["id"]}">
  <section class="page"><div class="wrap">
    {back("#works")}
    <div class="person" data-ambient="{ambient(p["works"])}">
      <div class="person-side">
        {portrait}
        <p class="kicker">Портфолио · {count} {plural(count, "работа", "работы", "работ")}</p>
        <p class="role">{esc(p["role"])}</p>
        <h1 id="pt-{p["id"]}" class="h-person" tabindex="-1">{esc(p["name"])}</h1>
        <p class="page-lead">{esc(p["bio"])}</p>
        {price_html(p, "price-line price-lg")}
        <div class="actions">{ext_btn(TG, "Записаться в Telegram", "btn btn-accent", " data-magnet")}</div>
      </div>
      <div class="person-works">{works}</div>
    </div>
    <nav class="others" aria-label="Другие авторы"><p class="kicker">Другие авторы</p>{nxt}</nav>
  </div></section>
</div>'''


def bts_view():
    if not BACKSTAGE:
        return ""
    refs = [b["ref"] for b in BACKSTAGE]
    return f'''
<div class="view" id="bts" aria-labelledby="bts-title">
  <section class="page"><div class="wrap">
    {back("#backstage")}
    {page_head(f"Контактный лист · {len(refs)} кадров", CP["backstageTitle"], CP["backstageLead"], "bts-title")}
    {mosaic(refs, "bts", pattern=("b",))}
  </div></section>
</div>'''


# ---------------------------------------------------------------- общие части

NAV = [("#works", "Работы", ("main", "p-")), ("#prices", "Цены", ("prices",)), ("#smm-clients", "SMM", ("smm",)),
       ("#rent", "Аренда студии", ("rent",)), ("#contact", "Контакты", ())]


def header():
    links = "".join(f'<li><a href="{h}" data-nav="{"|".join(v)}">{roll(t)}</a></li>' for h, t, v in NAV)
    return f'''
<header class="hdr" id="hdr">
  <div class="wrap hdr-in">
    <a class="brand" href="#top" aria-label="231inc — на главную">{mono_svg()}{wordmark_svg("wm")}</a>
    <span class="hdr-clock" aria-hidden="true">Душанбе <b data-clock>··:··</b></span>
    <nav class="nav" aria-label="Разделы"><ul>{links}</ul></nav>
    <a class="btn btn-ink btn-sm hdr-cta" href="#contact" data-req>{roll("Обсудить проект")}</a>
    <a class="menu-btn" href="#site-nav" aria-haspopup="dialog" aria-controls="menu"><span class="menu-ico" aria-hidden="true"></span><span>Меню</span></a>
  </div>
</header>'''


def menu_dialog():
    links = "".join(f'<li><a href="{h}">{t}</a></li>' for h, t, _ in NAV)
    return f'''
<dialog class="menu" id="menu" aria-label="Меню">
  <div class="menu-in">
    <div class="menu-top wrap">
      <a class="brand" href="#top" aria-label="231inc — на главную">{mono_svg()}{wordmark_svg("wm")}</a>
      <button class="menu-close" type="button" data-close>Закрыть</button>
    </div>
    <nav class="wrap menu-nav" aria-label="Разделы"><ul>{links}</ul></nav>
    <div class="wrap menu-foot">
      <p class="kicker">{esc(CT["phone"])}</p>
      <div class="acts">
        <a class="pill pill-accent" href="{esc(TG)}" {EXT}>Telegram <span aria-hidden="true">↗</span></a>
        <a class="pill" href="{esc(WA)}" {EXT}>WhatsApp <span aria-hidden="true">↗</span></a>
        <a class="pill" href="tel:+{PHONE_D}">Позвонить</a>
        {f'<a class="pill" href="{esc(INSTAGRAM)}" {EXT}>Instagram <span aria-hidden="true">↗</span></a>' if INSTAGRAM else ""}
      </div>
      <a class="btn btn-accent menu-req" href="#contact" data-req>Собрать заявку {ARROW_R}</a>
    </div>
  </div>
</dialog>'''


def footer():
    links = "".join(f'<li><a href="{h}">{t}</a></li>' for h, t, _ in NAV)
    year = date.today().year
    return f'''
<footer class="ftr night">
  <div class="wrap">
    <div class="ftr-top">
      <nav id="site-nav" class="ftr-nav" aria-label="Разделы сайта"><ul>{links}</ul></nav>
      <div class="ftr-contacts">
        <a href="{esc(TG)}" {EXT}>Telegram ↗</a><a href="{esc(WA)}" {EXT}>WhatsApp ↗</a>
        {f'<a href="{esc(INSTAGRAM)}" {EXT}>Instagram @231inc ↗</a>' if INSTAGRAM else ""}
        {f'<a href="{esc(TG_CHANNEL)}" {EXT}>Telegram-канал ↗</a>' if TG_CHANNEL else ""}
        <a href="mailto:{esc(CT["email"])}">{esc(CT["email"])}</a><span>{esc(CT["address"])}</span>
      </div>
    </div>
    <a class="ftr-mark" href="#top" aria-label="231inc — наверх" data-rv>{wordmark_svg("wm-xl", slanted=True)}</a>
    <div class="ftr-meta"><span>© {year} 231INC · {esc(CT["city"])} <span class="ftr-clock" aria-hidden="true">· <b data-clock>··:··</b></span></span><span>{esc(C["site"]["footerNote"])}</span></div>
  </div>
</footer>'''


def lightbox():
    return f'''
<dialog class="lb" id="lb" aria-label="Просмотр">
  <div class="lb-top">
    <p class="lb-cap" id="lb-cap" aria-live="polite"></p>
    <button class="lb-heart" type="button" data-lb-heart aria-pressed="false">{HEART}<span data-lb-heart-t>В референсы</span></button>
    <button class="lb-close" type="button" data-close aria-label="Закрыть">Закрыть <span aria-hidden="true">×</span></button>
  </div>
  <div class="lb-stage" id="lb-stage"></div>
  <div class="lb-bar">
    <button class="lb-nav lb-prev" type="button" aria-label="Предыдущий кадр"><span aria-hidden="true">←</span></button>
    <button class="lb-nav lb-next" type="button" aria-label="Следующий кадр"><span aria-hidden="true">→</span></button>
  </div>
  <div class="lb-progress" aria-hidden="true"><i></i></div>
</dialog>'''


REQ_SERVICES = [s["title"] for s in C["services"]] + ["Аренда студии", "SMM"]


def req_dialog():
    chips = "".join(f'<label class="chip"><input type="checkbox" name="svc" value="{esc(t)}"><span>{esc(t)}</span></label>'
                    for t in REQ_SERVICES)
    authors = "".join(f'<option value="{esc(p["name"])}">{esc(p["name"])}</option>' for p in TEAM)
    return f'''
<dialog class="req" id="req" aria-labelledby="req-title">
  <form class="req-in" data-req-form novalidate>
    <div class="req-top">
      <div><p class="kicker">Заявка в 231inc</p><h2 id="req-title" class="req-title">Соберите сообщение</h2></div>
      <button class="lb-close" type="button" data-close aria-label="Закрыть">Закрыть <span aria-hidden="true">×</span></button>
    </div>
    <p class="req-note">Сайт ничего не отправляет сам: готовый текст откроется в WhatsApp или скопируется для Telegram, а отправите его вы.</p>
    <fieldset class="req-set"><legend class="kicker">Что нужно</legend><div class="chips-set">{chips}</div></fieldset>
    <div class="req-grid">
      <label class="field"><span class="kicker">Автор</span><select name="author"><option value="">Не важно</option>{authors}</select></label>
      <label class="field"><span class="kicker">Дата</span><input type="date" name="date"></label>
      <label class="field"><span class="kicker">Как к вам обращаться</span><input type="text" name="name" autocomplete="name" maxlength="60"></label>
    </div>
    <label class="field"><span class="kicker">Комментарий</span><textarea name="note" rows="3" maxlength="600" placeholder="Например: реклама кафе, ролик 30 секунд, нужен сценарий"></textarea></label>
    <div class="req-refs">
      <p class="kicker">Референсы · <span data-refs-count>0</span></p>
      <ul class="req-thumbs" data-refs-list></ul>
      <p class="req-empty" data-refs-empty>Нажмите ♡ на понравившихся кадрах — они появятся здесь и попадут в сообщение.</p>
    </div>
    <div class="req-preview"><p class="kicker">Сообщение</p><pre class="req-text" data-req-text></pre></div>
    <p class="req-error" data-req-error role="alert" hidden>Выберите, что нужно, добавьте референс или напишите комментарий.</p>
    <div class="req-actions">
      <a class="btn btn-accent" data-req-wa href="{esc(WA)}" {EXT}>Открыть в WhatsApp {ARROW_OUT}</a>
      <a class="btn btn-line" data-req-tg href="{esc(TG)}" {EXT}>Скопировать и открыть Telegram {ARROW_OUT}</a>
      <button class="btn btn-line" type="button" data-req-copy>Скопировать текст</button>
    </div>
  </form>
</dialog>
<button class="refs-pill" type="button" data-req hidden aria-label="Референсы — открыть заявку">{HEART}<span>Референсы · <b data-refs-count>0</b></span></button>'''


def intro():
    """Первый заход за сессию: логотип собирается по цифрам на фоне киноракорда (показ включает скрипт в head)."""
    return f'''
<div class="intro" aria-hidden="true">
  <div class="intro-leader"><span class="ring"></span><span class="ring r2"></span><span class="cross"></span><span class="sweep"></span></div>
  <div class="intro-mark">{wordmark_svg("wm-intro", slanted=True)}</div>
  <p class="intro-skip">Нажмите, чтобы пропустить</p>
</div>'''


def case_dialog():
    if not WORKS:
        return ""
    return ('<dialog class="case-dlg" id="case-dlg" aria-labelledby="case-title"><div class="case-top">'
            '<button class="lb-close" type="button" data-close aria-label="Закрыть">Закрыть <span aria-hidden="true">×</span></button>'
            '</div><div class="case-in" id="case-in"></div></dialog>')


def site_data():
    gal = {}
    for p in TEAM:
        gal[p["id"]] = {"label": p["name"], "items": p["works"]}
    gal["studio"] = {"label": f'Студия {C["site"].get("brand", "231inc")}', "items": [r for r in STUDIO.get("photos", []) if r in MEDIA]}
    for z in STUDIO.get("zones", []):
        gal[f'zone-{z["id"]}'] = {"label": z.get("name", ""), "items": [r for r in z.get("photos", []) if r in MEDIA]}
    if BACKSTAGE:
        gal["bts"] = {"label": "Бэкстейдж", "items": [b["ref"] for b in BACKSTAGE]}
    for w in WORKS:
        if w.get("bts"):
            gal[f'case-{w["id"]}'] = {"label": w.get("title", ""), "items": [r for r in w["bts"] if r in MEDIA]}
    sel = [r for r in C.get("selected", []) if r in MEDIA]
    if sel:
        gal["selected"] = {"label": CP.get("selectedTitle", "Избранное"), "items": sel}
    trail = [r for r in C.get("trail", []) if r in MEDIA]
    used = {r for g in gal.values() for r in g["items"]} | set(trail)
    media = {}
    for r in used:
        m = MEDIA[r]
        if m.get("type") == "video":
            pm = MEDIA[m["poster"]]
            media[r] = {"type": "video", "src": m["src"], "poster": f'{pm["base"]}-{pm["jw"][-1]}.jpg', "w": m["w"], "h": m["h"], "alt": m["alt"]}
        else:
            media[r] = {k: m[k] for k in ("w", "h", "ws", "jw", "base", "c", "alt")}
    people = [{"id": p["id"], "name": p["name"]} for p in TEAM]
    return {"galleries": gal, "media": media, "avif": HAS_AVIF, "people": people, "trail": trail,
            "wa": WA, "tg": TG, "tgRent": TG_RENT, "url": C["site"].get("url", "").rstrip("/")}


def views_list():
    v = ["prices", "smm", "rent"] + [f'p-{p["id"]}' for p in TEAM] + (["bts"] if BACKSTAGE else [])
    alias = {} if BACKSTAGE else {"bts": "works"}
    return v, alias


# ---------------------------------------------------------------- иконки и превью ссылки

def logo_polys(scale, ox, oy):
    polys = []
    for sub in re.findall(r"M[^M]+", LOGO):
        nums = list(map(float, re.findall(r"-?\d+(?:\.\d+)?", sub)))
        polys.append([(ox + nums[k] * scale, oy + nums[k + 1] * scale) for k in range(0, len(nums), 2)])
    return polys


def draw_logo(img, box, color):
    x, y, w, h = box
    s = min(w / 1578, h / 1708)
    ox, oy = x + (w - 1578 * s) / 2, y + (h - 1708 * s) / 2
    d = ImageDraw.Draw(img)
    for poly in logo_polys(s, ox, oy):
        d.polygon(poly, fill=color)


def build_icons():
    (OUT / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-120 -60 1818 1828"><style>path{fill:#14161B}'
        '@media (prefers-color-scheme:dark){path{fill:#ECE8DF}}</style>'
        f'<path d="{LOGO}"/></svg>')
    for size, name in ((180, "apple-touch-icon.png"), (32, "favicon-32.png"), (512, "icon-512.png")):
        big = Image.new("RGB", (size * 4, size * 4), (14, 16, 20))
        pad = size * 4 * 0.2
        draw_logo(big, (pad, pad, size * 4 - 2 * pad, size * 4 - 2 * pad), (227, 168, 87))
        big.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)


def build_og():
    out = OUT / "og.jpg"
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (14, 16, 20))
    ph = ImageOps.exif_transpose(Image.open(find_original(C["hero"]["image"]))).convert("RGB")
    pw = 520
    k = max(pw / ph.width, H / ph.height)
    ph = ph.resize((round(ph.width * k), round(ph.height * k)), Image.LANCZOS)
    top = round((ph.height - H) * 0.25)
    img.paste(ph.crop(((ph.width - pw) // 2, top, (ph.width - pw) // 2 + pw, top + H)), (W - pw, 0))
    draw_logo(img, (72, 72, 64, 70), (227, 168, 87))
    d = ImageDraw.Draw(img)
    fsrc = SRC / "fonts" / "source"
    big = ImageFont.truetype(str(fsrc / "Unbounded-Variable.ttf"), 92)
    big.set_variation_by_axes([900])
    mid = ImageFont.truetype(str(fsrc / "Onest-Variable.ttf"), 34)
    mid.set_variation_by_axes([500])
    small = ImageFont.truetype(str(fsrc / "Onest-Variable.ttf"), 24)
    small.set_variation_by_axes([400])
    d.text((70, 250), "231INC", font=big, fill=(236, 232, 223))
    d.text((72, 382), "Продакшн и фотостудия", font=mid, fill=(236, 232, 223))
    d.text((72, 426), "в Душанбе", font=mid, fill=(236, 232, 223))
    d.text((72, 520), CT["address"].replace("Таджикистан, ", ""), font=small, fill=(163, 166, 173))
    d.rectangle((72, 488, 72 + 64, 492), fill=(227, 168, 87))
    img.save(out, quality=86, optimize=True, progressive=True)


# ---------------------------------------------------------------- страница

def build_grain():
    """Плёночное зерно: маленькая плитка шума, повторяется по экрану."""
    import random
    out = OUT / "img" / "grain.png"
    if out.exists():
        return
    rnd = random.Random(231)
    size = 128
    img = Image.new("LA", (size, size))
    # четыре уровня прозрачности вместо сотни: зерно то же, файл в разы легче
    img.putdata([(255 if rnd.random() < 0.5 else 0, rnd.choice((0, 0, 28, 56, 84))) for _ in range(size * size)])
    img.save(out, optimize=True)


def minify_css(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};])\s*", r"\1", css)
    css = re.sub(r";}", "}", css)
    return css.strip()


def json_ld():
    data = {
        "@context": "https://schema.org", "@type": "ProfessionalService", "name": "231inc",
        "description": C["tagline"], "telephone": CT["phone"], "email": CT["email"],
        "address": {"@type": "PostalAddress", "streetAddress": "ул. Айни, 46", "addressLocality": CT["city"], "addressCountry": "TJ"},
        "sameAs": [],
    }
    if C["site"].get("url"):
        data["url"] = C["site"]["url"]
        data["image"] = C["site"]["url"].rstrip("/") + "/og.jpg"
    return json.dumps(data, ensure_ascii=False)


def page():
    site = C["site"]
    url = site.get("url", "").rstrip("/")
    og_img = f"{url}/og.jpg" if url else "og.jpg"
    views, alias = views_list()
    css = (SRC / "styles.css").read_text("utf-8")
    view_css = ",".join([".js[data-view=main] #top"] + [f".js[data-view={v}] #{v}" for v in views])
    css = css.replace("/*VIEW_RULES*/", view_css + "{display:block}")
    js = (SRC / "app.js").read_text("utf-8")
    js_name = "app." + hashlib.sha1(js.encode()).hexdigest()[:8] + ".js"
    for old in OUT.glob("app.*.js"):
        old.unlink()
    (OUT / js_name).write_text(js, "utf-8")
    router = (SRC / "router.js").read_text("utf-8")
    router = router.replace("__VIEWS__", json.dumps(views)).replace("__ALIAS__", json.dumps(alias))
    router = re.sub(r"^\s*//.*$", "", router, flags=re.M)
    router = re.sub(r"\n\s*", "", router)
    data = json.dumps(site_data(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    main = (hero() + strip_section() + works_section() + trail_section() + cases_section() + services_section()
            + smm_section() + rent_teaser() + backstage_section() + contact_section())
    canonical = f'<link rel="canonical" href="{url}/">' if url else ""
    return f'''<!doctype html>
<html lang="ru" data-view="main">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(site["title"])}</title>
<meta name="description" content="{esc(site["description"])}">
<meta name="theme-color" content="#0B0C0F">
{canonical}
<meta property="og:type" content="website">
<meta property="og:locale" content="ru_RU">
<meta property="og:site_name" content="231inc">
<meta property="og:title" content="{esc(site["title"])}">
<meta property="og:description" content="{esc(site["description"])}">
<meta property="og:image" content="{og_img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="icon" href="favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="preload" href="fonts/unbounded-500.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="fonts/onest-var.woff2" as="font" type="font/woff2" crossorigin>
<script>{router}</script>
<style>{minify_css(css)}</style>
<script type="application/ld+json">{json_ld()}</script>
</head>
<body>
{intro()}
<a class="skip" href="#main">Перейти к содержанию</a>
{header()}
<main id="main" tabindex="-1">
<div class="view" id="top">{main}
</div>
{prices_view()}{smm_view()}{rent_view()}{"".join(person_view(p, i) for i, p in enumerate(TEAM))}{bts_view()}
</main>
{footer()}
{menu_dialog()}
{lightbox()}
{case_dialog()}
{case_templates()}
{req_dialog()}
<div class="grain" aria-hidden="true"></div>
<p class="sr" id="live" aria-live="polite"></p>
<script type="application/json" id="site-data">{data}</script>
<script src="{js_name}" defer></script>
</body>
</html>
'''


def main():
    OUT.mkdir(exist_ok=True)
    print("Фото и видео…" + ("" if HAS_AVIF else " (Pillow без AVIF: только WebP и JPEG)"))
    build_all_media()
    (OUT / "fonts").mkdir(exist_ok=True)
    for f in (SRC / "fonts").glob("*.woff2"):
        shutil.copy2(f, OUT / "fonts" / f.name)
    for f in (SRC / "fonts" / "source").glob("OFL-*.txt"):
        shutil.copy2(f, OUT / "fonts" / f.name)
    build_icons()
    build_og()
    build_grain()
    (OUT / "index.html").write_text(page(), "utf-8")
    (OUT / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    (OUT / ".nojekyll").write_text("")
    used = {p.name for p in (OUT / "img").iterdir()}
    keep = set()
    for m in MEDIA.values():
        if m.get("type") == "video":
            continue
        for w in m["ws"]:
            keep |= {f'{Path(m["base"]).name}-{w}.webp', f'{Path(m["base"]).name}-{w}.avif'}
        keep |= {f'{Path(m["base"]).name}-{w}.jpg' for w in m["jw"]}
    keep.add("grain.png")
    for stale in used - keep:
        (OUT / "img" / stale).unlink()
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"Готово: site/ ({size / 1048576:.1f} МБ, фото {len(MEDIA)}), index.html {len((OUT / 'index.html').read_bytes()) // 1024} КБ")


if __name__ == "__main__":
    main()
