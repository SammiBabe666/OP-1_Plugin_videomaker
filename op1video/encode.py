"""Encode frames (and the plugin's audio) with ffmpeg.

Formats:
  mp4   H.264 + AAC, yuv420p: plays everywhere (web, phones, social)
  webm  VP9 + Opus: smaller files for the web
  mov   ProRes 422 HQ + PCM: for editing in Final Cut / Premiere / Resolve
  gif   palette-optimised animated GIF, no audio
  png   a numbered PNG sequence in a folder (plus audio.wav)
"""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image

FORMATS = ("mp4", "webm", "mov", "gif", "png")


class EncodeError(RuntimeError):
    pass


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise EncodeError("ffmpeg not found on PATH (see docs/INSTALL.md)")
    return exe


def write_wav(raw_s16: Path, wav: Path, rate: int = 44100, peak_db: float | None = -1.0,
              max_gain_db: float = 18.0) -> float:
    """Wrap the simulator's raw PCM as a WAV, optionally normalising its peak to `peak_db` dBFS.
    Returns the gain applied in dB."""
    a = np.fromfile(raw_s16, dtype="<i2")
    gain_db = 0.0
    if peak_db is not None and a.size:
        peak = int(np.abs(a.astype(np.int32)).max())
        if peak > 0:
            gain_db = min(max_gain_db, peak_db - 20 * np.log10(peak / 32767))
            a = np.clip(np.round(a * 10 ** (gain_db / 20)), -32768, 32767).astype("<i2")
    data = a.tobytes()
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)
    return float(gain_db)


def decode_audio(src: Path, out_raw: Path, rate: int = 44100) -> None:
    """Any audio file -> mono s16le at 44.1 kHz (input for effects, or a granular sample)."""
    r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(rate),
                        "-f", "s16le", str(out_raw)], capture_output=True, text=True)
    if r.returncode:
        raise EncodeError(f"could not decode {src}: {r.stderr.strip()[:300]}")


class Writer:
    def __init__(self, out: Path, fmt: str, size: tuple[int, int], fps: int, audio: Path | None,
                 crf: int = 18, gif_fps: int | None = None, loop: bool = True):
        if fmt not in FORMATS:
            raise EncodeError(f"unknown format {fmt}; choose from {', '.join(FORMATS)}")
        self.out, self.fmt, self.size, self.fps, self.audio = out, fmt, size, fps, audio
        self.n = 0
        self.proc = None
        out.parent.mkdir(parents=True, exist_ok=True)
        w, h = size
        if fmt == "png":
            out.mkdir(parents=True, exist_ok=True)
            return
        cmd = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
               "-r", str(fps), "-i", "-"]
        if audio and fmt != "gif":
            cmd += ["-i", str(audio)]
        if fmt == "mp4":
            cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-tune", "animation"]
            if audio:
                cmd += ["-c:a", "aac", "-b:a", "192k"]
        elif fmt == "webm":
            cmd += ["-c:v", "libvpx-vp9", "-crf", str(crf + 12), "-b:v", "0", "-pix_fmt", "yuv420p", "-row-mt", "1"]
            if audio:
                cmd += ["-c:a", "libopus", "-b:a", "160k"]
        elif fmt == "mov":
            cmd += ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
            if audio:
                cmd += ["-c:a", "pcm_s16le"]
        elif fmt == "gif":
            gf = gif_fps or min(fps, 30)
            cmd += ["-vf", f"fps={gf},split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
                           f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                    "-loop", "0" if loop else "-1"]
        if audio and fmt != "gif":
            cmd += ["-shortest"]
        cmd += [str(out)]
        self.cmd = cmd
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, rgb: np.ndarray) -> None:
        if self.fmt == "png":
            Image.fromarray(rgb).save(self.out / f"frame_{self.n:05d}.png")
        else:
            try:
                self.proc.stdin.write(np.ascontiguousarray(rgb, dtype=np.uint8).tobytes())
            except BrokenPipeError:
                err = self.proc.stderr.read().decode(errors="replace")
                raise EncodeError("ffmpeg stopped: " + err.strip()[:500])
        self.n += 1

    def close(self) -> None:
        if self.fmt == "png":
            if self.audio:
                shutil.copy(self.audio, self.out / "audio.wav")
            return
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode(errors="replace")
        self.proc.stderr.close()
        if self.proc.wait():
            raise EncodeError("ffmpeg failed: " + err.strip()[:800])
