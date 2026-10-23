# Troubleshooting

Run `./op1video.py doctor` first: it checks Python packages, the compiler, ffmpeg and its encoders, the SVG
rasterizers and the source bundle. Add `-v` to any render to see compiler commands, timings and the audio gain,
and `--keep` to keep the working folder (script, frame records, raw audio).

## Installation

**`no C compiler found`** — install one (macOS: `xcode-select --install`; Debian/Ubuntu:
`sudo apt install build-essential`) or point `CC` at it: `CC=clang ./op1video.py render eva`.

**`ffmpeg not found on PATH`** — install ffmpeg (macOS `brew install ffmpeg`, Debian/Ubuntu
`sudo apt install ffmpeg`). For `--format webm` it needs libvpx, for `mov` prores_ks; `doctor` lists both.

**`no SVG rasterizer available`** — install librsvg (macOS `brew install librsvg`, Debian/Ubuntu
`sudo apt install librsvg2-2`), or `pip install cairosvg`, or put the `resvg` binary on PATH. Force one with
`--backend`.

**`ModuleNotFoundError: No module named 'lxml'`** (or numpy, PIL, yaml) — activate your virtual environment and
`pip install -r requirements.txt`.

## The source bundle

**Download fails** — op1video fetches from `raw.githubusercontent.com`. Behind a proxy, set `HTTPS_PROXY`. Or
download `hundekraft-3.0.3-source.tar.gz` yourself from
[the repository](https://github.com/Hundekraft/op1-workshop/tree/main/source) and pass `--sdk path/to/it.tar.gz`.

**`checksum mismatch`** — the download was corrupted or the file changed upstream. Run `./op1video.py fetch --force`.
If it persists, check the `.sha256` file published next to the bundle.

**`... is not a hundekraft source bundle`** — `--sdk` must point at the `.tar.gz`, the extracted folder that
contains `ext/kennel/synth_sdk`, or an op1-workshop checkout.

## Building

**`compiling ... failed`** — the message shows the compiler's errors. Usual causes: a plugin from a newer bundle
needs a host function op1video doesn't provide yet (an `undefined reference to host_...`: add it to `sim/host.c`
and `op1_host.h`), or your own plugin uses an SDK path that doesn't exist on the host (see ADDING-PLUGINS.md).
`./op1video.py build <plugin> -v` shows the full commands.

**`expected code not found (the source bundle changed?)`** — a compatibility patch no longer matches; see
ADDING-PLUGINS.md.

**Stale results after editing a plugin** — builds are keyed on the content of every source file, so this should not
happen; `./op1video.py build <plugin> --force` rebuilds anyway, and deleting `.cache/build/` clears all builds.

## Rendering

**`the simulator failed for <plugin>`** — the plugin crashed or rejected the script. Render with `-v --keep` and
run the printed `op1sim` command from the kept folder under a debugger, or shorten the scene to find the moment.

**`note: screen looked up an id that is not in the SVG`** — harmless: the screen code asks for an element its
artwork doesn't have (the device returns NULL too). If the screen then looks wrong, check the SVG file name in
`plugin.json`.

**The screen is black or static** — synth screens come alive while notes play; give the scene `notes`. Effect
screens react to sound passing through: check the `source` level, and that notes fall inside the duration.
Some effects (HAIL, Clouds, In a room) show nothing until their buffer has sound or a capture was pushed.

**Text looks different from the OP–1** — expected for six plugins: the firmware font isn't in the source bundle,
so a substitute is used (HOW-IT-WORKS.md, Fidelity). Installing Inter (`fonts-inter`) gets closest.

**Lines too thick or thin** — adjust `--stroke-scale` (default 0.7; 1.0 is the SVG as authored).

**Audio too loud / quiet** — the final audio is peak-normalised to −1 dBFS. Set `normalize: false` in the scene, or
`--no-normalize`, to hear the plugin's own level, and use the scene's `master` to change it.

**`fps must divide 60`** — the OP–1 screen updates at 60 Hz; use 60, 30, 20, 15, 12 ... so frames land on ticks.

**Slow rendering** — use `--jobs` (default up to 8 processes), a smaller `--size`, or `--layout screen --scale 2`
while iterating. Encoding with `--format mov` is the fastest; `webm` the slowest.

**`ffmpeg stopped` / `ffmpeg failed`** — usually an encoder missing from your ffmpeg build (see `doctor`) or the
disk is full. The message includes ffmpeg's own error.
