# op1-plugin-video

Render videos of the [hundekraft OP–1 workshop](https://hundekraft.github.io/op1-workshop/) plugins — the
animated synth and effect screens of the original Teenage Engineering OP–1 — **driven by each plugin's own C code
and with its real audio**.

Nothing is redrawn or faked. For every plugin, op1video compiles the plugin's actual DSP and screen code from the
workshop's GPL source bundle on your computer, plays a short scripted performance through it (notes, encoder
turns and pushes, even tilt for Aether), records exactly what the screen code draws on each 60 Hz GUI tick, renders
the plugin's own SVG artwork with those changes, and muxes the frames with the sound the plugin produced.

```
./op1video.py render eva          # -> renders/eva.mp4  (1920x1080, 30 fps, AAC audio)
./op1video.py render-all          # every plugin, using the demo scenes in scenes/
```

28 plugins are supported: every synth, effect and live-input engine in the bundle that has a screen —
aether, amp, arc, clouds, crush, elg, eva, father, fmbell, granular, hail, in a room, mbira, mixtur, oxbow,
palme, pew, plate, reverb, sid, snowglobe, stutter, supersaw, taffy, tape, warble, washer and wavetable.

## Quick start

You need Python 3.9+, a C compiler, ffmpeg and librsvg (step-by-step per OS in [docs/INSTALL.md](docs/INSTALL.md)).

```bash
git clone https://github.com/SammiBabe666/OP-1_Plugin_videomaker.git op1-plugin-video && cd op1-plugin-video
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

./op1video.py doctor        # checks compiler, ffmpeg, rasterizer
./op1video.py fetch         # downloads + verifies the hundekraft 3.0.3 source bundle (~9 MB) into .cache/
./op1video.py list          # the renderable plugins
./op1video.py render eva    # renders/eva.mp4
```

`./op1video.py` and `python -m op1video` are the same command; after `pip install -e .` it is also on your PATH
as `op1video`.

## Common recipes

```bash
# a 1080p "card" video: title, the OLED, the four encoders with live values, a keyboard strip
./op1video.py render washer

# just the screen, sized like the workshop's card images, no audio, as WebM for the web
./op1video.py render washer --layout screen --size 960x480 --format webm --no-audio

# a square clip for social posts, and a looping GIF
./op1video.py render snowglobe --layout square
./op1video.py render taffy --layout screen --scale 2 --format gif --duration 6

# a vertical (9:16) video of your own plugin stepping through its presets
./op1video.py --plugin-dir ~/dev/vapora/plugin render vapora --scene examples/vapora-presets.yaml --layout vertical

# your own performance (see docs/SCENES.md), or a starter scene to edit
./op1video.py scene hail -o my-hail.yaml
./op1video.py render hail --scene my-hail.yaml

# put your own audio through an effect: in the scene, source: {file: guitar.wav}

# check a scene quickly: one frame as PNG (and its SVG)
./op1video.py still eva --at 7.5 --svg eva.svg

# everything, as ProRes for editing
./op1video.py render-all --format mov --out-dir renders/prores
```

All options: [docs/USAGE.md](docs/USAGE.md).

## Documentation

| | |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | Installing on macOS, Linux and Windows (WSL), and checking it with `doctor` |
| [docs/USAGE.md](docs/USAGE.md) | Every command and option, layouts, formats, batch rendering |
| [docs/SCENES.md](docs/SCENES.md) | Writing scenes: notes, chords, sequences, knob moves, presses, page 2, tilt, audio input, presets, captions |
| [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) | Architecture, the host shim, timing, file formats, how fidelity was checked |
| [docs/ADDING-PLUGINS.md](docs/ADDING-PLUGINS.md) | New bundle versions, your own `.knl` plugin, compatibility patches |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Errors and fixes |

## Repository layout

```
op1-plugin-video/
├── op1video.py              launcher (same as python -m op1video)
├── op1video/                the Python package
│   ├── cli.py               commands: fetch, list, build, render, render-all, still, scene, doctor
│   ├── sdk.py               download, verify and read the hundekraft source bundle; plugin.json discovery
│   ├── build.py             compiles a plugin's sources + the simulator into .cache/build/<plugin>-<hash>/op1sim
│   ├── compat.py            exact-match source patches for the few plugins whose host build differs
│   ├── scene.py             YAML scenes -> the simulator's per-frame script
│   ├── render.py            build -> simulate -> rasterise (parallel) -> lay out -> encode
│   ├── svgframe.py          applies recorded node state and drawing to the plugin SVG for each frame
│   ├── raster.py            SVG rasterizers: librsvg (ctypes), cairosvg, resvg
│   ├── compose.py           layouts: screen, card, square, vertical
│   ├── presets.py           reads OP-1 preset files (.aif): knobs, envelope, octave
│   └── encode.py            ffmpeg: mp4, webm, mov, gif, png sequence; WAV and normalisation
├── sim/                     the C host simulator
│   ├── include/harness/op1_host.h   host stand-ins for every firmware address in the plugin API
│   ├── host.c               node table, drawing recorder, per-frame JSON
│   ├── driver.c             voices, ADSR, FX/input sources, beat clock, 60 Hz screen ticks
│   └── compat/crush.c       glue for Crush's own preview hooks
├── scenes/                  one demo scene per plugin (from the manual's "Try this" settings)
├── examples/                annotated example scenes showing every feature
├── tests/                   unit and end-to-end tests (python -m unittest)
├── docs/                    the documentation above
├── .github/workflows/       CI: renders every plugin and uploads the videos
├── Makefile                 shortcuts: make setup / fetch / render-all / cards / test
├── requirements.txt, pyproject.toml, LICENSE
└── .cache/, renders/        created on use (git-ignored)
```

## How faithful is it?

Each plugin's screen was compared with the workshop manual's native emulator captures at the same settings:
the artwork, its animation state and the plugins' own drawing (meters, waveforms, readouts) line up. Two things
are approximations, by necessity: the OP–1's firmware font isn't in the source bundle (six plugins use it for
readouts; a light condensed sans is set to the measured metrics instead), and stroke weight follows a
calibration (`--stroke-scale`, default 0.7) measured against the captures. Audio is the plugins' own integer DSP
at 44.1 kHz, with a simple ADSR standing in for the OP–1's envelope page and no master effects.
Details in [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

## Credits and license

The plugins, their artwork and the kennel SDK are by Hundekraft and the contributors credited in the
[workshop manual](https://hundekraft.github.io/op1-workshop/manual.html#credits) — op1r by pcppcp, Musica Obscura
by ultralazr, Maiko Pruett's designs, OberVave by zvenson, cRSID by Hermit, Mutable Instruments DSP by Émilie
Gillet, artwork by DAN76/Rackes and others. op1video downloads their GPL-3.0 source bundle at run time and does
not redistribute it. Independent project; not affiliated with Teenage Engineering or Hundekraft.

op1video itself is GPL-3.0-or-later (see [LICENSE](LICENSE)), matching the code it builds and links with.
Videos you render show other people's artwork and sound: credit the plugin authors when you share them.
