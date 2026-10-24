"""Scenes: a YAML description of a short performance, turned into the simulator's per-frame script.

See docs/SCENES.md for the full format. In short:

    plugin: eva
    duration: 10
    knobs: [61, 50, 37, 9]            # start values, percent of each encoder's range
    labels: [Pressure, Freq, Oxygen, Com]
    notes:
      - {at: 0.5, len: 3, chord: [C3, Eb3, G3]}        # OP-1 note names: C3 = MIDI 60
      - {at: 4, every: 0.25, len: 0.2, notes: "C3 G3 C4 G3", until: 8}
    moves:
      - {at: 4, to: 7, knob: green, value: 95}
      - {at: 8, press: orange}

Knob values are percentages unless written as {raw: 0..32767}.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import presets as presets_mod
from .sdk import Plugin

RATE = 44100
KNOB_INDEX = {"blue": 0, "green": 1, "white": 2, "orange": 3, "red": 3,
              "blue2": 5, "green2": 6, "white2": 7, "orange2": 7, "red2": 7,
              "b": 0, "g": 1, "w": 2, "o": 3, "r": 3}
ENCODERS = ["blue", "green", "white", "orange"]
NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
SEMI = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
FPS_OK = (60, 30, 20, 15, 12, 10, 6, 5, 4, 3, 2, 1)


class SceneError(ValueError):
    pass


def note_number(n) -> int:
    if isinstance(n, int):
        return n
    m = NOTE_RE.match(str(n).strip())
    if not m:
        raise SceneError(f"bad note {n!r}: use names like C3, F#2, Bb1 (OP-1 naming: C3 = MIDI 60) or MIDI numbers")
    letter, acc, octave = m.groups()
    v = SEMI[letter.lower()] + (1 if acc == "#" else -1 if acc == "b" else 0)
    return 12 * (int(octave) + 2) + v                 # TE naming, as the OP-1 shows notes: C3 = 60, A3 = 440 Hz


def _q15(v) -> int:
    if isinstance(v, dict) and "raw" in v:
        return max(0, min(32767, int(v["raw"])))
    return max(0, min(32767, round(float(v) * 32767 / 100)))


def _knob(k) -> int:
    if isinstance(k, int):
        if k not in (0, 1, 2, 3, 5, 6, 7):
            raise SceneError(f"knob index {k} out of range (0-3 encoders, 5-7 page-2 words)")
        return k
    key = str(k).strip().lower()
    if key not in KNOB_INDEX:
        raise SceneError(f"unknown knob {k!r}: use blue, green, white, orange (or blue2/green2/white2 for page 2)")
    return KNOB_INDEX[key]


def _ease(name: str, x: float) -> float:
    x = min(1.0, max(0.0, x))
    if name in ("linear", "lin"):
        return x
    if name in ("in",):
        return x * x
    if name in ("out",):
        return 1 - (1 - x) ** 2
    if name == "sine":
        return 0.5 - 0.5 * math.cos(math.pi * x)
    return x * x * (3 - 2 * x)                    # smooth (default)


@dataclass
class Track:
    """Keyframes of one value: (time, value, ease used to arrive at it; 'step' = hold, then jump)."""
    keys: list[tuple[float, float, str]]

    def at(self, t: float) -> float:
        keys = self.keys
        if t <= keys[0][0]:
            return keys[0][1]
        for i in range(len(keys) - 1):
            t0, v0, _ = keys[i]
            t1, v1, e1 = keys[i + 1]
            if t0 <= t < t1:
                if e1 == "step":
                    return v0
                return v0 + (v1 - v0) * _ease(e1, (t - t0) / (t1 - t0) if t1 > t0 else 1.0)
        return keys[-1][1]

    def move(self, at: float, to: float | None, value: float, ease: str) -> None:
        start = self.at(at)
        self.keys = [k for k in self.keys if k[0] < at]
        if to is None or to <= at:
            self.keys.append((at, value, "step"))
        else:
            self.keys += [(at, start, "step"), (to, value, ease)]
        self.keys.sort(key=lambda k: k[0])


@dataclass
class Scene:
    plugin: str
    title: str = ""
    subtitle: str = ""
    duration: float = 8.0
    fps: int = 30
    bpm: int = 120
    labels: list[str] = field(default_factory=lambda: [e.capitalize() for e in ENCODERS])
    labels2: list[str] = field(default_factory=list)    # names for page-2 (pushed) encoders
    start: list[int] = field(default_factory=list)        # 8 words (Q15)
    envelope: tuple[int, int, int, int] = (10, 300, 80, 500)   # ms, ms, %, ms
    master: int = 50
    source: str = "pluck"
    source_level: int = 70
    source_file: str | None = None
    sample_file: str | None = None
    tuner: bool = False
    normalize: float | None = -1.0                         # peak target in dBFS; None leaves the level as played
    tracks: dict[int, Track] = field(default_factory=dict)
    toggles: dict[int, list[float]] = field(default_factory=dict)
    pages: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    shift: list[tuple[float, float]] = field(default_factory=list)
    tilt: list[Track] = field(default_factory=list)
    notes: list[tuple[float, float, int, int]] = field(default_factory=list)   # start s, end s, note, vel
    env_events: list[tuple[float, tuple[int, int, int, int]]] = field(default_factory=list)  # envelope from t on
    captions: list[dict] = field(default_factory=list)    # {at, to, title, text, index, count}
    output: dict = field(default_factory=dict)
    base_dir: Path = Path(".")

    # ----------------------------------------------------------------------------------- per-frame values
    @property
    def n_frames(self) -> int:
        return max(1, round(self.duration * self.fps))

    def frame_time(self, f: int) -> float:
        return (f + 1) / self.fps

    def words_at(self, t: float) -> list[int]:
        w = list(self.start)
        for k, tr in self.tracks.items():
            w[k] = int(round(tr.at(t)))
        return w

    def pages_at(self, t: float) -> list[int]:
        out = list(self.pages)
        for k, times in self.toggles.items():
            n = sum(1 for x in times if x <= t)
            out[k] ^= n & 1
        return out

    def shift_at(self, t: float) -> int:
        return int(any(a <= t < b for a, b in self.shift))

    def tilt_at(self, t: float) -> list[int]:
        """Accelerometer reading (ADXL345 as the firmware copies it: 1 g = 16384; X: left side up +,
        Y: front edge up -, Z: up +) for the scene's tilt in degrees: side (right side up +), front (front edge up +)."""
        if not self.tilt:
            return [0, 0, 16384]
        side, front = (math.radians(tr.at(t)) for tr in self.tilt)
        g = 16384
        return [round(-g * math.sin(side)), round(-g * math.sin(front)),
                round(g * math.cos(side) * math.cos(front))]

    def held_at(self, t: float) -> list[int]:
        return sorted({n for s, e, n, _ in self.notes if s <= t < e})

    def caption_at(self, t: float) -> dict | None:
        live = [c for c in self.captions if c["at"] <= t < c["to"]]
        return live[-1] if live else None

    # ----------------------------------------------------------------------------------- script for op1sim
    def script(self, source_raw: Path | None = None, sample_raw: Path | None = None) -> str:
        a, d, s, r = self.envelope
        lines = [
            "# op1sim script generated by op1video (format: docs/HOW-IT-WORKS.md)",
            f"fps {self.fps}",
            f"frames {self.n_frames}",
            f"envelope {int(a)} {int(d)} {round(s * 32767 / 100)} {int(r)}",
            f"master {round(self.master * 32767 / 100)}",
            f"bpm {int(self.bpm)}",
            f"source {self.source} {round(self.source_level * 32767 / 100)}",
            f"tuner {int(self.tuner)}",
        ]
        if source_raw:
            lines.append(f"source_file {source_raw}")
        if sample_raw:
            lines.append(f"sample_file {sample_raw}")
        for f in range(self.n_frames):
            t = self.frame_time(f)
            w, pg, sh, ac = self.words_at(t), self.pages_at(t), self.shift_at(t), self.tilt_at(t)
            lines.append("k %d %s %s %d %s" % (f, " ".join(map(str, w)), " ".join(map(str, pg)), sh,
                                              " ".join(map(str, ac))))
        for t, (a, d, s, r) in self.env_events:
            lines.append(f"env {round(t * RATE)} {int(a)} {int(d)} {round(s * 32767 / 100)} {int(r)}")
        for start, end, note, vel in self.notes:
            lines.append(f"on {round(start * RATE)} {note} {vel}")
            lines.append(f"off {round(end * RATE)} {note}")
        lines.append("end")
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------- loading
def _notes(spec: list, duration: float) -> list[tuple[float, float, int, int]]:
    out = []
    for n in spec or []:
        if not isinstance(n, dict):
            raise SceneError(f"each entry under notes: must be a mapping, got {n!r}")
        vel = int(n.get("vel", 100))
        length = float(n.get("len", 0.5))
        at = float(n.get("at", 0))
        if "every" in n:                                    # a repeating sequence
            seq = n.get("notes", [])
            seq = seq.split() if isinstance(seq, str) else list(seq)
            if not seq:
                raise SceneError("a sequence (every:) needs notes:")
            step = float(n["every"])
            until = float(n.get("until", duration))
            i, t = 0, at
            while t < until - 1e-9:
                item = seq[i % len(seq)]
                if str(item) not in ("-", "."):            # "-" or "." is a rest
                    group = item if isinstance(item, list) else str(item).split("+")
                    for x in group:
                        out.append((t, min(t + length, until), note_number(x), vel))
                i += 1
                t = at + i * step
            continue
        group = n.get("chord") or [n.get("note")]
        if group == [None]:
            raise SceneError(f"note entry needs note:, chord: or every:+notes: ({n})")
        for x in group:
            out.append((at, at + length, note_number(x), vel))
    return out


def from_dict(d: dict, plugin: Plugin, base_dir: Path = Path(".")) -> Scene:
    sc = Scene(plugin=plugin.name, base_dir=base_dir)
    sc.title = str(d.get("title", plugin.display.upper()))
    sc.subtitle = str(d.get("subtitle", ""))
    sc.duration = float(d.get("duration", 8))
    sc.fps = int(d.get("fps", 30))
    if sc.fps not in FPS_OK:
        raise SceneError(f"fps must divide 60 (the OP-1's screen rate): one of {FPS_OK}")
    sc.bpm = int(d.get("bpm", 120))
    sc.labels2 = [str(x) if x else "" for x in (d.get("labels2") or [])][:4]
    labels = d.get("labels")
    if labels:
        sc.labels = [str(x) for x in labels][:4] + sc.labels[len(labels):]

    start = list(plugin.defaults[:4]) + [plugin.selector] + list(plugin.page2_defaults[:3])
    for i, v in enumerate((d.get("knobs") or [])[:4]):
        if v is not None:
            start[i] = _q15(v)
    for i, v in enumerate((d.get("page2") or [])[:3]):
        if v is not None:
            start[5 + i] = _q15(v)
    sc.start = start
    sc.tracks = {}

    env = d.get("envelope") or {}
    sc.envelope = (int(env.get("attack", 10)), int(env.get("decay", 300)),
                   int(env.get("sustain", 80)), int(env.get("release", 500)))
    sc.master = int(d.get("master", 50))
    src = d.get("source") or {}
    if isinstance(src, str):
        src = {"type": src}
    sc.source = str(src.get("type", "pluck"))
    if sc.source not in ("saw", "pluck", "pad", "sine", "square", "noise", "drums", "file"):
        raise SceneError(f"unknown source type {sc.source!r}")
    sc.source_level = int(src.get("level", 70))
    if src.get("file"):
        sc.source_file = str(src["file"])
        sc.source = "file"
    if d.get("sample"):
        sc.sample_file = str(d["sample"])
    sc.tuner = bool(d.get("tuner", False))
    norm = d.get("normalize", -1.0)
    sc.normalize = None if norm in (False, None) else (-1.0 if norm is True else float(norm))
    sc.pages = [int(bool(x)) for x in (d.get("pages") or [0, 0, 0, 0])][:4] + [0] * 4
    sc.pages = sc.pages[:4]

    moves = list(d.get("moves") or [])
    for m in moves:
        if not isinstance(m, dict):
            raise SceneError(f"each entry under moves: must be a mapping, got {m!r}")
    entries = _load_presets(sc, d.get("presets") or [], plugin)
    if entries and entries[0][0] <= 0:                    # a preset at 0 is also the start state
        for k in PRESET_WORDS:
            sc.start[k] = max(0, min(32767, entries[0][2].knobs[k]))
        sc.envelope = entries[0][2].envelope
    # presets become moves, merged in time order with the scene's own (a move at the same time wins)
    # the encoders glide (if glide: is set); page-2 words (often discrete choices) always switch at once
    preset_moves = []
    for at, e, pr in entries:
        g = float(e.get("glide", 0))
        preset_moves.append({"at": at, **({"to": at + g} if g > 0 else {}), "_words": {k: pr.knobs[k] for k in (0, 1, 2, 3)}})
        preset_moves.append({"at": at, "_words": {k: pr.knobs[k] for k in (5, 6, 7)}})
    moves = preset_moves + moves
    for m in sorted(moves, key=lambda m: float(m.get("at", 0))):     # later moves override earlier ones
        at = float(m.get("at", 0))
        to = float(m["to"]) if "to" in m else None
        ease = str(m.get("ease", "smooth"))
        if "press" in m:
            presses = m["press"] if isinstance(m["press"], list) else [m["press"]]
            for p in presses:
                k = _knob(p)
                if k > 3:
                    raise SceneError("press: takes an encoder name (blue, green, white, orange)")
                sc.toggles.setdefault(k, []).append(at)
            continue
        if "shift" in m:
            sc.shift.append((at, to if to is not None else at + float(m.get("len", 1.0))))
            continue
        if "_words" in m:                                 # from a preset
            for k, v in m["_words"].items():
                tr = sc.tracks.setdefault(k, Track([(0.0, float(start[k]), "step")]))
                tr.move(at, to, float(max(0, min(32767, v))), ease)
            continue
        if "tilt" in m:                                   # [side, front] in degrees
            tv = m["tilt"]
            if not isinstance(tv, list) or not 1 <= len(tv) <= 2:
                raise SceneError("tilt: takes [side, front] in degrees, e.g. tilt: [0, 20]")
            if not sc.tilt:
                sc.tilt = [Track([(0.0, 0.0, "step")]), Track([(0.0, 0.0, "step")])]
            for i in range(2):
                if i < len(tv) and tv[i] is not None:
                    v = float(tv[i])
                    if abs(v) > 90:
                        raise SceneError("tilt angles are degrees between -90 and 90")
                    sc.tilt[i].move(at, to, v, ease)
            continue
        targets: list[tuple[int, object]] = []
        if "knob" in m:
            targets.append((_knob(m["knob"]), m["value"]))
        if "knobs" in m:
            for i, v in enumerate(m["knobs"][:4]):
                if v is not None:
                    targets.append((i, v))
        if not targets:
            raise SceneError(f"move needs knob:+value:, knobs:, press:, shift: or tilt: ({m})")
        for k, v in targets:
            tr = sc.tracks.setdefault(k, Track([(0.0, float(start[k]), "step")]))
            tr.move(at, to, float(_q15(v)), ease)

    sc.notes = _notes(d.get("notes"), sc.duration)
    _apply_presets(sc, entries)
    for c in d.get("captions") or []:
        if not isinstance(c, dict) or "at" not in c:
            raise SceneError(f"each caption needs at: ({c!r})")
        sc.captions.append({"at": float(c["at"]), "to": float(c.get("to", sc.duration)),
                            "title": str(c.get("title", "")), "text": str(c.get("text", "")),
                            "index": c.get("index"), "count": c.get("count")})
    sc.captions.sort(key=lambda c: c["at"])
    sc.output = dict(d.get("output") or {})
    return sc


PRESET_WORDS = (0, 1, 2, 3, 5, 6, 7)                      # word 4 is the engine selector: the plugin's own


def _load_presets(sc: Scene, spec: list, plugin: Plugin) -> list:
    """presets: [{at: 4, file: "glass veil.aif", glide: 0.5, caption: "...", text: "..."}]"""
    entries = []
    for e in spec:
        if isinstance(e, str):
            e = {"file": e}
        if not isinstance(e, dict) or "file" not in e:
            raise SceneError(f"each preset needs file: ({e!r})")
        try:
            pr = presets_mod.load((sc.base_dir / str(e["file"])).expanduser())
        except presets_mod.PresetError as err:
            raise SceneError(str(err))
        if pr.type and pr.type != plugin.display:
            raise SceneError(f"{pr.path.name} is a preset for {pr.type!r}, not {plugin.display!r}")
        entries.append((float(e.get("at", 0)), e, pr))
    entries.sort(key=lambda x: x[0])
    return entries


def _apply_presets(sc: Scene, entries: list) -> None:
    """Each preset's envelope and octave apply to notes starting from its time until the next preset; its
    caption shows over the same span."""
    for i, (at, e, pr) in enumerate(entries):
        end = entries[i + 1][0] if i + 1 < len(entries) else sc.duration
        sc.env_events.append((at, pr.envelope))
        if pr.octave:
            sc.notes = [(s, t, n + 12 * pr.octave, v) if at <= s < end else (s, t, n, v)
                        for s, t, n, v in sc.notes]
        if e.get("caption", True) is not False:
            title = e["caption"] if isinstance(e.get("caption"), str) else pr.name
            sc.captions.append({"at": at, "to": end, "title": str(title), "text": str(e.get("text", "")),
                                "index": i + 1, "count": len(entries)})
    sc.notes = [(s, t, max(0, min(127, n)), v) for s, t, n, v in sc.notes]


def load(path: Path, plugin: Plugin) -> Scene:
    d = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(d, dict):
        raise SceneError(f"{path}: a scene is a YAML mapping")
    if d.get("plugin") and d["plugin"] != plugin.name:
        raise SceneError(f"{path} is a scene for {d['plugin']}, not {plugin.name}")
    return from_dict(d, plugin, Path(path).resolve().parent)


def auto(plugin: Plugin, duration: float = 12.0) -> dict:
    """A default scene for plugins without one: play something, then sweep each encoder in turn."""
    seg = duration / 5
    moves = []
    for i, k in enumerate(ENCODERS):
        a = seg * (i + 0.5)
        moves += [{"at": round(a, 2), "to": round(a + seg * 0.45, 2), "knob": k, "value": 100},
                  {"at": round(a + seg * 0.5, 2), "to": round(a + seg * 0.95, 2), "knob": k, "value": 0}]
    moves.append({"at": round(seg * 4.5, 2), "to": round(duration - 0.3, 2),
                  "knobs": [round(v * 100 / 32767) for v in plugin.defaults[:4]]})
    if plugin.kind == "synth":
        notes = [{"at": 0.2, "every": 1.6, "len": 1.4, "notes": ["C2+G2+E3", "A1+E2+C3", "F1+C2+A2", "G1+D2+B2"],
                  "until": duration - 0.5}]
        envelope = {"attack": 15, "decay": 400, "sustain": 75, "release": 600}
    else:
        notes = [{"at": 0.1, "every": 0.2, "len": 0.15, "notes": "C3 G3 Eb4 G3 C4 G3 Bb3 G3", "until": duration - 1}]
        envelope = {"attack": 2, "decay": 180, "sustain": 30, "release": 200}
    return {"plugin": plugin.name, "title": plugin.display.upper(), "duration": duration,
            "envelope": envelope, "notes": notes, "moves": moves}
