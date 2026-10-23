"""Locate, download and read the hundekraft source bundle (kennel SDK) that contains the plugins.

The bundle is published with the workshop at
https://github.com/Hundekraft/op1-workshop/tree/main/source as hundekraft-<version>-source.tar.gz plus a
.sha256 file. It is GPL-3.0-or-later; this tool downloads it on demand and never redistributes it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_VERSION = "3.0.3"
RAW_BASE = "https://raw.githubusercontent.com/Hundekraft/op1-workshop/main/source"
ROOT = Path(__file__).resolve().parent.parent


def cache_dir() -> Path:
    d = Path(os.environ.get("OP1VIDEO_CACHE", ROOT / ".cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


class SdkError(RuntimeError):
    pass


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "op1-plugin-video"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(tar_path: Path, dest: Path) -> Path:
    """Extract safely (no absolute paths, no links out of dest) and return the bundle's top directory."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path) as tf:
        try:
            tf.extractall(dest, filter="data")          # Python >= 3.12 (and patched 3.8+)
        except TypeError:                                # very old Pythons: check members by hand
            for m in tf.getmembers():
                p = (dest / m.name).resolve()
                if not str(p).startswith(str(dest.resolve())) or m.issym() or m.islnk():
                    raise SdkError(f"refusing unsafe archive member {m.name}")
            tf.extractall(dest)
    tops = [p for p in dest.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else dest


def fetch(version: str = DEFAULT_VERSION, force: bool = False) -> Path:
    """Download and verify the source bundle for `version`; returns the extracted bundle root."""
    d = cache_dir() / f"sdk-{version}"
    marker = d / ".ok"
    if marker.exists() and not force:
        return Path(marker.read_text().strip())
    name = f"hundekraft-{version}-source.tar.gz"
    tar_path = cache_dir() / name
    sha_path = cache_dir() / (name + ".sha256")
    print(f"downloading {name} ...")
    _download(f"{RAW_BASE}/{name}.sha256", sha_path)
    if force or not tar_path.exists():
        _download(f"{RAW_BASE}/{name}", tar_path)
    expected = sha_path.read_text().split()[0].strip().lower()
    actual = _sha256(tar_path)
    if expected != actual:
        tar_path.unlink(missing_ok=True)
        raise SdkError(f"checksum mismatch for {name}: expected {expected}, got {actual}")
    if d.exists():
        shutil.rmtree(d)
    root = _extract(tar_path, d)
    marker.write_text(str(root))
    print(f"source bundle verified (sha256 {actual[:12]}...) and extracted to {root}")
    return root


def resolve(sdk: str | None = None, version: str = DEFAULT_VERSION, download: bool = True) -> Path:
    """Find the bundle root from an explicit path (extracted dir, .tar.gz, or an op1-workshop checkout),
    the OP1VIDEO_SDK environment variable, the cache, or by downloading it."""
    sdk = sdk or os.environ.get("OP1VIDEO_SDK")
    if sdk:
        p = Path(sdk).expanduser().resolve()
        if p.is_file() and p.name.endswith(".tar.gz"):
            d = cache_dir() / ("local-" + p.name.replace(".tar.gz", ""))
            marker = d / ".ok"
            if not marker.exists():
                root = _extract(p, d)
                marker.write_text(str(root))
            return Path(marker.read_text().strip())
        if (p / "source").is_dir() and not (p / "ext").is_dir():       # an op1-workshop checkout
            tars = sorted((p / "source").glob(f"hundekraft-{version}-source.tar.gz")) or \
                sorted((p / "source").glob("hundekraft-*-source.tar.gz"))
            if not tars:
                raise SdkError(f"no source bundle in {p / 'source'}")
            return resolve(str(tars[-1]), version, download)
        if (p / "ext" / "kennel" / "synth_sdk").is_dir():
            return p
        if (p / "synth_sdk").is_dir() and (p.parent.parent / "ext").is_dir():
            return p.parent.parent
        raise SdkError(f"{p} is not a hundekraft source bundle (expected ext/kennel/synth_sdk inside)")
    marker = cache_dir() / f"sdk-{version}" / ".ok"
    if marker.exists():
        return Path(marker.read_text().strip())
    if not download:
        raise SdkError("source bundle not found; run `op1video fetch` first")
    return fetch(version)


def synth_sdk(root: Path) -> Path:
    return root / "ext" / "kennel" / "synth_sdk"


KINDS = ("synth", "fx", "input")


@dataclass
class Plugin:
    name: str                         # folder name: the id used on the command line and for scenes
    display: str                      # plugin.json "name"
    dir: Path
    kind: str                         # synth | fx | input
    symbol: str
    sources: list[str]
    defaults: list[int]
    page2_defaults: list[int] = field(default_factory=lambda: [0, 0, 0])
    order: int = 0
    svg: Path | None = None
    screen_symbol: str | None = None
    cflags: list[str] = field(default_factory=list)
    include_dirs: list[str] = field(default_factory=list)
    uses_sample: bool = False
    stereo: bool = False
    author: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def selector(self) -> int:        # params[4]: OP1_ENGINE_MAGIC + engine order (files use 32..63)
        return 0x5300 + (self.order if self.order else 32)


def load_plugin(folder: Path) -> Plugin | None:
    pj = folder / "plugin.json"
    if not pj.exists():
        return None
    d = json.loads(pj.read_text())
    kind = d.get("kind")
    if kind == "synth" and d.get("input_engine"):
        kind = "input"
    if kind not in KINDS:
        return None
    screen = d.get("screen") or {}
    svg = folder / screen["svg"] if screen.get("svg") else None
    defaults = list(d.get("defaults") or [16384] * 4)[:4]
    defaults += [16384] * (4 - len(defaults))
    p2 = list(d.get("page2_defaults") or [0, 0, 0])[:3]
    p2 += [0] * (3 - len(p2))
    return Plugin(
        name=folder.name, display=d.get("name", folder.name), dir=folder, kind=kind, symbol=d["symbol"], sources=list(d["sources"]),
        defaults=defaults, page2_defaults=p2, order=int(d.get("order") or 0),
        svg=svg if svg and svg.exists() else None, screen_symbol=screen.get("symbol"),
        cflags=list(d.get("cflags") or []), include_dirs=list(d.get("include_dirs") or []),
        uses_sample=bool(d.get("uses_sample")), stereo=bool(d.get("stereo")),
        author=d.get("author", ""), meta=d,
    )


def discover(root: Path, with_screen_only: bool = True, extra_dirs: list | None = None) -> dict[str, Plugin]:
    """Plugins in the bundle, plus your own: each extra dir is a plugin folder (with plugin.json) or a folder of
    them. Your own plugins override bundle plugins of the same folder name."""
    folders = sorted(p for p in (synth_sdk(root) / "plugins").iterdir() if p.is_dir())
    for d in extra_dirs or []:
        d = Path(d).expanduser().resolve()
        if not d.is_dir():
            raise SdkError(f"--plugin-dir {d} is not a folder")
        folders += [d] if (d / "plugin.json").exists() else sorted(p for p in d.iterdir() if (p / "plugin.json").exists())
    plugins = {}
    for folder in folders:
        p = load_plugin(folder)
        if p and (p.svg or not with_screen_only):
            plugins[p.name] = p
    return plugins
