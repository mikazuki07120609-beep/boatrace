# シェア用の画像(OGP 1200x630: og-omote.png・og-ura.png・og-top.png)を作る。日本語のフォント(Noto Sans CJK)と Pillow が要る。
#   python3 scripts/make_og.py site/assets
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = sys.argv[1]
W, H = 1200, 630
NOTO = "/usr/share/fonts/opentype/noto/NotoSansCJK-{}.ttc"


def font(w, size):
    return ImageFont.truetype(NOTO.format(w), size, index=0)


def grad(w, h, c0, c1, horizontal=False):
    im = Image.new("RGB", (w, h), c0)
    px = im.load()
    for y in range(h):
        for x in range(w) if horizontal else [0]:
            pass
    d = ImageDraw.Draw(im)
    n = w if horizontal else h
    for i in range(n):
        t = i / max(1, n - 1)
        c = tuple(round(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
        if horizontal:
            d.line([(i, 0), (i, h)], fill=c)
        else:
            d.line([(0, i), (w, i)], fill=c)
    return im


def glow(im, xy, r, color, alpha):
    layer = Image.new("RGBA", im.size, color + (0,))
    ImageDraw.Draw(layer).ellipse([xy[0] - r, xy[1] - r, xy[0] + r, xy[1] + r], fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(r / 2.2))
    return Image.alpha_composite(im.convert("RGBA"), layer)


def text(d, xy, s, f, fill, anchor="la"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def mark(im, xy, s, f, color, alpha, anchor):
    """透かしの字(半透明で重ねる)。"""
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, s, font=f, fill=color + (alpha,), anchor=anchor)
    return Image.alpha_composite(im.convert("RGBA"), layer)


def omote(path):
    im = grad(W, H, (255, 255, 255), (214, 236, 250)).convert("RGBA")
    im = glow(im, (1040, 120), 260, (190, 228, 250), 120)
    im = mark(im, (1150, 640), "表", font("Black", 420), (20, 120, 184), 24, "rd")
    d = ImageDraw.Draw(im)
    # 丸い印
    d.ellipse([80, 120, 160, 200], fill=(20, 120, 184))
    d.ellipse([96, 132, 128, 164], fill=(127, 211, 255))
    text(d, (185, 160), "水面ノート", font("Black", 96), (20, 120, 184), "lm")
    text(d, (84, 290), "全国のボートレースを、データで読む。", font("Bold", 46), (29, 42, 54))
    text(d, (84, 370), "出走表・直前情報・1周1マークの展開シミュレーション", font("Regular", 34), (64, 84, 100))
    text(d, (84, 420), "当てにいく本線を、毎日自動で。", font("Regular", 34), (64, 84, 100))
    d.rounded_rectangle([84, 500, 520, 566], 33, fill=(20, 120, 184))
    text(d, (302, 533), "suimennote.com", font("Bold", 34), (255, 255, 255), "mm")
    im.convert("RGB").save(path, optimize=True)


def ura(path):
    im = Image.new("RGBA", (W, H), (13, 11, 18, 255))
    im = glow(im, (1080, 60), 420, (122, 24, 48), 230)
    im = glow(im, (180, 640), 300, (60, 14, 36), 200)
    im = mark(im, (1160, 650), "裏", font("Black", 440), (255, 84, 112), 40, "rd")
    d = ImageDraw.Draw(im)
    # 三日月
    d.ellipse([80, 118, 164, 202], fill=(255, 84, 112))
    d.ellipse([104, 104, 184, 184], fill=(13, 11, 18))
    text(d, (190, 160), "裏水面ノート", font("Black", 96), (255, 210, 122), "lm")
    text(d, (84, 290), "荒れを狙う、裏本線。", font("Bold", 50), (243, 237, 230))
    text(d, (84, 372), "万舟になる見込みと、荒れるとしたら一番ありそうな決着を", font("Regular", 33), (200, 188, 210))
    text(d, (84, 420), "風・波・潮・展開・人気のずれから。", font("Regular", 33), (200, 188, 210))
    d.rounded_rectangle([84, 500, 520, 566], 33, fill=(255, 84, 112))
    text(d, (302, 533), "suimennote.com", font("Bold", 34), (13, 11, 18), "mm")
    im.convert("RGB").save(path, optimize=True)


def top(path):
    left = grad(W // 2, H, (255, 255, 255), (214, 236, 250)).convert("RGBA")
    right = Image.new("RGBA", (W - W // 2, H), (13, 11, 18, 255))
    right = glow(right, (420, 60), 360, (122, 24, 48), 230)
    im = Image.new("RGBA", (W, H))
    im.paste(left, (0, 0))
    im.paste(right, (W // 2, 0))
    im = mark(im, (W // 2 - 20, 650), "表", font("Black", 360), (20, 120, 184), 26, "rd")
    im = mark(im, (W // 2 + 20, 650), "裏", font("Black", 360), (255, 84, 112), 44, "ld")
    d = ImageDraw.Draw(im)
    text(d, (W // 4, 230), "水面ノート", font("Black", 74), (20, 120, 184), "mm")
    text(d, (W // 4, 320), "当てにいく本線", font("Bold", 38), (29, 42, 54), "mm")
    text(d, (3 * W // 4, 230), "裏水面ノート", font("Black", 74), (255, 210, 122), "mm")
    text(d, (3 * W // 4, 320), "荒れを狙う裏本線", font("Bold", 38), (243, 237, 230), "mm")
    d.rounded_rectangle([W // 2 - 230, 500, W // 2 + 230, 566], 33, fill=(255, 255, 255))
    text(d, (W // 2, 533), "suimennote.com", font("Bold", 34), (29, 42, 54), "mm")
    f = font("Medium", 27)
    tw = d.textlength("全国のボートレースを、データで読む。買い目は出しません。", font=f)
    d.rounded_rectangle([W // 2 - tw / 2 - 26, 416, W // 2 + tw / 2 + 26, 464], 24, fill=(255, 255, 255, 215))
    text(d, (W // 2, 440), "全国のボートレースを、データで読む。買い目は出しません。", f, (58, 70, 82), "mm")
    im.convert("RGB").save(path, optimize=True)


omote(f"{OUT}/og-omote.png")
ura(f"{OUT}/og-ura.png")
top(f"{OUT}/og-top.png")
print("ok")
