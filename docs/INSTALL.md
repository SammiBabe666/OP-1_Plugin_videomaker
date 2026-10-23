# Installing

op1video needs four things:

| | why | check |
|---|---|---|
| **Python 3.9+** with numpy, Pillow, lxml, PyYAML | the pipeline | `python3 --version` |
| **a C compiler** (gcc or clang) | compiles each plugin's own C code for your computer | `cc --version` |
| **ffmpeg** (with libx264) | encodes the videos and audio | `ffmpeg -version` |
| **an SVG rasterizer**: librsvg (recommended), or cairosvg, or resvg | draws each frame | `./op1video.py doctor` |

Plus an internet connection the first time, to download the plugin source bundle from GitHub.

## macOS

```bash
xcode-select --install                    # C compiler (clang), if you don't have it
brew install python ffmpeg librsvg        # https://brew.sh
cd op1-plugin-video
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./op1video.py doctor
```

The librsvg backend finds Homebrew's libraries in `/opt/homebrew/lib` (Apple silicon) and `/usr/local/lib` (Intel).

## Ubuntu / Debian

```bash
sudo apt install python3 python3-venv build-essential ffmpeg librsvg2-2 fonts-inter
cd op1-plugin-video
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./op1video.py doctor
```

`fonts-inter` is optional; it is the font used for the layout text and the stand-in for the OP–1 firmware font.
Without it, Helvetica, Arial or DejaVu Sans are used.

## Fedora

```bash
sudo dnf install python3 gcc ffmpeg librsvg2 rsms-inter-fonts      # ffmpeg from RPM Fusion
```

then the same `venv` / `pip` / `doctor` steps.

## Windows

Use WSL (Windows Subsystem for Linux), which gives you Ubuntu: run `wsl --install` in PowerShell, open the Ubuntu
terminal, and follow the Ubuntu steps above. The rendered files are reachable from Windows at
`\\wsl$\Ubuntu\home\<you>\op1-plugin-video\renders`.

Natively on Windows (without WSL) you need a gcc (e.g. MSYS2's `mingw-w64-ucrt-x86_64-gcc`) on PATH, ffmpeg on
PATH, and `pip install cairosvg` (with the GTK runtime for its cairo DLL) or the `resvg` executable on PATH.
`./op1video.py doctor` tells you what is missing.

## Without a virtual environment

```bash
pip install --user -r requirements.txt
```

or, to get an `op1video` command on your PATH, from the repository folder: `pip install -e .`
(keep the clone: the simulator sources and scenes are read from it).

## The plugin source bundle

`./op1video.py fetch` downloads `hundekraft-3.0.3-source.tar.gz` and its `.sha256` from
[Hundekraft/op1-workshop/source](https://github.com/Hundekraft/op1-workshop/tree/main/source), checks the
checksum, and extracts it to `.cache/sdk-3.0.3/`. Rendering fetches it automatically if you skip this step.

To use a copy you already have — the `.tar.gz`, an extracted folder, or a clone of the op1-workshop repository —
pass `--sdk PATH` to any command, or set it once:

```bash
export OP1VIDEO_SDK=~/src/op1-workshop          # a checkout: the newest bundle in source/ is used
./op1video.py --sdk-version 3.0.2 fetch         # an older release
```

`OP1VIDEO_CACHE` moves the cache folder (default `.cache/` in the repository).

## Checking the install

```
$ ./op1video.py doctor
op1video doctor
  [ok] python: 3.12.4
  [ok] numpy: 2.1.0
  [ok] PIL: 10.4.0
  [ok] lxml: 5.3.0
  [ok] yaml: 6.0.2
  [ok] C compiler: cc (Apple clang version 16.0.0)
  [ok] ffmpeg: /opt/homebrew/bin/ffmpeg
  [ok]   libx264 (mp4)
  [ok]   libvpx-vp9 (webm)
  [ok]   prores_ks (mov)
  [ok] SVG rasterizer: rsvg=ok, cairosvg=no, resvg=no
  [ok] source bundle: .../.cache/sdk-3.0.3/hundekraft-3.0.3-source
all good
```

Then `make test` (or `python -m unittest discover tests`) runs the test suite, including a short end-to-end render.
