/* driver.c — op1sim: runs one kennel plugin (synth engine, effect or live-input engine) and its screen on the host.
 *
 * Built per plugin by op1video/build.py. Each plugin source is compiled in its own translation unit (as the
 * firmware build does) through a small wrapper that also exports that unit's beat clock; this file, host.c and
 * the generated beats.c are separate units. Defines:
 *   -DOP1V_KIND_SYNTH | -DOP1V_KIND_FX | -DOP1V_KIND_INPUT
 *   -DOP1V_SYMBOL=<symbol from plugin.json>   -DOP1V_SCREEN=<screen symbol> (optional)
 *
 * Usage: op1sim <script> <ids> <frames.jsonl> <audio.s16>
 *   script : the performance, written by op1video/scene.py (format: docs/HOW-IT-WORKS.md)
 *   ids    : SVG node ids with stroke/fill, written by op1video/svgframe.py ("-" = accept any id)
 *   frames : one JSON line per captured video frame (format: host.c)
 *   audio  : mono s16le PCM, 44.1 kHz
 *
 * Timing follows the device: audio in 128-sample synth blocks / 64-sample FX and input blocks at 44.1 kHz; the
 * screen is updated on every 60 Hz GUI tick with dt in milliseconds; every (60 / fps)-th tick is captured.
 *
 * Copyright (C) 2026 op1-plugin-video contributors. GPL-3.0-or-later (see LICENSE).
 */
#ifndef OP1_HOST
#define OP1_HOST
#endif
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "op1_plugin.h"

int  host_load_ids(const char *path);
void host_frame_begin(void);
void host_frame_dump(FILE *f, int frame, double t_ms);
extern int16_t host_accel[3];
extern int host_tuner;

/* beats.c (generated): one accessor per plugin translation unit */
extern op1_beat_t *(*const op1v_beats[])(void);
extern const int op1v_nbeats;

#if defined(OP1V_KIND_SYNTH) + defined(OP1V_KIND_FX) + defined(OP1V_KIND_INPUT) != 1
#error "define exactly one of OP1V_KIND_SYNTH, OP1V_KIND_FX, OP1V_KIND_INPUT"
#endif

#ifdef OP1V_KIND_INPUT
#include "op1_input.h"
extern const op1_input_engine_t OP1V_SYMBOL;
#elif defined(OP1V_KIND_SYNTH)
extern const op1_engine_t OP1V_SYMBOL;
#else
extern const op1_fx_t OP1V_SYMBOL;        /* stereo FX (op1_fx_stereo_t) start with the same mono op1_fx_t */
#endif
#ifdef OP1V_SCREEN
extern const op1_screen_t OP1V_SCREEN;
#endif

#define RATE 44100
#define MAX_FRAMES 72000                  /* 20 minutes at 60 fps */
#define MAX_EVENTS 65536
#define NV OP1_VOICES

/* ------------------------------------------------------------------------------------------------ script */
typedef struct { int16_t p[8]; uint8_t pg[4]; uint8_t shift; int16_t accel[3]; } frame_knobs;
typedef struct { int64_t at; int kind; int note; int vel; } event;   /* kind 1 on, 0 off */

static frame_knobs *fk;
static int n_frames, fps = 30;
static event ev[MAX_EVENTS];
static int n_ev;
static int env_a = 10, env_d = 300, env_s = 26000, env_r = 500;    /* ms, ms, Q15, ms */
static int master_q15 = 16384;
static int bpm = 120;
static char source[32] = "saw";
static char source_file[1024], sample_file[1024];
static int src_level_q15 = 22000;
static int use_tuner;

static int cmp_ev(const void *a, const void *b)
{
    const event *x = a, *y = b;
    if (x->at != y->at) return x->at < y->at ? -1 : 1;
    return x->kind - y->kind;             /* offs before ons at the same time */
}

static int load_script(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); return -1; }
    char key[64];
    while (fscanf(f, "%63s", key) == 1) {
        if (key[0] == '#') { int c; while ((c = fgetc(f)) != EOF && c != '\n'); continue; }
        if (!strcmp(key, "fps")) { if (fscanf(f, "%d", &fps) != 1) return -1; }
        else if (!strcmp(key, "frames")) {
            if (fscanf(f, "%d", &n_frames) != 1 || n_frames < 1 || n_frames > MAX_FRAMES) return -1;
            fk = calloc((size_t)n_frames, sizeof *fk);
        }
        else if (!strcmp(key, "envelope")) { if (fscanf(f, "%d %d %d %d", &env_a, &env_d, &env_s, &env_r) != 4) return -1; }
        else if (!strcmp(key, "master")) { if (fscanf(f, "%d", &master_q15) != 1) return -1; }
        else if (!strcmp(key, "bpm")) { if (fscanf(f, "%d", &bpm) != 1) return -1; }
        else if (!strcmp(key, "tuner")) { if (fscanf(f, "%d", &use_tuner) != 1) return -1; }
        else if (!strcmp(key, "source")) { if (fscanf(f, "%31s %d", source, &src_level_q15) != 2) return -1; }
        else if (!strcmp(key, "source_file")) { if (fscanf(f, " %1023[^\n]", source_file) != 1) return -1; }
        else if (!strcmp(key, "sample_file")) { if (fscanf(f, " %1023[^\n]", sample_file) != 1) return -1; }
        else if (!strcmp(key, "k")) {
            /* k <frame> p0..p7 page0..page3 shift ax ay az */
            int fr, v[16];
            if (fscanf(f, "%d", &fr) != 1) return -1;
            for (int i = 0; i < 16; i++) if (fscanf(f, "%d", &v[i]) != 1) return -1;
            if (!fk || fr < 0 || fr >= n_frames) continue;
            for (int i = 0; i < 8; i++) fk[fr].p[i] = (int16_t)v[i];
            for (int i = 0; i < 4; i++) fk[fr].pg[i] = (uint8_t)v[8 + i];
            fk[fr].shift = (uint8_t)v[12];
            for (int i = 0; i < 3; i++) fk[fr].accel[i] = (int16_t)v[13 + i];
        }
        else if (!strcmp(key, "on") || !strcmp(key, "off")) {
            long long at; int note, vel = 0;
            if (fscanf(f, "%lld %d", &at, &note) != 2) return -1;
            if (key[1] == 'n' && fscanf(f, "%d", &vel) != 1) return -1;
            if (n_ev < MAX_EVENTS) ev[n_ev++] = (event){ at, key[1] == 'n', note, vel };
        }
        else if (!strcmp(key, "end")) break;
        else { fprintf(stderr, "op1sim: unknown script key %s\n", key); fclose(f); return -1; }
    }
    fclose(f);
    if (!fk) { fprintf(stderr, "op1sim: script has no frames\n"); return -1; }
    qsort(ev, (size_t)n_ev, sizeof *ev, cmp_ev);
    return 0;
}

/* ------------------------------------------------------------------------------------------------ helpers */
static uint32_t note_inc(int note) { return (uint32_t)llround(4294967296.0 * 440.0 * pow(2.0, (note - 69) / 12.0) / RATE); }
static uint32_t v_rng = 0x1234567u;
static int32_t v_noise(void) { v_rng = v_rng * 1664525u + 1013904223u; return (int32_t)(v_rng >> 16) - 32768; }

/* ADSR in Q15 per sample. stage: 0 off, 1 attack, 2 decay, 3 sustain, 4 release */
typedef struct { int stage; int32_t lvl; int32_t rel_step; } v_adsr;
static int32_t step_for(int ms, int32_t span) { int n = ms * RATE / 1000; return n < 1 ? span : (span + n - 1) / n; }
static int32_t adsr_tick(v_adsr *e)
{
    switch (e->stage) {
    case 1: e->lvl += step_for(env_a, 32767); if (e->lvl >= 32767) { e->lvl = 32767; e->stage = 2; } break;
    case 2: e->lvl -= step_for(env_d, 32767 - env_s > 0 ? 32767 - env_s : 1); if (e->lvl <= env_s) { e->lvl = env_s; e->stage = 3; } break;
    case 4: e->lvl -= e->rel_step; if (e->lvl <= 0) { e->lvl = 0; e->stage = 0; } break;
    default: break;
    }
    return e->lvl;
}
static void adsr_release(v_adsr *e) { if (e->stage) { e->stage = 4; e->rel_step = step_for(env_r, e->lvl > 0 ? e->lvl : 1); } }

typedef struct { int active, note, gate; uint32_t inc, ph, ph2; int64_t age; v_adsr env; int32_t lp; } v_voice;
static v_voice vs[NV];
static int64_t age_counter;

static int alloc_voice(int note)
{
    for (int i = 0; i < NV; i++) if (vs[i].active && vs[i].note == note) return i;   /* retrigger */
    for (int i = 0; i < NV; i++) if (!vs[i].active) return i;
    int best = 0;                                                                     /* steal the oldest */
    for (int i = 1; i < NV; i++) if (vs[i].age < vs[best].age) best = i;
    return best;
}

static int16_t v_limit(int32_t x)         /* soft knee above -2.5 dBFS, then hard clip */
{
    if (x > 24576) x = 24576 + ((x - 24576) >> 2);
    if (x < -24576) x = -24576 + ((x + 24576) >> 2);
    return op1_sat16(x);
}

static int16_t params[8];
static void apply_knobs(int frame)
{
    const frame_knobs *k = &fk[frame < n_frames ? frame : n_frames - 1];
    memcpy(params, k->p, sizeof params);
    host_shift = k->shift;
    memcpy(host_accel, k->accel, sizeof host_accel);
#ifdef OP1V_KIND_FX
    for (int i = 0; i < 4; i++) op1_fx_page[0][i] = k->pg[i];
    for (int i = 0; i < 8; i++) host_fx_knobs[0][i] = params[i];
#else
    for (int i = 0; i < 4; i++) op1_eng_page[i] = k->pg[i];
    for (int i = 0; i < 8; i++) host_knobs[0][i] = params[i];
#endif
}

static int16_t *read_raw(const char *path, long *n_out)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return 0; }
    fseek(f, 0, SEEK_END);
    long bytes = ftell(f);
    fseek(f, 0, SEEK_SET);
    int16_t *d = malloc((size_t)bytes + 16);
    long n = d ? (long)fread(d, 2, (size_t)bytes / 2, f) : 0;
    fclose(f);
    *n_out = n;
    return d;
}

/* engines with "uses_sample" (granular) read the slot's sampler recording: SampleBuffer {data*, peak[0x813]} */
static struct { int16_t *data; int16_t peak[OP1_PEAK_BUCKETS]; } sample_buf;
static void setup_sample(void)
{
    long n = 0;
    int16_t *raw = sample_file[0] ? read_raw(sample_file, &n) : 0;
    if (n > OP1_SAMPLE_MAX) n = OP1_SAMPLE_MAX;
    if (!raw || n <= 0) {                 /* the SDK's preset-review demo sample: two drifting tones, 2 s */
        free(raw);
        n = 88200;
        raw = malloc((size_t)n * 2);
        for (long i = 0; i < n; i++)
            raw[i] = (int16_t)(9000 * sin(i * .0373) * (.5 + .5 * sin(i * .00007)) + 3000 * sin(i * .0559));
    }
    int16_t *d = calloc((size_t)OP1_SAMPLE_GUARD + (size_t)OP1_SAMPLE_MAX + 16, 2);
    memcpy(d + OP1_SAMPLE_GUARD, raw, (size_t)n * 2);
    free(raw);
    sample_buf.data = d;
    for (int b = 0; b < OP1_PEAK_BUCKETS; b++) {
        int16_t pk = 0;
        for (long i = (long)b * 256; i < (long)(b + 1) * 256 && i < n; i++) {
            int32_t v = d[OP1_SAMPLE_GUARD + i];
            if (v < 0) v = -v;
            if (v > 32767) v = 32767;
            if (v > pk) pk = (int16_t)v;
        }
        sample_buf.peak[b] = pk;
    }
    for (int s = 0; s < 8; s++) host_sample_buffer[s] = (const uint8_t *)&sample_buf;
}

/* beat clock: 1/16384 samples; broadcast to every plugin translation unit's copy */
static op1_beat_t beat;
static void beat_publish(void) { for (int i = 0; i < op1v_nbeats; i++) *op1v_beats[i]() = beat; }
static void beat_init(void)
{
    beat.len = (int32_t)((int64_t)2646000 * 16384 / (bpm > 0 ? bpm : 120));
    beat.next = 0; beat.step = 0x100000; beat.follows_tape = 0; beat.tape_pos = 0;
    beat_publish();
}
static void beat_advance(int samples)
{
    beat.next -= samples << 14;
    while (beat.next < 0) beat.next += beat.len;
    beat.tape_pos += samples;
    beat_publish();
}

/* ------------------------------------------------------------------------------------------------ audio */
#ifdef OP1V_KIND_SYNTH
#define BLOCK OP1_BLOCK
static const op1_engine_t *eng;

static void note_event(const event *e)
{
    if (e->kind) {
        int v = alloc_voice(e->note);
        void *self = host_voice_mem + v * OP1_VOICE_SIZE;
        vs[v] = (v_voice){ .active = 1, .note = e->note, .gate = 1, .inc = note_inc(e->note), .age = ++age_counter };
        vs[v].env.stage = 1;
        host_voice_vel[v] = (int16_t)((e->vel < 1 ? 1 : e->vel > 127 ? 127 : e->vel) << 8);
        for (int i = 0; i < 128; i++) host_pitch_inc[i] = (int32_t)vs[v].inc;
        eng->note_on(self, params);
    } else {
        for (int v = 0; v < NV; v++) if (vs[v].active && vs[v].gate && vs[v].note == e->note) {
            vs[v].gate = 0;
            adsr_release(&vs[v].env);
            if (eng->note_off) eng->note_off(host_voice_mem + v * OP1_VOICE_SIZE);
        }
    }
}

static void render_block(int16_t *out)
{
    int32_t mix[BLOCK] = { 0 };
    int16_t buf[BLOCK];
    for (int v = 0; v < NV; v++) {
        if (!vs[v].active) continue;
        int32_t env[BLOCK];
        for (int i = 0; i < BLOCK; i++) { env[i] = adsr_tick(&vs[v].env); host_voice_env[i] = (int16_t)env[i]; }
        for (int i = 0; i < 128; i++) host_pitch_inc[i] = (int32_t)vs[v].inc;
        eng->render(host_voice_mem + v * OP1_VOICE_SIZE, buf, params);
        for (int i = 0; i < BLOCK; i++) mix[i] += (buf[i] * env[i]) >> 15;
        if (!vs[v].env.stage) vs[v].active = 0;      /* the firmware frees a voice when its envelope ends */
    }
    for (int i = 0; i < BLOCK; i++) out[i] = v_limit((mix[i] * master_q15) >> 15);
}
#else
/* effects and live-input engines both process a dry signal in 64-sample blocks */
#define BLOCK OP1_FX_BLOCK
#ifdef OP1V_KIND_FX
static const op1_fx_t *fx;
#else
static const op1_input_engine_t *ieng;
#endif
static int16_t *src_raw;
static long src_len, src_pos;

static void note_event(const event *e)
{
    if (e->kind) {
        int v = alloc_voice(e->note);
        vs[v] = (v_voice){ .active = 1, .note = e->note, .gate = 1, .inc = note_inc(e->note), .age = ++age_counter,
                           .ph2 = 0x40000000u };
        vs[v].env.stage = 1;
    } else {
        for (int v = 0; v < NV; v++) if (vs[v].active && vs[v].gate && vs[v].note == e->note) {
            vs[v].gate = 0;
            adsr_release(&vs[v].env);
        }
    }
}

/* the dry signal: a small built-in synth played by the scene's notes, a drum loop, or a file */
static int32_t source_voice(v_voice *v)
{
    int32_t s;
    uint32_t i = v->inc;
    if (!strcmp(source, "sine")) { v->ph += i; s = OP1_SINE_TABLE[v->ph >> 19]; }
    else if (!strcmp(source, "square")) { v->ph += i; s = (v->ph >> 31) ? 20000 : -20000; }
    else if (!strcmp(source, "pluck")) {
        v->ph += i; v->ph2 += i + (i >> 9);
        s = (((int32_t)v->ph >> 16) + ((int32_t)v->ph2 >> 16)) >> 1;
        v->lp += ((s - v->lp) * ((v->env.lvl >> 1) + 1200)) >> 15;  /* brightness follows the envelope */
        s = v->lp;
    }
    else if (!strcmp(source, "noise")) s = v_noise() >> 1;
    else if (!strcmp(source, "pad")) {
        v->ph += i; v->ph2 += i + (i >> 8);
        s = (((int32_t)v->ph >> 16) + ((int32_t)v->ph2 >> 16)) >> 1;
        v->lp += ((s - v->lp) * 3500) >> 15;
        s = v->lp;
    }
    else { v->ph += i; v->ph2 += i + (i >> 10); s = (((int32_t)v->ph >> 16) + ((int32_t)v->ph2 >> 16)) >> 1; }  /* saw */
    return s;
}

static int64_t drum_t;
static int32_t drum_sample(void)           /* kick on beats, snare on 2 and 4, hat on eighths, at the bpm */
{
    int64_t beat_len = (int64_t)RATE * 60 / (bpm > 0 ? bpm : 120);
    int64_t t = drum_t++, in_beat = t % beat_len, beat_no = t / beat_len, in_eighth = t % (beat_len / 2);
    double tk = in_beat / (double)RATE;
    double kick = sin(2 * M_PI * (50 * tk + 90 * (1 - exp(-tk * 30)) / 30)) * exp(-tk * 9) * 26000;
    double hat = (v_noise() / 32768.0) * exp(-(in_eighth / (double)RATE) * 70) * 6000;
    double sn = (beat_no & 1) ? (v_noise() / 32768.0 * 0.8 + sin(2 * M_PI * 185 * tk) * 0.4) * exp(-tk * 18) * 16000 : 0;
    return (int32_t)(kick + hat + sn);
}

static void render_block(int16_t *out)
{
    int16_t buf[BLOCK], res[BLOCK];
    for (int n = 0; n < BLOCK; n++) {
        int32_t s = 0;
        if (src_raw) s = src_pos < src_len ? src_raw[src_pos++] : 0;
        else if (!strcmp(source, "drums")) s = drum_sample();
        else for (int v = 0; v < NV; v++) {
            if (!vs[v].active) continue;
            int32_t e = adsr_tick(&vs[v].env);
            s += (source_voice(&vs[v]) * e) >> 15;
            if (!vs[v].env.stage) vs[v].active = 0;
        }
        buf[n] = v_limit((s * src_level_q15) >> 15);
    }
#ifdef OP1V_KIND_FX
    fx->render(0, buf, params);
    memcpy(res, buf, sizeof res);
#else
    ieng->process(buf, res, params, RATE);
#endif
    int16_t pk = 0;
    for (int n = 0; n < BLOCK; n++) {
        out[n] = v_limit((res[n] * master_q15) >> 15);
        int32_t a = res[n] < 0 ? -res[n] : res[n];
        if (a > 32767) a = 32767;
        if (a > pk) pk = (int16_t)a;
    }
    int16_t m = host_fx_meter[0];              /* peak with decay, like the firmware's FX meter */
    host_fx_meter[0] = pk > m ? pk : (int16_t)(m - (m >> 4));
}
#endif

/* ------------------------------------------------------------------------------------------------ main */
int main(int argc, char **argv)
{
    if (argc != 5) {
        fprintf(stderr, "usage: %s <script> <ids> <frames.jsonl> <audio.s16>\n", argv[0]);
        return 2;
    }
    if (load_script(argv[1])) { fprintf(stderr, "op1sim: bad script %s\n", argv[1]); return 2; }
    if (strcmp(argv[2], "-") && host_load_ids(argv[2]) < 0) { perror(argv[2]); return 2; }
    if (fps < 1 || 60 % fps) { fprintf(stderr, "op1sim: fps must divide 60 (60, 30, 20, 15, 12...)\n"); return 2; }
    FILE *fo = fopen(argv[3], "w"), *fa = fopen(argv[4], "wb");
    if (!fo || !fa) { perror("op1sim: output"); return 2; }

    for (int i = 0; i < 8192; i++) host_sine[i] = (int16_t)lrint(32767 * sin(2 * M_PI * i / 8192));
    host_slot = 0; host_fx_pos = 0;
    host_tuner = use_tuner;
    setup_sample();
    apply_knobs(0);
    beat_init();

    const op1_screen_t *scr = 0;
#ifdef OP1V_SCREEN
    scr = &OP1V_SCREEN;
#endif
#ifdef OP1V_KIND_SYNTH
    eng = &OP1V_SYMBOL;
#elif defined(OP1V_KIND_FX)
    fx = &OP1V_SYMBOL;
    for (int p = 0; p < 3; p++) host_fx_scratch[p] = calloc(1, OP1_FX_SCRATCH_BYTES + 64);
    if (fx->init) fx->init(0);
#else
    ieng = &OP1V_SYMBOL;
    if (ieng->reset) ieng->reset(0, RATE);
    if (use_tuner && ieng->tuner) scr = ieng->tuner;
#endif
#ifndef OP1V_KIND_SYNTH
    if (source_file[0]) src_raw = read_raw(source_file, &src_len);
#endif

    static uint8_t screen_obj[4096];
    if (scr && scr->init) scr->init(screen_obj);

    const int ticks_per_frame = 60 / fps;
    const int64_t total_ticks = (int64_t)n_frames * ticks_per_frame;
    int64_t audio_pos = 0;
    int ei = 0;
    int16_t out[BLOCK];
    for (int64_t tick = 0; tick < total_ticks; tick++) {
        const int frame = (int)(tick / ticks_per_frame);
        apply_knobs(frame);
        const int64_t target = (tick + 1) * RATE / 60;
        while (audio_pos < target) {
            while (ei < n_ev && ev[ei].at < audio_pos + BLOCK) note_event(&ev[ei++]);
            render_block(out);
            beat_advance(BLOCK);
#ifdef OP1V_KIND_INPUT
            if (ieng->service) ieng->service();   /* the device's main loop runs far more often than the GUI */
#endif
            fwrite(out, sizeof(int16_t), BLOCK, fa);
            audio_pos += BLOCK;
        }
        const int dt = (int)((tick + 1) * 1000 / 60 - tick * 1000 / 60);      /* 16 / 17 ms */
        host_frame_begin();
        if (scr && scr->update) scr->update(screen_obj, dt);
        else host_screen_draw(0, dt);
        if ((tick + 1) % ticks_per_frame == 0) host_frame_dump(fo, frame, (double)(tick + 1) * 1000.0 / 60.0);
    }
    fclose(fo);
    fclose(fa);
    return 0;
}
