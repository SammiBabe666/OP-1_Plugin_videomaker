"""SVG -> RGB rasterizers.

Backends, tried in this order by "auto":
  rsvg     librsvg + cairo called through ctypes: no Python packages needed, only the system libraries
           (Debian/Ubuntu: librsvg2-2; macOS: brew install librsvg; Windows: use cairosvg or resvg)
  cairosvg pip install cairosvg (needs the cairo library)
  resvg    the resvg command-line tool (cargo install resvg, or a release binary on PATH)
All return a numpy uint8 array of shape (height, width, 3).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import io
import shutil
import subprocess
import sys

import numpy as np


class RasterError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------- librsvg (ctypes)
class _RsvgRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("width", ctypes.c_double), ("height", ctypes.c_double)]


def _load(names: list[str]):
    for n in names:
        path = ctypes.util.find_library(n) or n
        try:
            return ctypes.CDLL(path)
        except OSError:
            continue
    return None


class RsvgBackend:
    name = "rsvg"

    def __init__(self):
        if sys.platform == "darwin":
            extra = ["/opt/homebrew/lib/librsvg-2.2.dylib", "/usr/local/lib/librsvg-2.2.dylib"]
            extra_c = ["/opt/homebrew/lib/libcairo.2.dylib", "/usr/local/lib/libcairo.2.dylib"]
            extra_g = ["/opt/homebrew/lib/libgobject-2.0.0.dylib", "/usr/local/lib/libgobject-2.0.0.dylib"]
        else:
            extra, extra_c, extra_g = ["librsvg-2.so.2"], ["libcairo.so.2"], ["libgobject-2.0.so.0"]
        self.rsvg = _load(["rsvg-2", "rsvg-2.0", *extra])
        self.cairo = _load(["cairo", *extra_c])
        self.gobj = _load(["gobject-2.0", *extra_g])
        if not (self.rsvg and self.cairo and self.gobj):
            raise RasterError("librsvg/cairo libraries not found")
        r, c, g = self.rsvg, self.cairo, self.gobj
        r.rsvg_handle_new_from_data.restype = ctypes.c_void_p
        r.rsvg_handle_new_from_data.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self.has_doc = hasattr(r, "rsvg_handle_render_document")
        if self.has_doc:
            r.rsvg_handle_render_document.restype = ctypes.c_int
            r.rsvg_handle_render_document.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RsvgRect),
                                                      ctypes.POINTER(ctypes.c_void_p)]
        r.rsvg_handle_render_cairo.restype = ctypes.c_int
        r.rsvg_handle_render_cairo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        c.cairo_image_surface_create.restype = ctypes.c_void_p
        c.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        c.cairo_create.restype = ctypes.c_void_p
        c.cairo_create.argtypes = [ctypes.c_void_p]
        c.cairo_scale.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
        c.cairo_set_source_rgb.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_double]
        c.cairo_paint.argtypes = [ctypes.c_void_p]
        c.cairo_surface_flush.argtypes = [ctypes.c_void_p]
        c.cairo_image_surface_get_data.restype = ctypes.POINTER(ctypes.c_ubyte)
        c.cairo_image_surface_get_data.argtypes = [ctypes.c_void_p]
        c.cairo_image_surface_get_stride.restype = ctypes.c_int
        c.cairo_image_surface_get_stride.argtypes = [ctypes.c_void_p]
        c.cairo_destroy.argtypes = [ctypes.c_void_p]
        c.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
        g.g_object_unref.argtypes = [ctypes.c_void_p]

    def render(self, svg: bytes, width: int, height: int) -> np.ndarray:
        r, c = self.rsvg, self.cairo
        err = ctypes.c_void_p()
        h = r.rsvg_handle_new_from_data(svg, len(svg), ctypes.byref(err))
        if not h:
            raise RasterError("librsvg could not parse the frame SVG")
        surf = c.cairo_image_surface_create(0, width, height)      # CAIRO_FORMAT_ARGB32
        cr = c.cairo_create(surf)
        try:
            c.cairo_set_source_rgb(cr, 0.0, 0.0, 0.0)
            c.cairo_paint(cr)
            if self.has_doc:
                vp = _RsvgRect(0.0, 0.0, float(width), float(height))
                ok = r.rsvg_handle_render_document(h, cr, ctypes.byref(vp), ctypes.byref(err))
            else:
                c.cairo_scale(cr, width / 320.0, height / 160.0)
                ok = r.rsvg_handle_render_cairo(h, cr)
            if not ok:
                raise RasterError("librsvg failed to render a frame")
            c.cairo_surface_flush(surf)
            stride = c.cairo_image_surface_get_stride(surf)
            buf = ctypes.string_at(c.cairo_image_surface_get_data(surf), stride * height)
            a = np.frombuffer(buf, np.uint8).reshape(height, stride // 4, 4)[:, :width]
            return a[:, :, 2::-1].copy()                                 # BGRA (little endian) -> RGB
        finally:
            c.cairo_destroy(cr)
            c.cairo_surface_destroy(surf)
            self.gobj.g_object_unref(h)


# ------------------------------------------------------------------------------------------- cairosvg
class CairoSvgBackend:
    name = "cairosvg"

    def __init__(self):
        try:
            import cairosvg  # noqa: F401
        except Exception as e:                                           # ImportError or missing libcairo
            raise RasterError(f"cairosvg unavailable: {e}")
        import cairosvg
        from PIL import Image
        self.cairosvg, self.Image = cairosvg, Image

    def render(self, svg: bytes, width: int, height: int) -> np.ndarray:
        png = self.cairosvg.svg2png(bytestring=svg, output_width=width, output_height=height,
                                    background_color="black")
        return np.asarray(self.Image.open(io.BytesIO(png)).convert("RGB"))


# ------------------------------------------------------------------------------------------- resvg CLI
class ResvgBackend:
    name = "resvg"

    def __init__(self):
        self.exe = shutil.which("resvg")
        if not self.exe:
            raise RasterError("resvg not on PATH")
        from PIL import Image
        self.Image = Image

    def render(self, svg: bytes, width: int, height: int) -> np.ndarray:
        r = subprocess.run([self.exe, "-w", str(width), "-h", str(height), "--background", "black", "-", "-c"],
                           input=svg, capture_output=True)
        if r.returncode:
            raise RasterError("resvg failed: " + r.stderr.decode(errors="replace")[:300])
        return np.asarray(self.Image.open(io.BytesIO(r.stdout)).convert("RGB"))


BACKENDS = {"rsvg": RsvgBackend, "cairosvg": CairoSvgBackend, "resvg": ResvgBackend}


def get_backend(name: str = "auto"):
    if name != "auto":
        if name not in BACKENDS:
            raise RasterError(f"unknown backend {name}; choose from {', '.join(BACKENDS)}")
        return BACKENDS[name]()
    errors = []
    for cls in BACKENDS.values():
        try:
            return cls()
        except RasterError as e:
            errors.append(f"{cls.name}: {e}")
    raise RasterError("no SVG rasterizer available (see docs/INSTALL.md):\n  " + "\n  ".join(errors))


def available() -> dict[str, str]:
    out = {}
    for n, cls in BACKENDS.items():
        try:
            cls()
            out[n] = "ok"
        except RasterError as e:
            out[n] = str(e)
    return out
