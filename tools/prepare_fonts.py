"""Готовит шрифты сайта из исходных TTF (запускать один раз, если меняются шрифты).

- Unbounded: статичное начертание 500 для заголовков, подмножество латиница + кириллица.
- Onest: переменный шрифт с осью веса 400–600, латиница + кириллица (+ таджикские буквы на будущее).
- Слово-логотип «231INC» (Unbounded 900) переводится в SVG-контуры: шрифт 900 на сайт не грузится.

Нужны fonttools, brotli и skia-pathops: pip install fonttools brotli skia-pathops
"""
import json, pathlib
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.varLib.instancer import OverlapMode
from fontTools import subset
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "fonts" / "source"
OUT = ROOT / "src" / "fonts"

LATIN = "U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+02C6,U+02DA,U+02DC"
CYR = "U+0400-045F,U+0490-0491"
TAJIK = "U+0492-0493,U+049A-049B,U+04B2-04B3,U+04B6-04B7,U+04E2-04E3,U+04EE-04EF"
PUNCT = "U+2010-2027,U+2030-203A,U+2044,U+20AC,U+2116,U+2122,U+2190-2199,U+2212,U+2215"


def unicodes(spec):
    out = []
    for part in spec.split(","):
        a, _, b = part.replace("U+", "").partition("-")
        out += range(int(a, 16), int(b or a, 16) + 1)
    return out


def write_subset(font, ranges, path):
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga", "calt", "tnum", "lnum", "case", "ccmp", "locl", "mark", "mkmk"]
    opts.name_IDs = [0, 1, 2, 3, 4, 5, 6]
    opts.notdef_outline = True
    opts.hinting = False
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=unicodes(ranges))
    sub.subset(font)
    subset.save_font(font, str(path), opts)
    print(path.name, path.stat().st_size // 1024, "KB")


# Unbounded 500
unb = TTFont(SRC / "Unbounded-Variable.ttf")
# перекрытия контуров убираем: иначе в контурном («обводка») тексте видны линии внутри букв
unb500 = instancer.instantiateVariableFont(unb, {"wght": 500}, overlap=OverlapMode.REMOVE)
write_subset(unb500, ",".join([LATIN, CYR, PUNCT]), OUT / "unbounded-500.woff2")

# Onest 400–600
on = TTFont(SRC / "Onest-Variable.ttf")
on46 = instancer.instantiateVariableFont(on, {"wght": (400, 600)})
write_subset(on46, ",".join([LATIN, CYR, TAJIK, PUNCT]), OUT / "onest-var.woff2")

# Слово-логотип «231INC» в контурах (Unbounded 900)
unb900 = instancer.instantiateVariableFont(TTFont(SRC / "Unbounded-Variable.ttf"), {"wght": 900}, overlap=OverlapMode.REMOVE)
gs = unb900.getGlyphSet()
cmap = unb900.getBestCmap()
upm = unb900["head"].unitsPerEm
asc = unb900["OS/2"].sCapHeight or 700
hmtx = unb900["hmtx"]


def run(text, x0=0):
    """Контуры букв по отдельности: для анимации подвала каждая буква выезжает сама."""
    glyphs, x = [], x0
    for ch in text:
        pen = SVGPathPen(gs)
        g = cmap[ord(ch)]
        gs[g].draw(TransformPen(pen, (1, 0, 0, -1, x, asc)))  # SVG: ось Y вниз, базовая линия на высоте прописной
        glyphs.append(pen.getCommands())
        x += hmtx[g][0]
    return glyphs, x


g231, x = run("231")
ginc, x2 = run("INC", x)
data = {"viewBox": [0, 0, x2, asc], "p231": "".join(g231), "pinc": "".join(ginc), "g231": g231, "ginc": ginc, "split": x, "upm": upm}
(OUT / "wordmark.json").write_text(json.dumps(data))
print("wordmark", data["viewBox"])
