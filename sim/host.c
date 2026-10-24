/* host.c — host implementations of the screen/audio stand-ins declared in harness/op1_host.h.
 *
 * Screen model: a plugin's SVG is drawn by the firmware; the plugin animates it by looking up named nodes and
 * setting matrices, visibility and colours, then draws extra raster lines and text on top. Here every lookup,
 * write and draw call is recorded, and host_frame_dump() prints one JSON line per video frame describing:
 *   nodes : the state of every node that differs from the SVG as loaded (matrix, visibility, stroke, fill)
 *   ops   : the immediate-mode drawing of this frame, in order; ["svg"] marks where the SVG itself was drawn
 * The Python side (op1video/svgframe.py) turns that into an SVG per frame.
 *
 * Copyright (C) 2026 op1-plugin-video contributors. GPL-3.0-or-later (see LICENSE).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "harness/op1_host.h"

/* ---- audio-side globals (names as in the SDK's own host tests) ---- */
int16_t  host_sine[8192];
int32_t  host_pitch_inc[128];
int16_t  host_voice_env[128];
uint8_t  host_voice_mem[6 * 0x24] __attribute__((aligned(16)));
int16_t  host_voice_vel[6];
int16_t  host_knobs[8][8];
int      host_slot;
const uint8_t *host_sample_buffer[8];
int16_t  host_fx_knobs[3][8];
int16_t  host_fx_meter[3];
void    *host_fx_scratch[3];
int      host_fx_pos;
uint8_t  host_shift;
uint32_t host_cycles;

int16_t  host_accel[3];               /* accelerometer x, y, z (aether: tilt) */
int      host_tuner;                  /* live-input engines: T2 tuner page shown */

/* core-owned globals plugins may reference */
volatile uint8_t  op1_fx_page[3][4];
volatile uint8_t  op1_eng_page[4];
int32_t           op1_db_last_err;
volatile uint32_t sm_cy[5];

void *read_fx_param_safe(int slot, int pos) { (void)slot; (void)pos; return 0; }
int op1_input_tuner_active(void) { return host_tuner; }

/* ---- nodes ---- */
#define MAX_NODES 1024
typedef struct {
    char    id[64];
    int32_t m[9];
    uint8_t has_m, visible, vis_touched;
    uint8_t stroke[4], fill[4];          /* live colour buffers handed out to the plugin */
    uint8_t stroke0[4], fill0[4];        /* as loaded from the SVG */
    uint8_t has_stroke, has_fill;
} host_node;

static host_node nodes[MAX_NODES];
static int n_nodes;
static int strict_ids;                   /* 1 when an id list was loaded: unknown ids return NULL like the device */
static int warned_unknown;

static int hexbyte(const char *s) { int v = 0; for (int i = 0; i < 2; i++) { char c = s[i]; v <<= 4;
    v |= (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : 0; }
    return v; }
static void parse_rgba(const char *s, uint8_t out[4], uint8_t *has)
{
    if (!s || s[0] == '-' || strlen(s) < 8) { out[0] = out[1] = out[2] = out[3] = 0; *has = 0; return; }
    for (int i = 0; i < 4; i++) out[i] = (uint8_t)hexbyte(s + 2 * i);
    *has = 1;
}

/* id file: one node per line: "<id> <stroke rrggbbaa|-> <fill rrggbbaa|->" (written by op1video/svgframe.py) */
int host_load_ids(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    char id[64], st[16], fi[16];
    while (n_nodes < MAX_NODES && fscanf(f, "%63s %15s %15s", id, st, fi) == 3) {
        host_node *n = &nodes[n_nodes++];
        memset(n, 0, sizeof *n);
        snprintf(n->id, sizeof n->id, "%s", id);
        n->visible = 1;
        parse_rgba(st, n->stroke0, &n->has_stroke);
        parse_rgba(fi, n->fill0, &n->has_fill);
        memcpy(n->stroke, n->stroke0, 4);
        memcpy(n->fill, n->fill0, 4);
    }
    fclose(f);
    strict_ids = 1;
    return n_nodes;
}

static host_node *lookup(const char *id, int create)
{
    for (int i = 0; i < n_nodes; i++) if (!strcmp(nodes[i].id, id)) return &nodes[i];
    if (strict_ids || !create || n_nodes >= MAX_NODES) {
        if (strict_ids && !warned_unknown) {
            fprintf(stderr, "op1sim: note: screen looked up an id that is not in the SVG (%s); returning NULL as the device does\n", id);
            warned_unknown = 1;
        }
        return 0;
    }
    host_node *n = &nodes[n_nodes++];
    memset(n, 0, sizeof *n);
    snprintf(n->id, sizeof n->id, "%s", id);
    n->visible = 1;
    return n;
}

void *host_find_node(void *scr, const char *id) { (void)scr; return id ? lookup(id, 1) : 0; }

void host_node_set_transform(void *node, const int32_t *m9)
{
    host_node *n = node;
    if (!n || !m9) return;
    memcpy(n->m, m9, sizeof n->m);
    n->has_m = 1;
}

void host_node_set_visible(void *node, int on)
{
    host_node *n = node;
    if (!n) return;
    n->visible = on != 0;
    n->vis_touched = 1;
}

uint8_t *host_node_line_rgba(void *scr, const char *id)
{ (void)scr; host_node *n = lookup(id, 1); if (!n) return 0; n->has_stroke = 1; return n->stroke; }
uint8_t *host_node_fill_rgba(void *scr, const char *id)
{ (void)scr; host_node *n = lookup(id, 1); if (!n) return 0; n->has_fill = 1; return n->fill; }

/* ---- immediate-mode ops for the current frame ---- */
enum { OP_SVG, OP_LINE, OP_TEXT };
typedef struct {
    int kind;
    int32_t a[5];               /* line: x0 y0 x1 y1 w (Q10); text: x(Q10) y size align has_m */
    int32_t m[9];
    uint8_t rgba[4];
    char *str;
} host_op;

static host_op *ops;
static int n_ops, cap_ops;
static int raster_token;

static host_op *push_op(int kind)
{
    if (n_ops == cap_ops) {
        cap_ops = cap_ops ? cap_ops * 2 : 1024;
        ops = realloc(ops, (size_t)cap_ops * sizeof *ops);
        if (!ops) { fprintf(stderr, "op1sim: out of memory\n"); exit(3); }
    }
    host_op *o = &ops[n_ops++];
    memset(o, 0, sizeof *o);
    o->kind = kind;
    return o;
}

void host_screen_draw(void *scr, int dt) { (void)scr; (void)dt; push_op(OP_SVG); }
void *host_raster(void) { return &raster_token; }

typedef struct { int32_t x, y; } hpt;
void host_raster_line(void *r, const void *p0, const void *p1, int32_t w_q10, const uint8_t *rgba)
{
    (void)r;
    const hpt *a = p0, *b = p1;
    if (!a || !b || !rgba) return;
    host_op *o = push_op(OP_LINE);
    o->a[0] = a->x; o->a[1] = a->y; o->a[2] = b->x; o->a[3] = b->y; o->a[4] = w_q10;
    memcpy(o->rgba, rgba, 4);
}

/* firmware text object, stored inside the plugin's OP1_TEXT_SIZE (0xA4) byte buffer */
typedef struct {
    uint32_t magic;
    int32_t x, y, size, align;
    uint8_t rgba[4];
    char str[OP1_TEXT_SIZE - 24];
} host_text;
_Static_assert(sizeof(host_text) <= OP1_TEXT_SIZE, "text object must fit the firmware's size");
#define TEXT_MAGIC 0x54585431u

void *host_text_ctor(void *obj, int32_t x_q10, int32_t y, int32_t size, const uint8_t *rgba)
{
    host_text *t = obj;
    if (!t) return 0;
    memset(t, 0, sizeof *t);
    t->magic = TEXT_MAGIC; t->x = x_q10; t->y = y; t->size = size;
    if (rgba) memcpy(t->rgba, rgba, 4); else memset(t->rgba, 255, 4);
    return t;
}
void host_text_set(void *obj, const char *s) { host_text *t = obj; if (t) snprintf(t->str, sizeof t->str, "%s", s ? s : ""); }
void host_text_align(void *obj, int align) { host_text *t = obj; if (t) t->align = align; }
int32_t host_text_width(const void *obj)
{
    const host_text *t = obj;
    return t ? (int32_t)strlen(t->str) * t->size * 600 : 0;   /* ~0.59 em per glyph, Q10 */
}
/* text without a text object, for plugin compat hooks (sim/compat/) */
void host_text_op(int32_t x_q10, int32_t y, int32_t size, int align, const uint8_t *rgba, const char *s)
{
    if (!s || !s[0]) return;
    host_op *o = push_op(OP_TEXT);
    o->a[0] = x_q10; o->a[1] = y; o->a[2] = size; o->a[3] = align;
    if (rgba) memcpy(o->rgba, rgba, 4); else memset(o->rgba, 255, 4);
    o->str = strdup(s);
}

void host_text_draw(void *obj, void *r, const int32_t *m9)
{
    (void)r;
    host_text *t = obj;
    if (!t || t->magic != TEXT_MAGIC || !t->str[0]) return;
    host_op *o = push_op(OP_TEXT);
    o->a[0] = t->x; o->a[1] = t->y; o->a[2] = t->size; o->a[3] = t->align; o->a[4] = m9 != 0;
    if (m9) memcpy(o->m, m9, sizeof o->m);
    memcpy(o->rgba, t->rgba, 4);
    o->str = strdup(t->str);
}

/* ---- per-frame JSON ---- */
static void put_rgba(FILE *f, const uint8_t c[4]) { fprintf(f, "\"%02x%02x%02x%02x\"", c[0], c[1], c[2], c[3]); }
static void put_str(FILE *f, const char *s)
{
    fputc('"', f);
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') { fputc('\\', f); fputc(c, f); }
        else if (c < 0x20 || c > 0x7e) fprintf(f, "\\u%04x", c);
        else fputc(c, f);
    }
    fputc('"', f);
}

void host_frame_begin(void)
{
    for (int i = 0; i < n_ops; i++) free(ops[i].str);
    n_ops = 0;
}

void host_frame_dump(FILE *f, int frame, double t_ms)
{
    fprintf(f, "{\"f\":%d,\"t\":%.2f,\"nodes\":{", frame, t_ms);
    int first = 1;
    for (int i = 0; i < n_nodes; i++) {
        host_node *n = &nodes[i];
        int st = n->has_stroke && memcmp(n->stroke, n->stroke0, 4);
        int fi = n->has_fill && memcmp(n->fill, n->fill0, 4);
        if (!n->has_m && !(n->vis_touched && !n->visible) && !st && !fi) continue;
        fprintf(f, "%s", first ? "" : ",");
        first = 0;
        put_str(f, n->id);
        fputs(":{", f);
        int k = 0;
        if (n->has_m) {
            fputs("\"m\":[", f);
            for (int j = 0; j < 9; j++) fprintf(f, "%s%d", j ? "," : "", n->m[j]);
            fputc(']', f);
            k = 1;
        }
        if (n->vis_touched && !n->visible) { fprintf(f, "%s\"v\":0", k ? "," : ""); k = 1; }
        if (st) { fprintf(f, "%s\"s\":", k ? "," : ""); put_rgba(f, n->stroke); k = 1; }
        if (fi) { fprintf(f, "%s\"fl\":", k ? "," : ""); put_rgba(f, n->fill); }
        fputc('}', f);
    }
    fputs("},\"ops\":[", f);
    for (int i = 0; i < n_ops; i++) {
        host_op *o = &ops[i];
        if (i) fputc(',', f);
        if (o->kind == OP_SVG) { fputs("[\"svg\"]", f); continue; }
        if (o->kind == OP_LINE) {
            fprintf(f, "[\"l\",%d,%d,%d,%d,%d,", o->a[0], o->a[1], o->a[2], o->a[3], o->a[4]);
            put_rgba(f, o->rgba);
            fputc(']', f);
            continue;
        }
        fprintf(f, "[\"t\",%d,%d,%d,%d,", o->a[0], o->a[1], o->a[2], o->a[3]);
        put_rgba(f, o->rgba);
        fputc(',', f);
        put_str(f, o->str);
        if (o->a[4]) {
            fputs(",[", f);
            for (int j = 0; j < 9; j++) fprintf(f, "%s%d", j ? "," : "", o->m[j]);
            fputc(']', f);
        }
        fputc(']', f);
    }
    fputs("]}\n", f);
}
