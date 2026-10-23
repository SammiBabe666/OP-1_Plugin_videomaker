# Scenes

A scene is a short performance written in YAML: what is played, and how the encoders move. The demo scenes in
`scenes/` (one per plugin) are good starting points, as is `./op1video.py scene <plugin>`. Annotated examples
covering every feature are in [`examples/`](../examples).

```yaml
plugin: eva                           # the plugin folder name (op1video list)
title: EVA                            # card/square layouts; default: the plugin name
subtitle: An astronaut's choir over the helmet radio.
duration: 16                          # seconds (default 8)
fps: 30                               # 60, 30, 20, 15, 12 ... (default 30)
bpm: 120                              # tempo for tempo-synced effects and the drum source (default 120)
labels: [Pressure, Freq, Oxygen, Com] # encoder names shown in the card layout

knobs: [61, 50, 37, 9]                # start values: blue, green, white, orange, in percent (default: plugin.json)
envelope: {attack: 250, decay: 600, sustain: 85, release: 1200}

notes:
  - {at: 0.2, len: 3.3, chord: [C2, G2, Eb3]}
  - {at: 7.6, every: 1.2, len: 1.0, notes: [G2, Bb2, D3, C3], until: 12}

moves:
  - {at: 3.6, to: 4.4, knobs: [34, 12, 67, 18]}
  - {at: 12, to: 15, knob: orange, value: 90}
```

Times are in seconds from the start. Values are percentages of an encoder's range, as in the manual's
"Try this" bars, unless written as `{raw: 0..32767}` (the plugin's own Q15 word).

## Top-level keys

| key | default | |
|---|---|---|
| `plugin` | — | must match the plugin being rendered (a mismatch is an error) |
| `title`, `subtitle` | plugin name, none | layout text |
| `duration` | 8 | seconds |
| `fps` | 30 | must divide 60 |
| `bpm` | 120 | beat clock for STUTTER, In a room's synced loops, and the `drums` source |
| `labels` | Blue, Green, White, Orange | up to four encoder names |
| `knobs` | plugin.json `defaults` | four start values; `null` keeps a default |
| `page2` | plugin.json `page2_defaults` | start values of the page-2 words (blue2, green2, white2) |
| `pages` | `[0, 0, 0, 0]` | start with an encoder already pushed to page 2 / latched (1) |
| `envelope` | `{attack: 10, decay: 300, sustain: 80, release: 500}` | ms, ms, percent, ms: the OP–1's T2 envelope for synths, and the built-in source's envelope for effects |
| `master` | 50 | output gain in percent, before normalisation |
| `normalize` | -1 | peak target in dBFS for the final audio; `false` to keep the level as rendered |
| `source` | `{type: pluck, level: 70}` | the dry signal for effects and Amp (below) |
| `sample` | built-in demo | an audio file for Granular's sampler slot (decoded to 44.1 kHz mono, up to 6 s) |
| `tuner` | false | Amp: render its T2 tuner page instead of the T1 page |
| `output` | | `{layout: square}` makes that the default layout for this scene |

## notes

Each entry is one of:

```yaml
- {at: 1.0, len: 0.5, note: C3, vel: 100}            # one note (middle C)
- {at: 1.0, len: 2.0, chord: [C2, E2, G2]}           # several at once
- {at: 0.0, every: 0.25, len: 0.2, notes: "C3 E3 G3 -", until: 8}   # a repeating sequence
- {at: 0.0, every: 1.0, len: 0.9, notes: [C2+E2+G2, A1+C2+E2]}     # a chord sequence
```

* Note names follow the OP–1 (Teenage Engineering) convention, the one its screens use — Amp's tuner, Palme's
  root: **`C3` is MIDI 60 (middle C) and `A3` is 440 Hz**, one octave lower in name than the "C4 = 60" some DAWs
  use. Sharps `F#2`, flats `Bb1`, negative octaves `C-1`; MIDI numbers work too.
* `len` (seconds, default 0.5) is how long the key is held; the sound continues through the envelope's release.
* `vel` is 1–127 (default 100). The synths follow velocity.
* Sequences: `every` is the step length, `until` the end time (default: the scene's end). Steps cycle through
  `notes`; `-` or `.` is a rest; `+` joins notes into a chord. `notes` can be a space-separated string or a list.
* An octave down or up, as in the manual's "octave −1": write the notes an octave lower or higher.
* Six voices, like the OP–1: a seventh note steals the oldest voice.

## moves

Moves change the encoders, and press them, over time. They are applied in time order; a later move on the same
encoder takes over from an earlier one.

```yaml
- {at: 2, to: 5, knob: white, value: 80}             # glide white to 80% between 2 s and 5 s
- {at: 6, knob: blue, value: 25}                     # jump (no "to")
- {at: 6, to: 8, knobs: [40, null, 10, 90]}          # several at once; null leaves one alone
- {at: 3, to: 6, knob: green, value: 95, ease: linear}
- {at: 9, press: orange}                             # push: toggles page 2 or a latch (freeze ...)
- {at: 9, press: [green, white]}                     # push two
- {at: 9.2, to: 11, knob: green2, value: 60}         # move a page-2 word
- {at: 4, shift: true, len: 1.5}                     # hold shift
- {at: 1, to: 3, tilt: [0, 25]}                      # tilt the OP-1 (Aether)
```

| key | |
|---|---|
| `knob` + `value` | encoder `blue`, `green`, `white`, `orange` (or `red`, or 0–3); page-2 words `blue2`, `green2`, `white2` (5–7) |
| `knobs` | four values for blue..orange; `null` to skip |
| `to` | end of a glide; without it the change is instant |
| `ease` | `smooth` (default), `linear`, `sine`, `in`, `out` |
| `press` | an encoder name or a list: each press toggles that encoder's page-2 / latch flag, as pushing it on the device does. What a push means is plugin-specific (see the manual): page 2 on MBIRA, Oxbow, Mixtur, Arc, Palme, HAIL...; freeze on HAIL, STUTTER, Clouds; latch on Palme; capture on In a room |
| `shift` + `len` or `to` | hold shift for a while |
| `tilt: [side, front]` | degrees, −90..90. side: right side up is positive; front: front edge up is positive. Glides with `to` |

The card layout shows page-2 values on an encoder while it is pushed (label `· P2`).

## source (effects and Amp)

Effects process a dry signal. By default the scene's `notes` play a small built-in synth into the effect:

```yaml
source: {type: pluck, level: 70}     # pluck | saw | pad | sine | square | noise
source: {type: drums, level: 85}     # kick, snare and hats at the scene's bpm (notes are ignored)
source: {file: my-guitar.wav}        # any audio file ffmpeg can read: decoded to 44.1 kHz mono
```

`level` is the input gain in percent. The `envelope` shapes the built-in synth's notes. A file is played from the
start; it is silent once it ends. Paths are relative to the scene file.

## Tips

* Start from the manual: each plugin's "Try this" settings are percentages you can paste into `knobs:`.
* Keep moves slow enough to see: the screens animate at 60 Hz and many respond with a little smoothing.
* Effects with tails (Snowglobe, Plate, Father, Reverb, Tape) look better with short plucks and space between
  them; granular effects (HAIL, Clouds) need sound in their buffer before a freeze shows anything.
* `./op1video.py still <plugin> --scene my.yaml --at T` is the quickest way to check a moment.
* Errors name the line's problem, e.g. `unknown knob 'purple'` or `bad note 'H4'`.
