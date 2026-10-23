"""Exact-match source patches for plugins whose host build deliberately differs from the device.

A few ports (Maiko's Plate and Warble) compile simplified screens under OP1_HOST for their own unit tests: no
readouts, or a 5-pixel test font instead of the firmware font. These patches switch just those spots back to the
device code path, which op1sim's host text functions then record. Patches are applied to copies of the files in
the build folder; the source bundle is never modified. If a patch's `old` text is not found (a newer bundle), the
build stops with a clear message instead of rendering something different from the device.
"""
from __future__ import annotations

PATCHES: dict[str, dict[str, list[tuple[str, str]]]] = {
    "plate": {
        "plate_screen.c": [
            ("#ifndef OP1_HOST\nstatic uint8_t texts[9][OP1_TEXT_SIZE]",
             "#if 1 /* op1video: device text path */\nstatic uint8_t texts[9][OP1_TEXT_SIZE]"),
            ("#ifndef OP1_HOST\n static const int32_t ident[9]={1024,0,0,0,1024,0,0,0,1024};\n if(!made[n])",
             "#if 1 /* op1video: device text path */\n static const int32_t ident[9]={1024,0,0,0,1024,0,0,0,1024};\n if(!made[n])"),
        ],
    },
    "warble": {
        "warble_screen.c": [
            ("#ifndef OP1_HOST\nstatic uint8_t text_objects[12][OP1_TEXT_SIZE]",
             "#if 1 /* op1video: device text path */\nstatic uint8_t text_objects[12][OP1_TEXT_SIZE]"),
            ("#ifndef OP1_HOST\n unsigned n=text_slot++;if(n>=12)return;",
             "#if 1 /* op1video: device text path */\n unsigned n=text_slot++;if(n>=12)return;"),
        ],
    },
}


class PatchError(RuntimeError):
    pass


def patched_sources(plugin: str) -> dict[str, list[tuple[str, str]]]:
    return PATCHES.get(plugin, {})


def apply(plugin: str, filename: str, text: str) -> str:
    for old, new in PATCHES.get(plugin, {}).get(filename, []):
        if text.count(old) != 1:
            raise PatchError(f"{plugin}/{filename}: expected code not found (the source bundle changed?). "
                             f"Render with a matching bundle version, or update op1video/compat.py.")
        text = text.replace(old, new)
    return text
