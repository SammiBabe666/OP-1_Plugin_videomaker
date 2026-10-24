# Example scenes

Annotated scenes that show every scene feature. Render one with:

```bash
./op1video.py render hail --scene examples/hail-everything.yaml
```

| file | shows |
|---|---|
| `hail-everything.yaml` | sequences with rests and chords, glides with easing, jumps, encoder pushes to page 2, page-2 moves, freeze, `{raw: ...}` values |
| `washer-your-audio.yaml` | an effect processing your own audio file (`source: {file: ...}`), square layout |
| `aether-tilt.yaml` | tilting the OP–1 (`tilt: [side, front]`), shift, 60 fps |
| `amp-tuner.yaml` | a live-input engine with the T2 tuner page (`tuner: true`) |
| `granular-your-sample.yaml` | Granular playing your own sample (`sample: ...`) |
| `vapora-presets.yaml` | a plugin that isn't in the workshop bundle (`--plugin-dir`), stepping through its preset files with captions, for the vertical layout |

The two scenes that read audio files expect `examples/audio/loop.wav`; `make example-audio` writes a test loop
there with ffmpeg, or drop in any file of your own.
