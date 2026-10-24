# Adding plugins

## New workshop releases

op1video reads plugins from the bundle's `plugin.json` files, so new synths and effects in a newer release are
picked up without code changes:

```bash
./op1video.py --sdk-version 3.1 fetch
./op1video.py --sdk-version 3.1 list
./op1video.py --sdk-version 3.1 render <new-plugin>
```

Change `DEFAULT_VERSION` in `op1video/sdk.py` to make it the default. A new plugin without a scene in `scenes/`
gets the automatic demo; `./op1video.py scene <plugin> -o scenes/<plugin>.yaml` gives you a file to refine.

If a release changes code that a compatibility patch targets, the build stops with
`<plugin>/<file>: expected code not found` instead of rendering something that differs from the device. Look at
the new code and update the patch in `op1video/compat.py`, or remove it if the plugin's host path now matches.

## Your own plugin

The workshop manual's "Make your own plugin" chapter and the bundle's `PLUGIN_GUIDE.md` describe the SDK; start
from `ext/kennel/synth_sdk/template/synth` or `template/fx`. For a video, the plugin needs a screen: an SVG and an
`op1_screen_t`, declared in `plugin.json`:

```json
{
  "name": "mysynth",
  "kind": "synth",
  "symbol": "ENGINE_mysynth",
  "sources": ["mysynth.c"],
  "defaults": [4000, 12000, 6000, 24000],
  "screen": {"svg": "mysynth.svg", "symbol": "SCREEN_mysynth"}
}
```

Render it straight from your working folder, no Blackfin toolchain needed:

```bash
./op1video.py --plugin-dir ~/dev/mysynth list
./op1video.py --plugin-dir ~/dev/mysynth render mysynth --scene ~/dev/mysynth/demo.yaml
./op1video.py --plugin-dir ~/dev/mysynth still mysynth --at 1 --svg frame.svg   # inspect a frame
```

`--plugin-dir` takes a plugin folder or a folder of plugin folders and can be repeated; a folder with the same
name as a bundle plugin overrides it. Include SDK headers by name (`#include "op1_plugin.h"`,
`"op1_synth.h"`, `"seq/seq_text.h"`): the SDK folder is on the include path. Relative paths like
`"../../op1_synth.h"` only work inside the bundle's `plugins/` folder.

This is also a quick way to see your screen at 60 Hz with real audio while you work on it: the simulator compiles in
a few seconds and is cached until a source file changes.

### Code that only works on the device

A plugin may read firmware memory or Blackfin registers directly, e.g. a key-state byte at a raw address or the
`CYCLES` counter through inline assembly. That crashes or doesn't compile on the host. Either keep such code
under `#ifndef OP1_HOST` with a host fallback (`host_shift`, `host_cycles` and the other stand-ins in
`sim/include/harness/op1_host.h`), or add an exact-match patch in `op1video/compat.py`. VAPORA is the example: its
screen reads the Shift byte at `0x01DD7F78` and `CYCLES`, and two patches point them at `host_shift` and
`host_cycles`.

### Host-mode rules your plugin should follow

These come from the SDK and are what make a plugin renderable on the host:

* Use only the API in `op1_plugin.h` / `op1_synth.h` (no raw firmware addresses outside `#ifndef OP1_HOST`).
* Check `op1_find_node` results: ids missing from the SVG return NULL here, as on the device.
* Read knobs with `op1_synth_knobs_live` / `op1_fx_knobs_live`, the sine table through `OP1_SINE_TABLE`.
* If your screen has a simplified `#ifdef OP1_HOST` path for unit tests, op1video will render that simplified path.

## Compatibility glue

Two mechanisms exist for plugins whose host build differs from the device:

* `sim/compat/<plugin>.c` is compiled into that plugin's simulator. Use it when a plugin declares its own
  preview hooks (Crush declares `crush_host_text`, `crush_host_line` ... and expects a harness to provide them).
* `op1video/compat.py` holds exact-match text patches applied to copies of a plugin's sources in the build folder,
  for when a screen's `OP1_HOST` path deliberately draws something different (Plate's and Warble's readouts).
  Keep them minimal: switch a branch back to the device path, nothing more.

Both are included in the build cache key, so edits trigger a rebuild.

## Checking a plugin against the device

The workshop manual's images (`manual/img/` in the op1-workshop repository) are captures from the kennel
emulator. To compare, render a still at the same settings and look at them side by side:

```bash
./op1video.py still crush --at 1.5 --layout screen --scale 3 -o ours.png
```

with a scene that sets the knobs to the values in the capture's caption (e.g. "Bits 6, Rate 8.0, Drive 6 and
Mix 99"). `tests/test_render.py` runs the end-to-end check for a few plugins.
