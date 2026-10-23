"""Turn the simulator's per-frame records into SVG documents.

A frame record (one JSON line from op1sim) has:
  nodes: {id: {"m": [a,b,0,c,d,0,tx,ty,1024], "v": 0, "s": "rrggbbaa", "fl": "rrggbbaa"}}  (Q10 matrix)
  ops  : [["svg"] | ["l", x0, y0, x1, y1, w, "rrggbbaa"] | ["t", x, y, size, align, "rrggbbaa", "str", [m9]]]
Node matrices are row-vector matrices, x' = a*x + c*y + tx, y' = b*x + d*y + ty, which is exactly SVG's
matrix(a b c d tx ty). Ops are immediate-mode drawing; the SVG is drawn where ["svg"] appears (first, if the
screen code never says so). The OLED background is black.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
W, H = 320, 160

NAMED = {"white": "ffffff", "black": "000000", "red": "ff0000", "green": "008000", "blue": "0000ff"}

# The device's rasteriser draws strokes thinner than a browser would for the same stroke-width; 0.7 matches the
# workshop's native emulator captures (measured on EVA and Washer). Override with --stroke-scale.
DEFAULT_STROKE_SCALE = 0.7

# The firmware text renderer's font is not part of the source bundle, so text is set in a similar light sans.
# Measured on the native captures: `y` is the top of the em box, the baseline is y + size, and capitals are about
# `size` tall. CAP_HEIGHT is the cap height of the substitute font as a fraction of its em.
# The firmware font has capitals only and is thin and condensed. Glyph height fits 0.8 * size + 3 px for letters
# and digits alike (measured: size 14 -> 14.2 px, size 40 -> 35 px).
TEXT_FONT = "Inter, Helvetica Neue, Helvetica, Arial, DejaVu Sans, sans-serif"
TEXT_WEIGHT = "200"
CAP_HEIGHT = 0.727
CONDENSE = 0.84


def glyph_height(size: float) -> float:
    return 0.8 * size + 3


def _hex(paint: str | None, opacity: str | None = None) -> str | None:
    """SVG paint -> rrggbbaa, or None for none/unset."""
    if not paint:
        return None
    p = paint.strip().lower()
    if p in ("none", "transparent") or p.startswith("url("):
        return None
    if p in NAMED:
        rgb = NAMED[p]
    elif p.startswith("#") and len(p) == 4:
        rgb = "".join(ch * 2 for ch in p[1:])
    elif p.startswith("#") and len(p) == 7:
        rgb = p[1:]
    elif p.startswith("rgb("):
        parts = [int(float(x)) for x in p[4:-1].split(",")]
        rgb = "".join(f"{v:02x}" for v in parts[:3])
    else:
        return None
    a = 255
    if opacity:
        try:
            a = max(0, min(255, round(float(opacity) * 255)))
        except ValueError:
            pass
    return rgb + f"{a:02x}"


def _inherited(el, attr: str) -> str | None:
    while el is not None:
        v = el.get(attr)
        if v is not None:
            return v
        el = el.getparent()
    return None


class SvgScreen:
    """A plugin screen SVG, ready to be re-rendered per frame."""

    def __init__(self, path: Path, stroke_scale: float = DEFAULT_STROKE_SCALE):
        self.path = path
        self.stroke_scale = stroke_scale
        parser = etree.XMLParser(remove_comments=True, resolve_entities=False, no_network=True)
        self.tree = etree.parse(str(path), parser)
        self.root = self.tree.getroot()
        # the device always renders the 320x160 user space onto its panel
        self.root.set("viewBox", f"0 0 {W} {H}")
        self.root.set("width", str(W))
        self.root.set("height", str(H))
        if stroke_scale != 1.0:
            for el in self.root.iter():
                sw = el.get("stroke-width")
                if sw is not None:
                    try:
                        el.set("stroke-width", f"{float(sw.replace('px', '')) * stroke_scale:.4g}")
                    except ValueError:
                        pass
                elif el.get("stroke") not in (None, "none") and el.getparent() is not None \
                        and _inherited(el.getparent(), "stroke-width") is None:
                    el.set("stroke-width", f"{stroke_scale:.4g}")
        self._order = list(self.root.iter())
        self.ids = {}
        for i, el in enumerate(self._order):
            eid = el.get("id")
            if eid and eid not in self.ids:
                self.ids[eid] = i

    def write_ids(self, path: Path) -> None:
        """The node list op1sim needs: lookups of ids not in the SVG return NULL, as on the device."""
        lines = []
        for eid, i in self.ids.items():
            if any(c.isspace() for c in eid):
                continue
            el = self._order[i]
            st = _hex(_inherited(el, "stroke"), _inherited(el, "stroke-opacity"))
            fi_raw = _inherited(el, "fill")
            fi = _hex(fi_raw if fi_raw is not None else "#000000", _inherited(el, "fill-opacity"))
            lines.append(f"{eid} {st or '-'} {fi or '-'}")
        path.write_text("\n".join(lines) + "\n")

    def frame(self, rec: dict) -> bytes:
        root = copy.deepcopy(self.root)
        order = list(root.iter())
        for eid, st in rec.get("nodes", {}).items():
            i = self.ids.get(eid)
            if i is None:
                continue
            el = order[i]
            m = st.get("m")
            if m:
                a, b, _, c, d, _, tx, ty, _ = m
                el.set("transform", "matrix(%s)" % " ".join(f"{v / 1024:.5f}" for v in (a, b, c, d, tx, ty)))
            if st.get("v") == 0:
                el.set("display", "none")
            if "s" in st:
                _paint(el, "stroke", st["s"])
            if "fl" in st:
                _paint(el, "fill", st["fl"])

        ops = rec.get("ops", [])
        svg_at = next((i for i, o in enumerate(ops) if o[0] == "svg"), None)
        before = ops[:svg_at] if svg_at is not None else []
        after = ops[svg_at + 1:] if svg_at is not None else ops
        after = [o for o in after if o[0] != "svg"]

        art = list(root)
        for child in art:
            root.remove(child)
        bg = etree.SubElement(root, f"{{{SVG_NS}}}rect", x="0", y="0", width=str(W), height=str(H), fill="#000000")
        bg.tail = None
        if before:
            root.append(_ops_group(before, self.stroke_scale))
        for child in art:
            root.append(child)
        if after:
            root.append(_ops_group(after, self.stroke_scale))
        return etree.tostring(root)


def _paint(el, attr: str, rgba: str) -> None:
    el.set(attr, "#" + rgba[:6])
    a = int(rgba[6:8], 16)
    if a < 255:
        el.set(attr + "-opacity", f"{a / 255:.3f}")
    elif el.get(attr + "-opacity") is not None:
        del el.attrib[attr + "-opacity"]


def _ops_group(ops: list, stroke_scale: float = 1.0) -> etree._Element:
    g = etree.Element(f"{{{SVG_NS}}}g")
    for o in ops:
        if o[0] == "l":
            _, x0, y0, x1, y1, w, rgba = o
            a = int(rgba[6:8], 16)
            if a == 0:
                continue
            el = etree.SubElement(g, f"{{{SVG_NS}}}line",
                                  x1=f"{x0 / 1024:.3f}", y1=f"{y0 / 1024:.3f}",
                                  x2=f"{x1 / 1024:.3f}", y2=f"{y1 / 1024:.3f}",
                                  stroke="#" + rgba[:6], **{"stroke-width": f"{max(w * stroke_scale, 256) / 1024:.3f}",
                                                             "stroke-linecap": "butt"})
            if a < 255:
                el.set("stroke-opacity", f"{a / 255:.3f}")
        elif o[0] == "t":
            x, y, size, align, rgba, text = o[1:7]
            m = o[7] if len(o) > 7 else None
            size = max(int(size), 4)
            # firmware text: x in Q10, y = top of the em in px, baseline at y + size
            anchor = {0: "start", 1: "middle", 2: "end"}.get(int(align), "start")
            text = str(text).upper()
            fs = glyph_height(size) / CAP_HEIGHT
            px = x / 1024
            el = etree.SubElement(g, f"{{{SVG_NS}}}text", x=f"{px:.2f}", y=f"{y + size:.2f}",
                                  fill="#" + rgba[:6], **{"font-size": f"{fs:.2f}",
                                                          "font-family": TEXT_FONT, "font-weight": TEXT_WEIGHT,
                                                          "text-anchor": anchor})
            el.set("transform", f"translate({px:.2f} 0) scale({CONDENSE} 1) translate({-px:.2f} 0)")
            if int(rgba[6:8], 16) < 255:
                el.set("fill-opacity", f"{int(rgba[6:8], 16) / 255:.3f}")
            el.text = text
            if m and m != [1024, 0, 0, 0, 1024, 0, 0, 0, 1024]:
                a_, b_, _, c_, d_, _, tx, ty, _ = m
                el.set("transform", "matrix(%s) " % " ".join(f"{v / 1024:.5f}" for v in (a_, b_, c_, d_, tx, ty))
                       + el.get("transform"))
    return g


def read_frames(path: Path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
