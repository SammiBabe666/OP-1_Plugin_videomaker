/* Crush (Maiko #250 port) ships its own host hooks for the SDK's preview harness, which the source bundle does
 * not include. These route them into op1sim's recorder. In host mode crush_screen.c also turns op1_screen_draw
 * into a no-op; the frame builder then draws the SVG first, as the device does.
 * Copyright (C) 2026 op1-plugin-video contributors. GPL-3.0-or-later (see LICENSE). */
#include <stdint.h>
#include "harness/op1_host.h"

void host_text_op(int32_t x_q10, int32_t y, int32_t size, int align, const uint8_t *rgba, const char *s);

void crush_host_knobs(int16_t *out) { for (int i = 0; i < 4; i++) out[i] = host_fx_knobs[host_fx_pos][i]; }
void *crush_host_raster(void) { return host_raster(); }
void crush_host_line(void *r, const void *a, const void *b, int32_t w, const uint8_t *c) { host_raster_line(r, a, b, w, c); }
/* same arguments as the device path: x in px (the device converts with OP1_Q10), y in px, size */
void crush_host_text(void *r, int x, int y, int size, const char *s, const uint8_t *c)
{ (void)r; host_text_op((int32_t)x * 1024, y, size, 0, c, s); }
int16_t crush_host_sine(uint32_t phase) { return host_sine[(phase >> 19) & 8191]; }
