"""End-to-end: build plugins, simulate, render. Skipped when the compiler, ffmpeg, a rasterizer or the source
bundle are missing (set OP1VIDEO_SDK, or run ./op1video.py fetch first)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from op1video import build, raster, render, sdk  # noqa: E402


def _ready():
    try:
        build.compiler()
        raster.get_backend()
        if not shutil.which("ffmpeg"):
            return None
        return sdk.resolve(download=False)
    except Exception:
        return None


ROOT_SDK = _ready()


@unittest.skipIf(ROOT_SDK is None, "needs a C compiler, ffmpeg, an SVG rasterizer and the source bundle")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugins = sdk.discover(ROOT_SDK)
        cls.tmp = Path(tempfile.mkdtemp(prefix="op1video-test-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_discovers_plugins(self):
        for name in ("eva", "washer", "amp", "stutter"):
            self.assertIn(name, self.plugins)
        self.assertEqual(self.plugins["amp"].kind, "input")
        self.assertEqual(self.plugins["washer"].kind, "fx")

    def test_render_kinds(self):
        """a synth, a multi-source effect, a tempo-synced effect, a live-input engine, and a patched plugin"""
        for name in ("eva", "washer", "stutter", "amp", "plate"):
            with self.subTest(plugin=name):
                out = self.tmp / f"{name}.mp4"
                render.render(self.plugins[name], ROOT_SDK, out, None,
                              render.Options(layout="screen", scale=1, duration=1.0, jobs=2))
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width",
                                        "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
                self.assertIn("video,320", probe)
                self.assertIn("audio", probe)

    def test_still_draws_something(self):
        import numpy as np
        from PIL import Image
        out = self.tmp / "sid.png"
        render.still(self.plugins["sid"], ROOT_SDK, out, 1.0, None, render.Options(layout="screen", scale=1))
        a = np.asarray(Image.open(out).convert("L"))
        self.assertEqual(a.shape, (160, 320))
        self.assertGreater((a > 60).mean(), 0.02)        # the artwork is there, not a black frame


if __name__ == "__main__":
    unittest.main()
