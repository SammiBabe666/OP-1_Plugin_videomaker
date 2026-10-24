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
            if any(not (f.parent / e["file"]).exists() for e in d.get("presets") or []):
                d.pop("presets")                          # preset files you supply yourself (examples/README.md)
            with self.subTest(scene=f.name):
                scene.from_dict(d, fake_plugin("fx" if d.get("source") else "synth"), f.parent)


def write_preset(path, name="demo", knobs=(1000, 2000, 3000, 4000, 21248, 5000, 6000, 7000), adsr=(64, 9000, 16384, 7000),
                 octave=0, kind="demo"):
    """an OP-1 style AIFC: FORM/AIFC with the patch JSON in an APPL chunk signed 'op-1'"""
    import json
    import struct
    body = b"op-1" + json.dumps({"type": kind, "name": name, "knobs": list(knobs), "adsr": list(adsr) + [2048, 5568, 4000, 4000],
                                 "octave": octave, "fx_active": True, "fx_type": "delay", "lfo_active": False,
                                 "lfo_type": "tremolo"}).encode() + b"\0"
    if len(body) & 1:
        body += b"\0"
    chunks = b"FVER" + struct.pack(">II", 4, 0xA2805140) + b"APPL" + struct.pack(">I", len(body)) + body
    Path(path).write_bytes(b"FORM" + struct.pack(">I", 4 + len(chunks)) + b"AIFC" + chunks)


class Presets(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_read(self):
        from op1video import presets
        write_preset(self.dir / "a.aif", name="glass veil", octave=1)
        p = presets.load(self.dir / "a.aif")
        self.assertEqual((p.name, p.octave, p.knobs[5], p.fx, p.lfo), ("glass veil", 1, 5000, "delay", None))
        a, d, s, r = p.envelope
        self.assertEqual(a, 5)                            # 64 is the shortest attack
        self.assertEqual(d, 1500)
        self.assertEqual(s, 50)
        self.assertTrue(presets.env_ms(16320) >= presets.env_ms(12000) >= presets.env_ms(4000))

    def test_scene_presets(self):
        write_preset(self.dir / "one.aif", name="one", knobs=(32767, 0, 0, 0, 21248, 9000, 100, 200))
        write_preset(self.dir / "two.aif", name="two", knobs=(0, 32767, 0, 0, 21248, 20000, 300, 400), octave=-1)
        d = {"duration": 4, "presets": [{"at": 0, "file": "one.aif"}, {"at": 2, "file": "two.aif", "glide": 1}],
             "notes": [{"at": 0.5, "note": "C3"}, {"at": 2.5, "note": "C3"}],
             "moves": [{"at": 3.5, "knob": "blue", "value": 50}]}
        sc = scene.from_dict(d, fake_plugin(), self.dir)
        self.assertEqual(sc.words_at(1)[:2], [32767, 0])
        self.assertEqual(sc.words_at(1)[4], 0x5300 + 32)  # the selector stays the plugin's
        mid = sc.words_at(2.5)
        self.assertTrue(0 < mid[0] < 32767)               # encoders glide ...
        self.assertEqual(mid[5], 20000)                   # ... page-2 words switch at once
        self.assertEqual(sc.words_at(3.6)[0], 16384)      # a later move still applies
        self.assertEqual(sorted(n for _, _, n, _ in sc.notes), [48, 60])   # octave -1 from the second preset
        self.assertEqual([round(t, 1) for t, _ in sc.env_events], [0.0, 2.0])
        self.assertEqual([(c["title"], c["index"], c["count"]) for c in sc.captions], [("one", 1, 2), ("two", 2, 2)])
        self.assertEqual(sc.caption_at(3)["title"], "two")
        self.assertIn("env 88200", sc.script())

    def test_wrong_engine(self):
        write_preset(self.dir / "x.aif", kind="eva")
        with self.assertRaises(scene.SceneError):
            scene.from_dict({"presets": [{"at": 0, "file": "x.aif"}]}, fake_plugin(), self.dir)


class Layouts(unittest.TestCase):
    def test_vertical_compose(self):
        import numpy as np
        from op1video import compose
        sc = scene.from_dict({"duration": 2, "notes": [{"at": 0, "note": "C3", "len": 1}],
                              "captions": [{"at": 0, "title": "hello", "text": "world"}]}, fake_plugin())
        lay = compose.make("vertical", sc, fake_plugin())
        self.assertEqual(lay.size, (1080, 1920))
        w, h = lay.screen_px
        self.assertEqual(w, 2 * h)
        out = lay.compose(np.zeros((h, w, 3), np.uint8),
                          compose.FrameInfo(t=1.0, words=sc.words_at(1), pages=[0] * 4, held=[60]))
        self.assertEqual(out.shape, (1920, 1080, 3))


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
