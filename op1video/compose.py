"""Frame layouts: place the rendered OLED image on the output canvas.

  screen  just the OLED (320x160 times --scale); for the workshop cards and embeds
  card    16:9 (1920x1080 by default): title, the screen, the four encoders with live values, a keyboard strip
  square  1:1 (1080x1080 by default): the same, stacked for social posts
"""
from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# the encoder colours used throughout the plugin artwork (blue, green, white, red/orange)
ENCODER_RGB = [(0x69, 0x8E, 0xFF), (0x00, 0xED, 0x95), (0xFF, 0xFF, 0xFF), (0xFF, 0x3A, 0x5D)]
BG = (12, 12, 13)
PANEL = (0, 0, 0)
BEZEL = (34, 34, 37)
DIM = (120, 120, 128)
FAINT = (52, 52, 58)

FONT_CANDIDATES = ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans", "FreeSans", "Liberation Sans"]


@lru_cache(maxsize=None)
def _font_path(bold: bool, override: str | None) -> str | None:
    if override:
        return override
    if shutil.which("fc-match"):
        for fam in FONT_CANDIDATES:
            q = fam + (":weight=bold" if bold else ":weight=medium")
            r = subprocess.run(["fc-match", "-f", "%{file}\n%{family}", q], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout:
                path, family = (r.stdout.split("\n") + [""])[:2]
                if fam.split()[0].lower() in family.lower() and path.lower().endswith((".ttf", ".otf", ".ttc")):
                    return path
    for p in ["/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            ImageFont.truetype(p, 10)
            return p
        except OSError:
            continue
    return None


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False, override: str | None = None):
    p = _font_path(bold, override)
    if p:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:                                   # Pillow < 10.1
        return ImageFont.load_default()


@dataclass
class FrameInfo:
    t: float
    words: list[int]          # 8 knob words (Q15)
    pages: list[int]          # page-2 / latch flags per encoder
    held: list[int]           # MIDI notes held


class Layout:
    name = "screen"

    def __init__(self, scene, plugin, width: int | None = None, height: int | None = None, scale: int = 4,
                 font_file: str | None = None, show_keys: bool | None = None):
        self.scene, self.plugin, self.font_file = scene, plugin, font_file
        self.scale = scale
        self.show_keys = show_keys
        self.setup(width, height)

    def setup(self, width, height):
        self.size = ((width or 320 * self.scale) // 2 * 2, (height or 160 * self.scale) // 2 * 2)
        self.screen_box = (0, 0, *self.size)

    @property
    def screen_px(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.screen_box
        return x1 - x0, y1 - y0

    def compose(self, oled: np.ndarray, info: FrameInfo) -> np.ndarray:
        if oled.shape[1] != self.size[0] or oled.shape[0] != self.size[1]:
            oled = np.asarray(Image.fromarray(oled).resize(self.size, Image.LANCZOS))
        return oled


class CardLayout(Layout):
    """16:9: title top left, the OLED in a bezel, four encoders and a keyboard strip below."""
    name = "card"
    default = (1920, 1080)

    def setup(self, width, height):
        W, H = width or self.default[0], height or self.default[1]
        W, H = W // 2 * 2, H // 2 * 2
        self.size = (W, H)
        u = H / 1080.0
        self.u = u
        sw = int(min(W * 0.70, (H * 0.56) * 2)) // 2 * 2
        sh = sw // 2
        sx, sy = (W - sw) // 2, int(150 * u)
        self.screen_box = (sx, sy, sx + sw, sy + sh)
        self.base = self._background()

    def _background(self) -> Image.Image:
        W, H = self.size
        u = self.u
        im = Image.new("RGB", self.size, BG)
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = self.screen_box
        pad = int(22 * u)
        d.rounded_rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), radius=int(26 * u), fill=PANEL,
                            outline=BEZEL, width=max(1, int(2 * u)))
        tx = x0 - pad
        d.text((tx, int(38 * u)), self.scene.title or self.plugin.display.upper(), fill=(240, 240, 240),
               font=font(int(52 * u), True, self.font_file))
        if self.scene.subtitle:
            tw = d.textlength(self.scene.title or self.plugin.display.upper(), font=font(int(52 * u), True, self.font_file))
            d.text((tx + tw + int(26 * u), int(56 * u)), self.scene.subtitle, fill=DIM,
                   font=font(int(28 * u), False, self.font_file))
        right = f"{self.plugin.kind.upper()}  ·  OP–1"
        f = font(int(22 * u), False, self.font_file)
        d.text((x1 + pad - d.textlength(right, font=f), int(62 * u)), right, fill=FAINT, font=f)
        return im

    def _keys_visible(self) -> bool:
        if self.show_keys is not None:
            return self.show_keys
        return self.plugin.kind != "input" and self.scene.source != "drums" and bool(self.scene.notes)

    def _dials(self, d: ImageDraw.ImageDraw, info: FrameInfo, top: int, height: int):
        W = self.size[0]
        u = self.u
        x0, _, x1, _ = self.screen_box
        cols = 4
        cw = (x1 - x0) / cols
        r = int(min(height * 0.34, cw * 0.2))
        for i in range(cols):
            cx = int(x0 + cw * (i + 0.5)) - int(cw * 0.16)
            cy = top + r + int(6 * u)
            col = ENCODER_RGB[i]
            paged = bool(info.pages[i]) if i < len(info.pages) else False
            word = info.words[5 + i] if (paged and i < 3) else info.words[i]
            v = max(0.0, min(1.0, word / 32767))
            box = (cx - r, cy - r, cx + r, cy + r)
            start, sweep = 135, 270
            d.arc(box, start, start + sweep, fill=FAINT, width=max(2, int(r * 0.22)))
            if v > 0.002:
                d.arc(box, start, start + sweep * v, fill=col, width=max(2, int(r * 0.22)))
            ang = math.radians(start + sweep * v)
            d.line((cx, cy, cx + math.cos(ang) * r * 0.62, cy + math.sin(ang) * r * 0.62), fill=col,
                   width=max(2, int(r * 0.12)))
            label = self.scene.labels[i] if i < len(self.scene.labels) else ""
            if paged and i < 3:
                label += "  ·  P2"
            tx = cx + r + int(18 * u)
            d.text((tx, cy - int(26 * u)), label.upper(), fill=col, font=font(int(22 * u), True, self.font_file))
            d.text((tx, cy + int(2 * u)), f"{round(v * 100):d}", fill=(225, 225, 230),
                   font=font(int(30 * u), False, self.font_file))

    def _keyboard(self, d: ImageDraw.ImageDraw, held: list[int], top: int, height: int):
        x0, _, x1, _ = self.screen_box
        lo, hi = 36, 84                                   # C2 .. C6
        whites = [n for n in range(lo, hi + 1) if n % 12 in (0, 2, 4, 5, 7, 9, 11)]
        ww = (x1 - x0) / len(whites)
        hs = set(held)
        for i, n in enumerate(whites):
            x = x0 + i * ww
            on = n in hs
            d.rectangle((int(x) + 1, top, int(x + ww) - 1, top + height),
                        fill=(250, 250, 250) if on else (44, 44, 48))
        for i, n in enumerate(whites[:-1]):
            b = n + 1
            if b % 12 in (1, 3, 6, 8, 10):
                x = x0 + (i + 1) * ww - ww * 0.32
                on = b in hs
                d.rectangle((int(x), top, int(x + ww * 0.64), top + int(height * 0.6)),
                            fill=(250, 250, 250) if on else (14, 14, 16))
        # notes outside the strip still light an edge marker
        if any(n < lo for n in hs):
            d.rectangle((x0 - 10, top, x0 - 5, top + height), fill=(250, 250, 250))
        if any(n > hi for n in hs):
            d.rectangle((x1 + 5, top, x1 + 10, top + height), fill=(250, 250, 250))

    def compose(self, oled: np.ndarray, info: FrameInfo) -> np.ndarray:
        im = self.base.copy()
        sw, sh = self.screen_px
        o = Image.fromarray(oled)
        if o.size != (sw, sh):
            o = o.resize((sw, sh), Image.LANCZOS)
        im.paste(o, self.screen_box[:2])
        d = ImageDraw.Draw(im)
        u = self.u
        H = self.size[1]
        top = self.screen_box[3] + int(56 * u)
        keys = self._keys_visible()
        kh = int(44 * u) if keys else 0
        dial_h = H - top - kh - int(48 * u)
        self._dials(d, info, top, dial_h)
        if keys:
            self._keyboard(d, info.held, H - kh - int(30 * u), kh)
        return np.asarray(im)


class SquareLayout(CardLayout):
    name = "square"
    default = (1080, 1080)

    def setup(self, width, height):
        W, H = width or self.default[0], height or self.default[1]
        W, H = W // 2 * 2, H // 2 * 2
        self.size = (W, H)
        self.u = H / 1080.0 * 0.9
        sw = int(W * 0.86) // 2 * 2
        sh = sw // 2
        sx, sy = (W - sw) // 2, int(170 * H / 1080)
        self.screen_box = (sx, sy, sx + sw, sy + sh)
        self.base = self._background()


LAYOUTS = {"screen": Layout, "card": CardLayout, "square": SquareLayout}


def make(name: str, scene, plugin, width=None, height=None, scale=4, font_file=None, show_keys=None) -> Layout:
    if name not in LAYOUTS:
        raise ValueError(f"unknown layout {name}; choose from {', '.join(LAYOUTS)}")
    return LAYOUTS[name](scene, plugin, width, height, scale, font_file, show_keys)
