"""op1video command line. Run `python -m op1video --help` (or ./op1video --help)."""
from __future__ import annotations

import argparse
import importlib
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from . import build as build_mod
from . import raster, render as render_mod, scene as scene_mod, sdk as sdk_mod

ROOT = Path(__file__).resolve().parent.parent


def _size(s: str):
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, e.g. 1920x1080")


def _root(args) -> Path:
    return sdk_mod.resolve(args.sdk, args.sdk_version)


def _plugins(args, root: Path) -> dict:
    return sdk_mod.discover(root, extra_dirs=args.plugin_dir)


def _get(args, root: Path, name: str):
    ps = _plugins(args, root)
    if name not in ps:
        close = [n for n in ps if name.lower() in n.lower()]
        hint = f" Did you mean {', '.join(close)}?" if close else " Run `op1video list` to see them."
        raise SystemExit(f"error: no renderable plugin called {name!r}.{hint}")
    return ps[name]


def _options(args) -> render_mod.Options:
    w, h = args.size if args.size else (None, None)
    return render_mod.Options(
        layout=args.layout, fmt=args.format, width=w, height=h, scale=args.scale, fps=args.fps,
        duration=args.duration, audio=not args.no_audio, backend=args.backend, jobs=args.jobs,
        stroke_scale=args.stroke_scale, crf=args.crf, font=args.font, keys=args.keys, keep=args.keep,
        no_normalize=args.no_normalize, verbose=args.verbose)


def _ext(fmt: str) -> str:
    return "" if fmt == "png" else "." + fmt


# ------------------------------------------------------------------------------------------------ commands
def cmd_fetch(args):
    root = sdk_mod.fetch(args.sdk_version, force=args.force) if not args.sdk else sdk_mod.resolve(args.sdk)
    ps = sdk_mod.discover(root)
    print(f"{len(ps)} renderable plugins in {root}")


def cmd_list(args):
    root = _root(args)
    ps = sdk_mod.discover(root, with_screen_only=not args.all, extra_dirs=args.plugin_dir)
    print(f"{'plugin':<12} {'kind':<6} {'screen':<7} {'scene':<6} author")
    for n, p in ps.items():
        sc = "yes" if (render_mod.SCENES / f"{n}.yaml").exists() else "auto"
        print(f"{n:<12} {p.kind:<6} {'yes' if p.svg else 'no':<7} {sc:<6} {p.author[:50]}")


def cmd_build(args):
    root = _root(args)
    ps = _plugins(args, root)
    names = list(ps) if args.all or not args.plugins else args.plugins
    failed = []
    for n in names:
        p = _get(args, root, n)
        try:
            exe = build_mod.build(p, root, verbose=args.verbose, force=args.force)
            print(f"ok    {n:<12} {exe}")
        except build_mod.BuildError as e:
            failed.append(n)
            print(f"FAIL  {n:<12} {e}")
    if failed:
        raise SystemExit(1)


def cmd_render(args):
    root = _root(args)
    p = _get(args, root, args.plugin)
    opt = _options(args)
    out = Path(args.output) if args.output else ROOT / "renders" / f"{p.name}{_ext(opt.fmt)}"
    t0 = time.time()
    print(f"rendering {p.name} -> {out}")
    render_mod.render(p, root, out, Path(args.scene) if args.scene else None, opt)
    print(f"done in {time.time() - t0:.1f}s: {out}")


def cmd_render_all(args):
    root = _root(args)
    ps = _plugins(args, root)
    only = set(args.only.split(",")) if args.only else None
    skip = set(args.skip.split(",")) if args.skip else set()
    opt = _options(args)
    out_dir = Path(args.out_dir)
    ok, failed = [], []
    for n, p in ps.items():
        if (only and n not in only) or n in skip:
            continue
        out = out_dir / f"{n}{_ext(opt.fmt)}"
        t0 = time.time()
        try:
            render_mod.render(p, root, out, None, render_mod.Options(**vars(opt)))
            ok.append(n)
            print(f"ok    {n:<12} {time.time() - t0:5.1f}s  {out}")
        except Exception as e:                                     # keep going; report at the end
            failed.append(n)
            print(f"FAIL  {n:<12} {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            if args.verbose:
                import traceback
                traceback.print_exc()
    print(f"\n{len(ok)} rendered, {len(failed)} failed" + (f": {', '.join(failed)}" if failed else ""))
    if failed:
        raise SystemExit(1)


def cmd_still(args):
    root = _root(args)
    p = _get(args, root, args.plugin)
    opt = _options(args)
    out = Path(args.output) if args.output else ROOT / "renders" / f"{p.name}-{args.at:g}s.png"
    render_mod.still(p, root, out, args.at, Path(args.scene) if args.scene else None, opt,
                     Path(args.svg) if args.svg else None)
    print(out)


def cmd_scene(args):
    root = _root(args)
    p = _get(args, root, args.plugin)
    d = scene_mod.auto(p, args.duration or 12.0)
    text = (f"# starter scene for {p.name} ({p.kind}); see docs/SCENES.md\n"
            f"# plugin.json defaults (percent): {[round(v * 100 / 32767) for v in p.defaults]}\n"
            + yaml.safe_dump(d, sort_keys=False, default_flow_style=None, width=110))
    if args.output:
        Path(args.output).write_text(text)
        print(args.output)
    else:
        print(text, end="")


def cmd_doctor(args):
    good = True

    def line(ok, what, detail=""):
        nonlocal good
        good &= bool(ok)
        print(f"  [{'ok' if ok else '!!'}] {what}{(': ' + detail) if detail else ''}")

    print("op1video doctor")
    line(sys.version_info >= (3, 9), "python", platform.python_version())
    for mod in ("numpy", "PIL", "lxml", "yaml"):
        try:
            m = importlib.import_module(mod)
            line(True, mod, getattr(m, "__version__", ""))
        except ImportError:
            line(False, mod, "missing: pip install -r requirements.txt")
    try:
        cc = build_mod.compiler()
        v = subprocess.run([cc, "--version"], capture_output=True, text=True).stdout.splitlines()[:1]
        line(True, "C compiler", f"{cc} ({v[0] if v else '?'})")
    except build_mod.BuildError as e:
        line(False, "C compiler", str(e))
    ff = shutil.which("ffmpeg")
    if ff:
        enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        line(True, "ffmpeg", ff)
        for codec, fmt in (("libx264", "mp4"), ("libvpx-vp9", "webm"), ("prores_ks", "mov")):
            ok = codec in enc
            print(f"  [{'ok' if ok else '--'}]   {codec} ({fmt}){'' if ok else ' not available'}")
    else:
        line(False, "ffmpeg", "not found on PATH")
    avail = raster.available()
    line(any(v == "ok" for v in avail.values()), "SVG rasterizer",
         ", ".join(f"{k}={'ok' if v == 'ok' else 'no'}" for k, v in avail.items()))
    try:
        root = sdk_mod.resolve(args.sdk, args.sdk_version, download=False)
        line(True, "source bundle", str(root))
    except sdk_mod.SdkError as e:
        print(f"  [--] source bundle: {e}")
    print("all good" if good else "fix the items marked !! (docs/INSTALL.md)")
    if not good:
        raise SystemExit(1)


# ------------------------------------------------------------------------------------------------ parser
def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="op1video", description="Render videos of hundekraft OP-1 plugin screens, "
                                 "animated by the plugins' own code, with their audio.")
    ap.add_argument("--sdk", help="source bundle: extracted folder, .tar.gz, or an op1-workshop checkout "
                                  "(default: download into .cache)")
    ap.add_argument("--sdk-version", default=sdk_mod.DEFAULT_VERSION, help="bundle version (default %(default)s)")
    ap.add_argument("--plugin-dir", action="append", default=[], metavar="DIR",
                    help="your own plugin folder (with plugin.json), or a folder of them; repeatable")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("fetch", help="download and verify the plugin source bundle")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("list", help="list renderable plugins")
    s.add_argument("--all", action="store_true", help="include synth/FX plugins without a screen")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("build", help="compile plugin simulators (render does this automatically)")
    s.add_argument("plugins", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_build)

    def render_opts(s):
        s.add_argument("--layout", default="card", choices=["card", "screen", "square"])
        s.add_argument("--format", default="mp4", choices=["mp4", "webm", "mov", "gif", "png"])
        s.add_argument("--size", type=_size, help="output size WxH (card 1920x1080, square 1080x1080 by default)")
        s.add_argument("--scale", type=int, default=4, help="screen layout: pixels per OLED pixel (default 4)")
        s.add_argument("--fps", type=int, help="frames per second, a divisor of 60 (default: scene, 30)")
        s.add_argument("--duration", type=float, help="override the scene's length in seconds")
        s.add_argument("--no-audio", action="store_true", help="leave the plugin's audio out")
        s.add_argument("--no-normalize", action="store_true", help="keep the audio level exactly as rendered")
        s.add_argument("--backend", default="auto", choices=["auto", *raster.BACKENDS])
        s.add_argument("--jobs", type=int, default=0, help="rasterising processes (default: up to 8 cores)")
        s.add_argument("--stroke-scale", type=float, default=render_mod.svgframe.DEFAULT_STROKE_SCALE,
                       help="stroke weight relative to the SVG (default %(default)s matches the device)")
        s.add_argument("--crf", type=int, default=18, help="video quality, lower is better (default 18)")
        s.add_argument("--font", help="TTF/OTF file for layout text")
        k = s.add_mutually_exclusive_group()
        k.add_argument("--keys", dest="keys", action="store_true", default=None, help="always show the keyboard")
        k.add_argument("--no-keys", dest="keys", action="store_false", help="never show the keyboard")
        s.add_argument("--keep", action="store_true", help="keep the working folder (script, frames, audio)")
        s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("render", help="render one plugin")
    s.add_argument("plugin")
    s.add_argument("--scene", help="scene YAML (default: scenes/<plugin>.yaml, else an automatic demo)")
    s.add_argument("-o", "--output", help="output file (default renders/<plugin>.<format>)")
    render_opts(s)
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("render-all", help="render every plugin with its scene")
    s.add_argument("--out-dir", default=str(ROOT / "renders"))
    s.add_argument("--only", help="comma-separated plugins")
    s.add_argument("--skip", help="comma-separated plugins")
    render_opts(s)
    s.set_defaults(fn=cmd_render_all)

    s = sub.add_parser("still", help="render a single frame to PNG")
    s.add_argument("plugin")
    s.add_argument("--at", type=float, default=2.0, help="time in seconds (default 2)")
    s.add_argument("--scene")
    s.add_argument("-o", "--output")
    s.add_argument("--svg", help="also write the frame's SVG here")
    render_opts(s)
    s.set_defaults(fn=cmd_still)

    s = sub.add_parser("scene", help="print a starter scene YAML for a plugin")
    s.add_argument("plugin")
    s.add_argument("--duration", type=float)
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_scene)

    s = sub.add_parser("doctor", help="check that everything needed is installed")
    s.set_defaults(fn=cmd_doctor)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        args.fn(args)
    except (sdk_mod.SdkError, build_mod.BuildError, render_mod.SimError, scene_mod.SceneError,
            raster.RasterError, render_mod.encode.EncodeError) as e:
        raise SystemExit(f"error: {e}")
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
