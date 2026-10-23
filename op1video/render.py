"""Render one plugin scene to a video: build -> simulate -> rasterise each frame -> lay out -> encode."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from PIL import Image

from . import build as build_mod
from . import compose, encode, raster, scene as scene_mod, svgframe
from .sdk import Plugin

ROOT = Path(__file__).resolve().parent.parent
SCENES = ROOT / "scenes"


@dataclass
class Options:
    layout: str = "card"
    fmt: str = "mp4"
    width: int | None = None
    height: int | None = None
    scale: int = 4                       # OLED pixels per screen pixel (screen layout; card uses its own size)
    fps: int | None = None
    duration: float | None = None
    audio: bool = True
    backend: str = "auto"
    jobs: int = 0                        # 0 = all cores
    stroke_scale: float = svgframe.DEFAULT_STROKE_SCALE
    crf: int = 18
    font: str | None = None
    keys: bool | None = None
    keep: bool = False
    no_normalize: bool = False
    verbose: bool = False


class SimError(RuntimeError):
    pass


def scene_for(plugin: Plugin, scene_path: Path | None) -> scene_mod.Scene:
    if scene_path:
        return scene_mod.load(scene_path, plugin)
    default = SCENES / f"{plugin.name}.yaml"
    if default.exists():
        return scene_mod.load(default, plugin)
    return scene_mod.from_dict(scene_mod.auto(plugin), plugin)


def simulate(plugin: Plugin, sdk_root: Path, sc: scene_mod.Scene, work: Path, opt: Options):
    """Run op1sim; returns (SvgScreen, frames.jsonl path, wav path)."""
    exe = build_mod.build(plugin, sdk_root, verbose=opt.verbose)
    svg = plugin.svg
    if sc.tuner and plugin.kind == "input":          # the T2 tuner is its own screen, without the T1 artwork
        svg = work / "tuner.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="160" viewBox="0 0 320 160"/>')
    screen = svgframe.SvgScreen(svg, opt.stroke_scale)
    ids = work / "ids.txt"
    screen.write_ids(ids)
    src_raw = smp_raw = None
    if sc.source_file:
        src_raw = work / "source.s16"
        encode.decode_audio((sc.base_dir / sc.source_file).resolve(), src_raw)
    if sc.sample_file:
        smp_raw = work / "sample.s16"
        encode.decode_audio((sc.base_dir / sc.sample_file).resolve(), smp_raw)
    script = work / "script.txt"
    script.write_text(sc.script(src_raw, smp_raw))
    frames, audio = work / "frames.jsonl", work / "audio.s16"
    t0 = time.time()
    cmd = [str(exe), str(script), str(ids), str(frames), str(audio)]
    if opt.verbose:
        print("  $ " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SimError(f"the simulator failed for {plugin.name} (exit {r.returncode}):\n{r.stderr.strip()[:800]}")
    if opt.verbose:
        if r.stderr.strip():
            print("  " + r.stderr.strip().replace("\n", "\n  "))
        print(f"  simulated {sc.n_frames} frames in {time.time() - t0:.1f}s")
    wav = work / "audio.wav"
    peak = None if opt.no_normalize else sc.normalize
    g = encode.write_wav(audio, wav, peak_db=peak)
    if opt.verbose and peak is not None:
        print(f"  audio normalised to {peak:g} dBFS peak ({g:+.1f} dB)")
    return screen, frames, wav


# ---------------------------------------------------------------------------------- parallel rasterising
_W = {}


def _init_worker(svg_path: str, stroke_scale: float, backend: str, size: tuple[int, int]):
    _W["screen"] = svgframe.SvgScreen(Path(svg_path), stroke_scale)
    _W["backend"] = raster.get_backend(backend)
    _W["size"] = size


def _raster_one(rec: dict) -> np.ndarray:
    w, h = _W["size"]
    return _W["backend"].render(_W["screen"].frame(rec), w, h)


def _frames_iter(screen, frames_path: Path, backend: str, size, jobs: int, stroke_scale: float):
    recs = svgframe.read_frames(frames_path)
    if jobs == 1:
        be = raster.get_backend(backend)
        for rec in recs:
            yield rec, be.render(screen.frame(rec), *size)
        return
    recs = list(recs)
    ctx = get_context("spawn" if os.name == "nt" else "fork")
    with ctx.Pool(jobs, initializer=_init_worker, initargs=(str(screen.path), stroke_scale, backend, size)) as pool:
        for rec, img in zip(recs, pool.imap(_raster_one, recs, chunksize=4)):
            yield rec, img


def _info(sc: scene_mod.Scene, rec: dict) -> compose.FrameInfo:
    t = rec["t"] / 1000.0
    return compose.FrameInfo(t=t, words=sc.words_at(t), pages=sc.pages_at(t), held=sc.held_at(t))


def _apply_overrides(sc: scene_mod.Scene, opt: Options) -> None:
    if opt.fps:
        if opt.fps not in scene_mod.FPS_OK:
            raise scene_mod.SceneError(f"--fps must divide 60: one of {scene_mod.FPS_OK}")
        sc.fps = opt.fps
    if opt.duration:
        sc.duration = opt.duration
    out = sc.output or {}
    if out.get("layout") and opt.layout == "card":
        opt.layout = out["layout"]


def render(plugin: Plugin, sdk_root: Path, out: Path, scene_path: Path | None = None,
           opt: Options | None = None) -> Path:
    opt = opt or Options()
    if not plugin.svg:
        raise SimError(f"{plugin.name} has no screen SVG; nothing to render")
    sc = scene_for(plugin, scene_path)
    _apply_overrides(sc, opt)
    layout = compose.make(opt.layout, sc, plugin, opt.width, opt.height, opt.scale, opt.font, opt.keys)
    oled_size = layout.screen_px
    jobs = opt.jobs or max(1, min(8, os.cpu_count() or 1))
    work = Path(tempfile.mkdtemp(prefix=f"op1video-{plugin.name}-"))
    t0 = time.time()
    try:
        screen, frames, wav = simulate(plugin, sdk_root, sc, work, opt)
        writer = encode.Writer(out, opt.fmt, layout.size, sc.fps, wav if opt.audio else None, crf=opt.crf)
        for rec, oled in _frames_iter(screen, frames, opt.backend, oled_size, jobs, opt.stroke_scale):
            writer.write(layout.compose(oled, _info(sc, rec)))
        writer.close()
        if opt.verbose:
            print(f"  {writer.n} frames, {layout.size[0]}x{layout.size[1]}, {time.time() - t0:.1f}s total")
    finally:
        if opt.keep:
            print(f"  kept working files in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return out


def still(plugin: Plugin, sdk_root: Path, out: Path, at: float, scene_path: Path | None = None,
          opt: Options | None = None, svg_out: Path | None = None) -> Path:
    """One frame as a PNG (and optionally its SVG): handy for checking a scene or making a thumbnail."""
    opt = opt or Options()
    sc = scene_for(plugin, scene_path)
    _apply_overrides(sc, opt)
    sc.duration = max(at + 1.0 / sc.fps, min(sc.duration, at + 1.0))
    layout = compose.make(opt.layout, sc, plugin, opt.width, opt.height, opt.scale, opt.font, opt.keys)
    work = Path(tempfile.mkdtemp(prefix=f"op1video-{plugin.name}-"))
    try:
        screen, frames, _ = simulate(plugin, sdk_root, sc, work, opt)
        want = min(sc.n_frames - 1, max(0, round(at * sc.fps) - 1))
        rec = next(r for i, r in enumerate(svgframe.read_frames(frames)) if i == want)
        doc = screen.frame(rec)
        if svg_out:
            svg_out.write_bytes(doc)
        oled = raster.get_backend(opt.backend).render(doc, *layout.screen_px)
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(layout.compose(oled, _info(sc, rec))).save(out)
    finally:
        if not opt.keep:
            shutil.rmtree(work, ignore_errors=True)
    return out
