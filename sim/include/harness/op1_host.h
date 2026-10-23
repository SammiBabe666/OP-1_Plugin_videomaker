/* op1_host.h — host-side stand-ins for the OP-1 firmware addresses used by kennel plugins.
 *
 * The kennel SDK (hundekraft op1-workshop source bundle) compiles plugin code for the host when OP1_HOST is
 * defined: op1_plugin.h then includes "harness/op1_host.h" and expects every firmware address it would normally
 * call to be provided here. The bundle does not ship this header, so op1-plugin-video provides its own,
 * using the same host_* names as the SDK's tests (tools/presets/review_host.c, plugins/*_test.c).
 *
 * Everything declared here is implemented in sim/host.c.
 *
 * Copyright (C) 2026 op1-plugin-video contributors. GPL-3.0-or-later (see LICENSE).
 */
#ifndef OP1_HOST_H
#define OP1_HOST_H
#include <stdint.h>
#include <stddef.h>

/* ---- audio-side state ---------------------------------------------------------------------------------- */
extern int16_t  host_sine[8192];            /* firmware sine table: sin(2*pi*k/8192) * 32767 */
extern int32_t  host_pitch_inc[128];        /* per-sample phase increment of the voice being rendered */
extern int16_t  host_voice_env[128];        /* stock envelope of the voice being rendered (Q15) */
extern uint8_t  host_voice_mem[6 * 0x24];   /* the six 0x24-byte voice objects */
extern int16_t  host_voice_vel[6];          /* velocity << 8 per voice */
extern int16_t  host_knobs[8][8];           /* synth knob words per instrument slot */
extern int      host_slot;                  /* current synth slot (also the slot the screen shows) */
extern const uint8_t *host_sample_buffer[8];/* sampler SampleBuffer per slot (granular) */
extern int16_t  host_fx_knobs[3][8];        /* FX knob words per FX position (synth, drum, master) */
extern int16_t  host_fx_meter[3];           /* FX output meter per position (peak with decay) */
extern void    *host_fx_scratch[3];         /* 176460-byte scratch buffer per FX position */
extern int      host_fx_pos;                /* FX position the FX screen shows (0 synth, 1 drum, 2 master) */
extern uint8_t  host_shift;                 /* shift key held */

#define OP1_PITCH_INC    ((const int32_t *)host_pitch_inc)
#define OP1_VOICE_ENV    ((const int16_t *)host_voice_env)
#define OP1_SINE_TABLE   ((const int16_t *)host_sine)
#define OP1_VOICE_BASE   ((uintptr_t)host_voice_mem)
#define OP1_VOICE_VEL    ((const volatile int16_t *)host_voice_vel)

static inline int op1_current_slot(void) { return host_slot; }
static inline const uint8_t *op1_sample_buffer(int slot) { return host_sample_buffer[slot & 7]; }
/* SampleBuffer layout as on the device: +0 int16 *data (8 guard samples first), +4 int16 peak[0x813] */
static inline const int16_t *op1_sample_data(const uint8_t *sb) { return *(int16_t *const *)sb + 8; }
static inline const int16_t *op1_sample_peaks(const uint8_t *sb) { return (const int16_t *)(sb + sizeof(void *)); }

static inline void *op1_fx_scratch(int pos) { return host_fx_scratch[pos]; }
static inline int op1_fx_screen_pos(void) { return host_fx_pos; }
static inline const int16_t *op1_fx_knobs(int pos) { return host_fx_knobs[pos]; }
/* the firmware rescales raw filter-slot words with a range table; the host stores words as 0..32767 already */
static inline int32_t op1_fx_param_q15(const int16_t *p, int i)
{ int32_t v = p[i]; return v < 0 ? 0 : (v > 32767 ? 32767 : v); }
static inline volatile int16_t *op1_fx_meter(int pos) { return (volatile int16_t *)&host_fx_meter[pos]; }

/* ---- screen side ------------------------------------------------------------------------------------- */
void    *host_find_node(void *scr, const char *id);
void     host_node_set_transform(void *node, const int32_t *m9);
void     host_node_set_visible(void *node, int on);
uint8_t *host_node_line_rgba(void *scr, const char *id);
uint8_t *host_node_fill_rgba(void *scr, const char *id);
void     host_screen_draw(void *scr, int dt);
void    *host_raster(void);
void     host_raster_line(void *r, const void *p0, const void *p1, int32_t w_q10, const uint8_t *rgba);
void    *host_text_ctor(void *obj, int32_t x_q10, int32_t y, int32_t size, const uint8_t *rgba);
void     host_text_set(void *t, const char *str);
void     host_text_draw(void *t, void *r, const int32_t *m9);
void     host_text_align(void *t, int align);
int32_t  host_text_width(const void *t);
void    *read_fx_param_safe(int slot, int pos);

#define op1_find_node(scr, id)              host_find_node((scr), (id))
#define op1_node_set_transform(node, m9)    host_node_set_transform((node), (m9))
#define op1_node_line_rgba(scr, id)         host_node_line_rgba((scr), (id))
#define op1_node_fill_rgba(scr, id)         host_node_fill_rgba((scr), (id))
#define op1_node_set_visible(node, on)      host_node_set_visible((node), (on))
#define op1_screen_draw(scr, dt)            host_screen_draw((scr), (dt))
#define op1_raster()                        host_raster()
#define op1_raster_line(r, p0, p1, w, rgba) host_raster_line((r), (p0), (p1), (w), (rgba))
#define OP1_SCREEN_SLOT                     host_slot

static inline const int16_t *op1_synth_knobs(int slot) { return host_knobs[slot & 7]; }
static inline void op1_synth_knobs_live(int slot, int16_t out[4])
{ for (int i = 0; i < 4; i++) out[i] = host_knobs[slot & 7][i]; }
static inline void op1_fx_knobs_live(int16_t out[4])
{ for (int i = 0; i < 4; i++) out[i] = host_fx_knobs[host_fx_pos][i]; }

/* firmware text (op1_synth.h): an object of OP1_TEXT_SIZE bytes */
#define OP1_TEXT_SIZE 0xA4
#define op1_text_ctor(obj, x_q10, y, size, rgba) host_text_ctor((obj), (x_q10), (y), (size), (rgba))
#define op1_text_set(t, str)                     host_text_set((t), (str))
#define op1_text_draw(t, r, m9)                  host_text_draw((t), (r), (m9))

#endif
