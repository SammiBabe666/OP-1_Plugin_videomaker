# Shortcuts. Everything here is also available as ./op1video.py <command>; see docs/USAGE.md.
PY      ?= python3
OP1     = $(PY) op1video.py
OUT     ?= renders

.PHONY: help setup doctor fetch list build render-all cards gifs example-audio test clean distclean

help:
	@echo "make setup          create .venv and install the Python requirements"
	@echo "make doctor         check compiler, ffmpeg, rasterizer, source bundle"
	@echo "make fetch          download + verify the plugin source bundle"
	@echo "make build          compile every plugin simulator (render does this on demand)"
	@echo "make render-all     1080p card videos of every plugin -> $(OUT)/"
	@echo "make cards          screen-only WebM loops sized for the workshop cards -> $(OUT)/cards/"
	@echo "make gifs           small looping GIFs -> $(OUT)/gif/"
	@echo "make render P=eva   one plugin (extra options: ARGS='--layout square')"
	@echo "make example-audio  write examples/audio/loop.wav for the example scenes"
	@echo "make test           run the tests"
	@echo "make clean          remove renders/; distclean also removes .cache/"

setup:
	$(PY) -m venv .venv
	.venv/bin/pip install -r requirements.txt
	@echo "now: source .venv/bin/activate && make doctor"

doctor:
	$(OP1) doctor

fetch:
	$(OP1) fetch

list:
	$(OP1) list

build:
	$(OP1) build --all

render:
	$(OP1) render $(P) $(ARGS)

render-all:
	$(OP1) render-all --out-dir $(OUT) $(ARGS)

cards:
	$(OP1) render-all --layout screen --size 960x480 --format webm --no-audio --out-dir $(OUT)/cards $(ARGS)

gifs:
	$(OP1) render-all --layout screen --scale 2 --format gif --duration 6 --out-dir $(OUT)/gif $(ARGS)

example-audio:
	mkdir -p examples/audio
	ffmpeg -v error -y -f lavfi -i "sine=frequency=220:duration=6,volume=0.5" \
	  -f lavfi -i "anoisesrc=d=6:c=pink:a=0.08" -filter_complex "[0][1]amix=2,tremolo=f=4:d=0.6" \
	  -ac 1 -ar 44100 examples/audio/loop.wav
	@echo "examples/audio/loop.wav"

test:
	$(PY) -m unittest discover -s tests -v

clean:
	rm -rf $(OUT)

distclean: clean
	rm -rf .cache
