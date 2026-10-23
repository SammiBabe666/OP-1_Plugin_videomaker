# Usage

```
./op1video.py [--sdk PATH] [--sdk-version 3.0.3] <command> [options]
```

`--sdk` points at the plugin source bundle (a `.tar.gz`, an extracted folder, or an op1-workshop checkout);
without it the bundle is downloaded into `.cache/` on first use. `OP1VIDEO_SDK` sets the same thing.

## Commands

| command | what it does |
|---|---|
| `fetch [--force]` | download and verify the source bundle |
| `list [--all]` | renderable plugins, their kind, and whether `scenes/` has a scene for them (`--all`: include plugins without a screen) |
| `build [PLUGIN ...] [--all] [--force] [-v]` | compile the simulators ahead of time (render does it when needed; results are cached) |
| `render PLUGIN [--scene FILE] [-o OUT] [options]` | render one plugin |
| `render-all [--out-dir DIR] [--only a,b] [--skip a,b] [options]` | render every plugin with its scene; keeps going past failures and reports them at the end |
| `still PLUGIN [--at SECONDS] [--svg FILE] [-o OUT.png] [options]` | one frame as a PNG (and its SVG) |
| `scene PLUGIN [-o FILE] [--duration S]` | print a starter scene to edit |
| `doctor` | check the installation |

Which scene is used: `--scene FILE` if given, else `scenes/<plugin>.yaml`, else an automatic demo that plays
chords (synths) or an arpeggio (effects) and sweeps each encoder in turn.

## Render options

Used by `render`, `render-all` and `still`.

| option | default | |
|---|---|---|
| `--layout card\|screen\|square` | `card` | see Layouts below (a scene's `output: {layout: ...}` also sets it) |
| `--format mp4\|webm\|mov\|gif\|png` | `mp4` | see Formats below |
| `--size WxH` | per layout | output size; card 1920x1080, square 1080x1080, screen 320x160 x `--scale` |
| `--scale N` | `4` | screen layout: output pixels per OLED pixel (4 = 1280x640) |
| `--fps N` | scene, else 30 | 60, 30, 20, 15, 12 ... (a divisor of 60: the OP–1 screen updates at 60 Hz) |
| `--duration S` | scene | override the scene's length |
| `--no-audio` | | video only |
| `--no-normalize` | | keep the audio level as rendered (default: peak normalised to −1 dBFS, at most +18 dB) |
| `--backend auto\|rsvg\|cairosvg\|resvg` | `auto` | SVG rasterizer |
| `--jobs N` | up to 8 | parallel rasterising processes (1 = single process) |
| `--stroke-scale F` | `0.7` | stroke weight relative to the SVG; 0.7 matches the device captures, 1.0 = as authored |
| `--crf N` | `18` | quality for mp4/webm (lower = better, bigger) |
| `--font FILE` | Inter / Helvetica / Arial / DejaVu | font for the layout's text |
| `--keys` / `--no-keys` | auto | the keyboard strip in card/square layouts (auto: shown when the scene plays notes) |
| `--keep` | | keep the working folder (script, frame records, raw audio) and print its path |
| `-v`, `--verbose` | | show compiler commands, timings and normalisation gain |

## Layouts

* **card** (16:9, 1920x1080): plugin name and subtitle, the OLED in a bezel, the four encoders with their labels
  and live values (page-2 values when an encoder is pushed to page 2), and a keyboard strip that lights the notes
  being played.
* **square** (1080x1080): the same, stacked, for social posts.
* **screen**: only the OLED, at `--scale` or `--size`. Use it to embed in pages, e.g. the workshop's cards
  (`--size 960x480` or `--size 400x200`).

## Formats

| format | contents | use |
|---|---|---|
| `mp4` | H.264 (yuv420p, faststart) + AAC 192 kb/s | anywhere |
| `webm` | VP9 + Opus | smaller web video |
| `mov` | ProRes 422 HQ + PCM | editing in Final Cut, Premiere, Resolve |
| `gif` | palette-optimised GIF, no audio, at most 30 fps | READMEs, chats |
| `png` | a folder of `frame_00000.png` ... plus `audio.wav` | your own compositing |

## Recipes

```bash
# videos for the workshop cards: OLED only, no sound, small WebM
./op1video.py render-all --layout screen --size 960x480 --format webm --no-audio --out-dir renders/cards

# 60 fps, as smooth as the device
./op1video.py render pew --fps 60

# a vertical-ish post: square, 8 seconds
./op1video.py render elg --layout square --duration 8

# preview a scene while writing it: a small fast render and a still
./op1video.py render mbira --scene my.yaml --layout screen --scale 2 --jobs 8
./op1video.py still mbira --scene my.yaml --at 4.2

# debug: keep the simulator's script and frame records
./op1video.py render sid --keep -v
```

`make` shortcuts for the same: `make render-all`, `make cards`, `make gifs`, `make test` (see the Makefile).

## Speed

A 12-second 1080p card video takes about 10 seconds on a laptop: simulating the plugin takes well under a
second; rasterising and encoding the frames is the rest, spread over `--jobs` processes. The first render of a
plugin also compiles it (a few seconds); after that the build is cached in `.cache/build/` until the plugin's
sources or the simulator change.
