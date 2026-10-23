"""Unit tests that need no compiler, ffmpeg or source bundle."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from op1video import scene, svgframe  # noqa: E402
from op1video.sdk import Plugin  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def fake_plugin(kind="synth"):
    return Plugin(name="demo", display="demo", dir=Path("."), kind=kind, symbol="ENGINE_demo", sources=[],
                  defaults=[16384, 8192, 0, 32767])


class NoteNames(unittest.TestCase):
    def test_names(self):
        # OP-1 (TE) naming, as the tuner and Palme show notes: C3 = MIDI 60, A3 = 440 Hz
        self.assertEqual(scene.note_number("C3"), 60)
        self.assertEqual(scene.note_number("A3"), 69)
        self.assertEqual(scene.note_number("F#2"), 54)
        self.assertEqual(scene.note_number("Bb1"), 46)
        self.assertEqual(scene.note_number("C-2"), 0)
        self.assertEqual(scene.note_number(72), 72)

    def test_bad(self):
        with self.assertRaises(scene.SceneError):
            scene.note_number("H4")


class Scenes(unittest.TestCase):
    def test_defaults_and_percent(self):
        sc = scene.from_dict({"knobs": [50, None, 100, {"raw": 123}]}, fake_plugin())
        self.assertEqual(sc.start[:4], [16384, 8192, 32767, 123])
        self.assertEqual(sc.start[4], 0x5300 + 32)

    def test_glide_and_jump(self):
        sc = scene.from_dict({"moves": [{"at": 1, "to": 2, "knob": "blue", "value": 100, "ease": "linear"},
                                        {"at": 3, "knob": "blue", "value": 0}]}, fake_plugin())
        self.assertEqual(sc.words_at(0.5)[0], 16384)
        self.assertAlmostEqual(sc.words_at(1.5)[0], (16384 + 32767) / 2, delta=2)
        self.assertEqual(sc.words_at(2.5)[0], 32767)
        self.assertEqual(sc.words_at(3.5)[0], 0)

    def test_moves_out_of_order(self):
        sc = scene.from_dict({"moves": [{"at": 3, "knob": "green", "value": 0},
                                        {"at": 1, "to": 2, "knob": "green", "value": 100}]}, fake_plugin())
        self.assertEqual(sc.words_at(2.5)[1], 32767)
        self.assertEqual(sc.words_at(3.5)[1], 0)

    def test_sequence(self):
        sc = scene.from_dict({"duration": 2, "notes": [{"at": 0, "every": 0.5, "len": 0.4,
                                                        "notes": "C3 - E3+G3", "until": 2}]}, fake_plugin())
        starts = sorted((s, n) for s, e, n, v in sc.notes)
        self.assertEqual(starts, [(0.0, 60), (1.0, 64), (1.0, 67), (1.5, 60)])

    def test_press_toggles(self):
        sc = scene.from_dict({"moves": [{"at": 1, "press": "orange"}, {"at": 2, "press": "orange"}]}, fake_plugin())
        self.assertEqual([sc.pages_at(t)[3] for t in (0.5, 1.5, 2.5)], [0, 1, 0])

    def test_tilt_degrees(self):
        sc = scene.from_dict({"moves": [{"at": 0, "tilt": [0, 30]}]}, fake_plugin())
        ax, ay, az = sc.tilt_at(1)
        self.assertEqual(ax, 0)
        self.assertAlmostEqual(ay, -8192, delta=2)
        self.assertAlmostEqual(az, 14189, delta=2)
        self.assertEqual(scene.from_dict({}, fake_plugin()).tilt_at(0), [0, 0, 16384])

    def test_errors(self):
        for bad in ({"moves": [{"at": 1, "knob": "purple", "value": 3}]}, {"fps": 25},
                    {"source": {"type": "theremin"}}, {"notes": [{"at": 0}]}):
            with self.assertRaises(scene.SceneError):
                scene.from_dict(bad, fake_plugin())

    def test_script(self):
        sc = scene.from_dict({"duration": 1, "fps": 30, "notes": [{"at": 0.5, "note": "A3", "len": 0.25}]},
                             fake_plugin())
        lines = sc.script().splitlines()
        self.assertEqual(sum(1 for l in lines if l.startswith("k ")), 30)
        self.assertIn("on 22050 69 100", lines)
        self.assertIn("off 33075 69", lines)
        self.assertEqual(lines[-1], "end")

    def test_auto_scene(self):
        for kind in ("synth", "fx"):
            sc = scene.from_dict(scene.auto(fake_plugin(kind)), fake_plugin(kind))
            self.assertGreater(len(sc.notes), 0)
            self.assertEqual(len(sc.tracks), 4)


class ShippedScenes(unittest.TestCase):
    def test_all_parse(self):
        import yaml
        for f in sorted((ROOT / "scenes").glob("*.yaml")) + sorted((ROOT / "examples").glob("*.yaml")):
            d = yaml.safe_load(f.read_text())
            with self.subTest(scene=f.name):
                scene.from_dict(d, fake_plugin("fx" if d.get("source") else "synth"))


class Frames(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "_tmp.svg"
        self.tmp.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 160">'
                            '<g id="arm"><line x1="0" y1="0" x2="10" y2="0" stroke="#FFFFFF" stroke-width="2"/></g>'
                            '<circle id="dot" cx="5" cy="5" r="2" fill="#00ED95"/></svg>')

    def tearDown(self):
        self.tmp.unlink(missing_ok=True)

    def test_ids_and_frame(self):
        s = svgframe.SvgScreen(self.tmp, stroke_scale=0.5)
        ids = self.tmp.with_suffix(".ids")
        s.write_ids(ids)
        self.assertIn("dot - 00ed95ff", ids.read_text())
        ids.unlink()
        doc = s.frame({"nodes": {"arm": {"m": [1024, 0, 0, 0, 1024, 0, 10240, 0, 1024]}, "dot": {"v": 0}},
                       "ops": [["svg"], ["l", 0, 0, 10240, 10240, 1024, "ff0000ff"],
                               ["t", 1024, 4, 14, 0, "ffffffff", "rate"]]}).decode()
        self.assertIn('transform="matrix(1.00000 0.00000 0.00000 1.00000 10.00000 0.00000)"', doc)
        self.assertIn('display="none"', doc)
        self.assertIn('stroke-width="1"', doc)                 # 2 * 0.5
        self.assertIn('stroke-linecap="butt"', doc)
        self.assertIn(">RATE<", doc)                           # firmware font: capitals only


if __name__ == "__main__":
    unittest.main()
