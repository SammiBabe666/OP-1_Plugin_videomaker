# How it works

```
 scenes/eva.yaml ──► scene.py ──► script.txt ─┐
                                              ▼
 source bundle ─► build.py ─► op1sim (plugin's own C + sim/) ──► frames.jsonl + audio.s16
 (plugin.json,                                                        │              │
  C sources, SVG)                                                     ▼              ▼
                           svgframe.py: plugin SVG + per-frame state ─► raster.py ─► compose.py ─► encode.py ─► eva.mp4
                                                                                                    ▲
                                                                              audio.wav (normalised)┘
```

## 1. The plugins are real code

The hundekraft workshop builds OP–1 firmware from *kennel*, a plugin runtime; each synth, effect and tool is a
folder in the source bundle (`ext/kennel/synth_sdk/plugins/<name>/`) with a `plugin.json`, C sources and, for the
ones with a screen, an SVG plus init/update callbacks:

```c
typedef struct {
    void (*init)(void *scr);           /* after SVG load: look up nodes */
    void (*update)(void *scr, int dt); /* every frame while visible */
} op1_screen_t;
```

A screen animates its SVG through a handful of firmware calls: `op1_find_node`, `op1_node_set_transform` (a Q10
matrix), `op1_node_set_visible`, `op1_node_line_rgba` / `fill_rgba`, `op1_screen_draw`, `op1_raster_line` and the
firmware text calls. The audio side is `note_on` / `render` / `note_off` on 128-sample blocks for synths,
`init` / `render` on 64-sample blocks for effects, and `reset` / `process` for live-input engines like Amp. All of
it is integer C, written to also compile for the host when `OP1_HOST` is defined; the SDK's own tests do this.

## 2. The host shim (`sim/include/harness/op1_host.h`, `sim/host.c`)

With `OP1_HOST` set, `op1_plugin.h` includes `harness/op1_host.h` and expects it to replace every firmware address.
The bundle doesn't ship that header, so op1video provides one, using the names the SDK's tests use
(`host_find_node`, `host_pitch_inc`, `host_fx_knobs` ...). The host versions:

* **Nodes**: `host_find_node` returns a handle for ids that exist in the plugin's SVG and NULL for others, as the
  device does (the list comes from `svgframe.py`, with each node's stroke/fill so colour writes can be detected).
  Matrices, visibility and colour writes are kept per node.
* **Drawing**: `op1_screen_draw` and every `op1_raster_line` and text draw are recorded in order for the frame.
* **Audio state**: the sine table, per-sample pitch increments, voice memory and velocities, the stock envelope,
  knob words per slot and FX position, FX scratch buffers and meters, the accelerometer (Aether), the beat clock.

## 3. The driver (`sim/driver.c`)

`op1sim` is linked from the plugin's sources, `host.c` and `driver.c`. Each plugin source is compiled in its own
translation unit, as the firmware build does, through a generated wrapper that also exports that unit's beat clock
(the SDK keeps one static clock per unit on the host), so tempo-synced effects follow the scene's bpm.

It reads the script and runs device timing:

* **Audio**: 44.1 kHz. Synths render 6 voices in 128-sample blocks; each voice's output is multiplied by a linear
  ADSR (standing in for the OP–1's T2 envelope; also exposed as `OP1_VOICE_ENV`) and mixed. Effects and Amp get a
  dry signal in 64-sample blocks: a small built-in synth played by the scene's notes, a drum loop, or a file. The
  FX meter is a peak with decay, like the firmware's. A soft limiter guards the output.
* **Screen**: `update(scr, dt)` on every 60 Hz GUI tick with `dt` of 16/17 ms, as on the device — screens advance
  per tick, so this keeps their speed right at any video frame rate. Every `60 / fps`-th tick is written out.
* **Controls**: knob words, page-2/latch flags, shift and tilt are applied per frame from the script.
* **Clock**: `host_cycles` stands in for the Blackfin's 400 MHz `CYCLES` register and advances with each GUI tick,
  for screens that time their animation with it.
* **Envelopes**: each voice keeps the envelope that was current when its note started; `env` events (from scene
  presets) change it for later notes.

Builds are cached in `.cache/build/<plugin>-<hash>/`; the hash covers the compiler, flags, the simulator files,
compatibility patches and every source file of the plugin. Flags: `-std=gnu11 -O2 -fwrapv -fno-strict-aliasing`
(`-fwrapv` because the DSP relies on two's-complement wrap-around, as on the Blackfin) plus the plugin's own
`cflags` from `plugin.json`.

### Script format (`script.txt`)

Plain text, one record per line, `#` comments:

```
fps 30
frames 480
envelope <attack ms> <decay ms> <sustain Q15> <release ms>
master <Q15>
bpm 120
source <pluck|saw|pad|sine|square|noise|drums|file> <level Q15>
tuner 0
source_file /path/source.s16            (optional: mono s16le 44.1 kHz)
sample_file /path/sample.s16            (optional: granular's sampler slot)
k <frame> <w0..w7> <page0..page3> <shift> <ax> <ay> <az>
env <sample> <attack ms> <decay ms> <sustain Q15> <release ms>    (envelope for notes from then on)
on <sample> <midi note> <velocity>
off <sample> <midi note>
end
```

`w0..w3` are the encoders, `w4` the engine selector (0x5300 + order), `w5..w7` the page-2 words, all 0..32767.
`ax ay az` is the accelerometer (1 g = 16384). There is one `k` line per frame.

### Frame records (`frames.jsonl`)

One JSON object per captured frame:

```json
{"f": 12, "t": 433.33,
 "nodes": {"socks": {"m": [1012,158,0,-158,1012,0,-11469,-14700,1024]}, "water": {"v": 0}, "bar0": {"s": "698effff"}},
 "ops": [["svg"], ["l", x0, y0, x1, y1, width, "rrggbbaa"], ["t", x, y, size, align, "rrggbbaa", "TEXT"]]}
```

`nodes` lists only nodes that differ from the SVG as loaded: `m` the Q10 matrix (row vectors, so
`matrix(a b c d tx ty)` in SVG terms, all divided by 1024), `v: 0` hidden, `s`/`fl` stroke and fill. `ops` are the
frame's immediate drawing in order; `["svg"]` is where the SVG itself was drawn (if a screen never says, the SVG is
drawn first). Line coordinates and widths are Q10 pixels; text `x` is Q10, `y` and `size` pixels.

## 4. Frames (`svgframe.py`, `raster.py`, `compose.py`)

For each record the plugin's SVG (forced to the 320x160 user space) gets a black background, the recorded
matrices, visibility and colours, and the recorded lines and text before/after the artwork. librsvg renders it
straight to the layout's OLED size (vector, so it stays sharp at 4x), then the layout pastes it into the frame
and draws its own text, encoder dials and keyboard. Frames are rasterised in parallel processes and streamed to
ffmpeg as raw RGB.

## 5. Fidelity

Every plugin was rendered at its default settings and compared side by side with the native emulator captures
in the workshop manual (`manual/img/*-native.png`, `*-play.png`). Artwork, animation state and the plugins' own
drawing match; differences come from settings or notes that differ from the capture. What was calibrated:

* **Stroke weight**: device strokes measured ~0.67 of the SVG `stroke-width` (EVA: 1.0 px native vs 1.5 px
  authored). Default `--stroke-scale 0.7`.
* **Raster line caps are butt**: Plate's host code draws filled rectangles as single lines whose width is the
  rectangle's height, which only reproduces a rectangle with butt caps. Round caps turned them into discs.
* **Firmware text**: `y` is the top of the em, the baseline is `y + size`, glyphs are about `0.8 * size + 3` px tall
  (measured at size 14 and 40 on Warble's capture), capitals only. The TE font isn't in the bundle, so a light,
  condensed sans (Inter ExtraLight at 84% width when installed) is set to those metrics. Six plugins use it:
  Aether, Crush, Father, Plate, SID, Warble. Stroke-font text (Oxbow, Palme, Mixtur, In a room, Amp ...) is drawn
  by the plugin itself and is exact.
* **Host-only code paths**: Crush, Plate and Warble compile simplified screens under `OP1_HOST` for their unit
  tests. `sim/compat/crush.c` and `op1video/compat.py` route them back to the device path (exact-match patches on
  copies; the bundle is untouched, and a changed bundle stops the build rather than drawing something else).

Not modelled: the OP–1's own LFO (T4), its master effects and mixer, the tape, and anything a plugin reads from
firmware state the host doesn't provide (they see defaults). Audio uses the plugin's DSP exactly, with the simple
ADSR above in place of the firmware envelope.
