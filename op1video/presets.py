"""OP-1 synth presets (.aif): read the patch JSON the OP-1 stores in the AIFF's APPL chunk.

A preset looks like:
  {"type": "vapora", "name": "glass veil", "octave": 0,
   "knobs": [12000, 20000, 24000, 15000, 21248, 31130, 6000, 31598],      # encoders, selector, page-2 words
   "adsr": [6000, 12000, 28000, 15000, 2048, 5568, 4000, 4000],            # T2 attack, decay, sustain, release
   "fx_type": "spring", "fx_active": true, "fx_params": [...],             # T3 (stock OP-1 effect)
   "lfo_type": "value", "lfo_active": true, "lfo_params": [...]}           # T4 (stock OP-1 LFO)

op1video uses `knobs`, `adsr` and `octave`. The stock T3 effects and T4 LFOs are part of the OP-1 firmware, not of
the plugin, so they are not rendered; `describe()` reports when a preset uses them.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

# OP-1 envelope words: attack, decay and release 64..16320, sustain 0..32767 (SDK tools/op1r_presets.py).
# The firmware's time curve is not documented. This curve is fitted through the attack times plugin authors
# pair with their saved words (e.g. VAPORA's preview_envelope_ms: 64 -> 5 ms, 7000 -> 650 ms, 9000 -> 1.5 s,
# 11500 -> 3.6 s, 14000 -> 5.2 s) and extended to about 10 s at the top. It is an approximation.
ENV_CURVE = [(0, 1), (64, 5), (2000, 40), (4000, 180), (7000, 650), (9000, 1500), (11000, 3400),
             (12500, 3930), (14000, 5200), (16320, 10000)]


def env_ms(word: int) -> int:
    w = max(0, min(16320, int(word)))
    for (w0, t0), (w1, t1) in zip(ENV_CURVE, ENV_CURVE[1:]):
        if w <= w1:
            return round(t0 + (t1 - t0) * (w - w0) / (w1 - w0))
    return ENV_CURVE[-1][1]


class PresetError(ValueError):
    pass


@dataclass
class Preset:
    path: Path
    name: str
    type: str
    knobs: list[int]
    adsr: list[int]
    octave: int = 0
    fx: str | None = None
    lfo: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def envelope(self) -> tuple[int, int, int, int]:
        """(attack ms, decay ms, sustain %, release ms) for the simulator's envelope."""
        a, d, s, r = (self.adsr + [64, 64, 32767, 64])[:4]
        return env_ms(a), env_ms(d), round(max(0, min(32767, s)) * 100 / 32767), env_ms(r)

    def describe(self) -> str:
        extra = [f"T3 {self.fx}" if self.fx else "", f"T4 {self.lfo}" if self.lfo else ""]
        extra = [e for e in extra if e]
        return f"{self.name} (octave {self.octave:+d})" + (f"; not rendered: {', '.join(extra)}" if extra else "")


def _patch_json(data: bytes) -> dict:
    """The JSON patch from an OP-1 AIFF/AIFC: chunk APPL with signature 'op-1'; falls back to the first {...}."""
    if data[:4] == b"FORM" and data[8:12] in (b"AIFF", b"AIFC"):
        pos = 12
        while pos + 8 <= len(data):
            cid, size = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
            body = data[pos + 8:pos + 8 + size]
            if cid == b"APPL" and body[:4] == b"op-1":
                text = body[4:].split(b"\0", 1)[0].strip()
                return json.loads(text.decode("utf-8"))
            pos += 8 + size + (size & 1)
    a, b = data.find(b"{"), data.rfind(b"}")
    if a < 0 or b < a:
        raise PresetError("no OP-1 patch data found")
    return json.loads(data[a:b + 1].decode("utf-8"))


def load(path: Path) -> Preset:
    path = Path(path)
    try:
        d = _patch_json(path.read_bytes())
    except FileNotFoundError:
        raise PresetError(f"preset not found: {path}")
    except (ValueError, UnicodeDecodeError) as e:
        raise PresetError(f"{path.name}: not an OP-1 preset ({e})")
    knobs = [int(v) for v in d.get("knobs", [])][:8]
    if len(knobs) < 4:
        raise PresetError(f"{path.name}: preset has no knob values")
    knobs += [0] * (8 - len(knobs))
    return Preset(path=path, name=str(d.get("name") or path.stem), type=str(d.get("type", "")), knobs=knobs,
                  adsr=[int(v) for v in d.get("adsr", [])][:4], octave=int(d.get("octave", 0)),
                  fx=d.get("fx_type") if d.get("fx_active") else None,
                  lfo=d.get("lfo_type") if d.get("lfo_active") else None, raw=d)
