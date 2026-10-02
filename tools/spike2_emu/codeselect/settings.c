/* settings.c - see settings.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include "settings.h"
#include "colour.h"
#include "log.h"

#define TH(e, role) ((e)->th->rgb[TH_##role])

/* how a held flipper repeats a step, once it has been held this long */
#define REPEAT_AFTER_MS 450
#define REPEAT_EVERY_MS 80

/* one press of a value row */
#define STEP_GAMMA 0.05f
#define STEP_GAIN  0.02f
#define STEP_SAT   0.05f
#define STEP_LIFT  0.005f

/* THE STARTING POINTS the Color profile tab offers (core/colour_profile.py
 * PRESETS - tests/test_stern_shader_profile.py holds these numbers to that
 * table), after "As built", which is each image's own. */
struct preset {
    const char *name;
    float gamma[3], gain[3], lift[3], sat;
};
static const struct preset PRESETS[] = {
    { "Recommended",     { 1.10f, 1.20f, 1.35f }, { 1, 1, 1 }, { 0, 0, 0 }, 0.90f },
    { "No change",       { 1, 1, 1 },             { 1, 1, 1 }, { 0, 0, 0 }, 1.00f },
    { "Black and white", { 1, 1, 1 },             { 1, 1, 1 }, { 0, 0, 0 }, 0.00f },
};
#define NPRESETS ((int)(sizeof PRESETS / sizeof PRESETS[0]))

static void preset_colour(int k, struct colour *out)
{
    memcpy(out->gamma, PRESETS[k].gamma, sizeof out->gamma);
    memcpy(out->gain, PRESETS[k].gain, sizeof out->gain);
    memcpy(out->lift, PRESETS[k].lift, sizeof out->lift);
    out->sat = PRESETS[k].sat;
}

enum row_kind { R_GAME, R_PRESET, R_GAMMA, R_GAIN, R_SAT, R_LIFT, R_SAVE, R_SAVE_ALL, R_LEAVE };
struct row { int kind, ch; };

enum screen { S_LIST, S_COLOR, S_DONE };

struct state {
    struct settings_env *e;
    int screen;
    int list_sel;
    /* the colour screen */
    int imgs[CONF_MAX_IMAGES], nimg, cur;
    struct colour work[CONF_MAX_IMAGES];     /* per image: what the screen shows */
    struct colour saved[CONF_MAX_IMAGES];    /* per image: what it boots with now */
    int has_saved[CONF_MAX_IMAGES];          /* ...and whether that is the file's, not the build's */
    struct row rows[16];
    int nrows, sel, editing;
    char status[240];
    int preset_k;                            /* START FROM while it is being changed: 0 = as built */
    int hold_ev;                             /* the key being held while editing, or 0 */
    long long next_rep;
    int move_voice;
};

static const char *const CH_NAME[3] = { "RED", "GREEN", "BLUE" };
static const unsigned CH_RGB[3] = { 0xE05555, 0x55C060, 0x5588E8 };

/* ------------------------------------------------------------- the values */

static const struct conf_colour *built_of(const struct state *st, int img)
{
    return &st->e->c->colour[img];
}

static int image_dirty(const struct state *st, int img)
{
    return !colour_equal(&st->work[img], &st->saved[img]);
}

static int any_dirty(const struct state *st)
{
    int k;
    for (k = 0; k < st->nimg; k++)
        if (image_dirty(st, st->imgs[k])) return 1;
    return 0;
}

/* which starting point the numbers are: 0 = as built, 1.. = PRESETS[k-1],
 * -1 = none of them (somebody's own) */
static int preset_of(const struct state *st, const struct colour *c, int img)
{
    int k;
    if (colour_equal(c, &built_of(st, img)->built)) return 0;
    for (k = 0; k < NPRESETS; k++) {
        struct colour p;
        preset_colour(k, &p);
        if (colour_equal(c, &p)) return k + 1;
    }
    return -1;
}

static float lift_of(const struct colour *c)
{
    return (c->lift[0] + c->lift[1] + c->lift[2]) / 3.0f;
}

static float stepped(float v, float step, int dir, float lo, float hi)
{
    v = roundf(v / step) * step + (float)dir * step;
    v = roundf(v / step) * step;
    return v < lo ? lo : v > hi ? hi : v;
}

static void value_text(const struct row *r, const struct colour *c, char *out, int n)
{
    switch (r->kind) {
    case R_GAMMA: {
        int d = (int)lroundf((c->gamma[r->ch] - 1.0f) * 100.0f);
        if (d == 0) snprintf(out, (size_t)n, "unchanged");
        else if (d > 0) snprintf(out, (size_t)n, "%d%% darker", d);
        else snprintf(out, (size_t)n, "%d%% brighter", -d);
        break;
    }
    case R_GAIN:
        snprintf(out, (size_t)n, "%d%%", (int)lroundf(c->gain[r->ch] * 100.0f));
        break;
    case R_SAT:
        snprintf(out, (size_t)n, "%d%%", (int)lroundf(c->sat * 100.0f));
        break;
    case R_LIFT: {
        float l = lift_of(c);
        if (l < 0.002f) snprintf(out, (size_t)n, "off");
        else snprintf(out, (size_t)n, "black becomes %d of 255", (int)lroundf(l * 255.0f));
        break;
    }
    default:
        out[0] = 0;
    }
}

/* one LEFT (-1) / RIGHT (+1) on the row being changed; 1 when anything moved */
static int step_row(struct state *st, int dir)
{
    const struct row *r = &st->rows[st->sel];
    int img = st->imgs[st->cur];
    struct colour *c = &st->work[img], before = *c;
    switch (r->kind) {
    case R_GAME:
        if (st->nimg < 2) return 0;
        st->cur = (st->cur + dir + st->nimg) % st->nimg;
        sel_log("color: now %s (image %d)", st->e->c->img[st->imgs[st->cur]].title, st->imgs[st->cur]);
        return 1;
    case R_PRESET: {
        /* through As built and the starting points, from the one the row
         * showed when it was opened - KEPT, not worked out from the numbers
         * again, or a game built with Recommended could never step past it:
         * its numbers are As built and Recommended both */
        int total = NPRESETS + 1;
        st->preset_k = (st->preset_k + dir + total) % total;
        if (st->preset_k == 0) *c = built_of(st, img)->built;
        else preset_colour(st->preset_k - 1, c);
        return 1;
    }
    case R_GAMMA:
        c->gamma[r->ch] = stepped(c->gamma[r->ch], STEP_GAMMA, dir, COLOUR_GAMMA_MIN, COLOUR_GAMMA_MAX);
        break;
    case R_GAIN:
        c->gain[r->ch] = stepped(c->gain[r->ch], STEP_GAIN, dir, COLOUR_GAIN_MIN, COLOUR_GAIN_MAX);
        break;
    case R_SAT:
        c->sat = stepped(c->sat, STEP_SAT, dir, COLOUR_SAT_MIN, COLOUR_SAT_MAX);
        break;
    case R_LIFT: {
        float l = stepped(lift_of(c), STEP_LIFT, dir, COLOUR_LIFT_MIN, COLOUR_LIFT_MAX);
        c->lift[0] = c->lift[1] = c->lift[2] = l;
        break;
    }
    default:
        return 0;
    }
    return !colour_equal(&before, c);
}

static void build_rows(struct state *st)
{
    int k, n = 0;
    if (st->nimg > 1) st->rows[n++] = (struct row){ R_GAME, 0 };
    st->rows[n++] = (struct row){ R_PRESET, 0 };
    for (k = 0; k < 3; k++) st->rows[n++] = (struct row){ R_GAMMA, k };
    for (k = 0; k < 3; k++) st->rows[n++] = (struct row){ R_GAIN, k };
    st->rows[n++] = (struct row){ R_SAT, 0 };
    st->rows[n++] = (struct row){ R_LIFT, 0 };
    st->rows[n++] = (struct row){ R_SAVE, 0 };
    if (st->nimg > 1) st->rows[n++] = (struct row){ R_SAVE_ALL, 0 };
    st->rows[n++] = (struct row){ R_LEAVE, 0 };
    st->nrows = n;
}

static void colour_open(struct state *st)
{
    const struct conf *c = st->e->c;
    int i, first = 0;
    st->nimg = 0;
    for (i = 0; i < c->n; i++) {
        if (!c->colour[i].set) continue;
        if (i == st->e->first_image) first = st->nimg;
        st->imgs[st->nimg++] = i;
        st->has_saved[i] = colour_file_get(st->e->colour_file, c->img[i].device, &st->saved[i]);
        if (!st->has_saved[i]) st->saved[i] = c->colour[i].built;
        st->work[i] = st->saved[i];
    }
    st->cur = first;
    build_rows(st);
    st->sel = 0;
    st->editing = 0;
    st->hold_ev = 0;
    st->status[0] = 0;
    {
        int img = st->imgs[st->cur];
        char vals[200];
        colour_format(&st->work[img], vals, sizeof vals);
        sel_say("settings: color correction, %d adjustable image%s, on image %d (%s): %s (%s)",
                st->nimg, st->nimg == 1 ? "" : "s", img, c->img[img].title, vals,
                st->has_saved[img] ? "set on this machine" : "as built");
    }
}

/* one image's numbers to the values file: none when they are the build's own */
static int save_image(struct state *st, int img, const struct colour *v)
{
    const struct conf *c = st->e->c;
    int as_built = colour_equal(v, &c->colour[img].built);
    char vals[200];
    if (colour_file_put(st->e->colour_file, c->img[img].device, as_built ? NULL : v) < 0) {
        sel_say("color: image %d (%s): cannot write %s: %s", img, c->img[img].title,
                st->e->colour_file, strerror(errno));
        return -1;
    }
    st->saved[img] = *v;
    st->work[img] = *v;
    st->has_saved[img] = !as_built;
    colour_format(v, vals, sizeof vals);
    sel_say("color: image %d (%s) saved: %s%s", img, c->img[img].title, vals,
            as_built ? " (as built: no line in the values file)" : "");
    return 0;
}

/* ------------------------------------------------------------------ draw */

static float S(const struct settings_env *e)
{
    return (float)e->g->h / 768.0f;
}

static void text_fit(struct settings_env *e, const char *s, float px, float min_px, int max_w,
                     int x, int base, int align, unsigned rgb)
{
    char cut[300];
    float p = gfx_fit_px(e->font, s, max_w, px, min_px);
    int w;
    gfx_ellipsize(e->font, p, s, max_w, cut, sizeof cut);
    w = gfx_text_width(e->font, p, cut);
    if (align == 0) gfx_text_center(e->g, e->font, p, x, base, cut, rgb);
    else gfx_text(e->g, e->font, p, align < 0 ? x : x - w, base, cut, rgb);
}

static void draw_footer(struct settings_env *e, const char *line)
{
    float s = S(e);
    text_fit(e, line, 28 * s, 18 * s, e->g->w - (int)(80 * s), e->g->w / 2, (int)(728 * s), 0,
             TH(e, FOOTER));
}

static void draw_list(struct state *st)
{
    struct settings_env *e = st->e;
    float s = S(e);
    int W = e->g->w, k;
    static const char *const TITLES[2] = { "COLOR CORRECTION", "BACK TO THE GAMES" };
    static const char *const SUBS[2] = { "How the screen shows each game's colors", "" };
    int rw = (int)(760 * s), rh = (int)(110 * s), x = (W - rw) / 2, y0 = (int)(220 * s);

    gfx_fill(e->g, TH(e, BACKGROUND));
    text_fit(e, "SETTINGS", 60 * s, 30 * s, W - (int)(80 * s), W / 2, (int)(96 * s), 0, TH(e, HEADING));
    for (k = 0; k < 2; k++) {
        int on = k == st->list_sel, y = y0 + k * (rh + (int)(30 * s));
        gfx_round_frame(e->g, x, y, rw, rh, (int)(22 * s), (int)((on ? 8 : 3) * s),
                        on ? TH(e, FRAME_HL) : TH(e, FRAME), on ? TH(e, CARD_HL) : TH(e, CARD));
        if (*SUBS[k]) {
            text_fit(e, TITLES[k], 40 * s, 24 * s, rw - (int)(60 * s), W / 2, y + (int)(52 * s), 0,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
            text_fit(e, SUBS[k], 24 * s, 18 * s, rw - (int)(60 * s), W / 2, y + (int)(88 * s), 0,
                     on ? TH(e, SUBTITLE_HL) : TH(e, SUBTITLE));
        } else {
            text_fit(e, TITLES[k], 40 * s, 24 * s, rw - (int)(60 * s), W / 2, y + (int)(70 * s), 0,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
        }
    }
    draw_footer(e, "LEFT / RIGHT FLIPPER: choose      START: open");
}

static const char *row_label(const struct state *st, const struct row *r)
{
    switch (r->kind) {
    case R_GAME: return "GAME";
    case R_PRESET: return "START FROM";
    case R_GAMMA: return r->ch == 0 ? "MIDDLE SHADES" : "";
    case R_GAIN: return r->ch == 0 ? "COLOR LEVEL" : "";
    case R_SAT: return "COLOR STRENGTH";
    case R_LIFT: return "DARKEST SHADES";
    case R_SAVE: return st->nimg > 1 ? "SAVE FOR THIS GAME" : "SAVE";
    case R_SAVE_ALL: return "SAVE FOR EVERY GAME";
    case R_LEAVE: return any_dirty(st) ? "LEAVE WITHOUT SAVING" : "BACK";
    }
    return "";
}

static void draw_colour(struct state *st)
{
    struct settings_env *e = st->e;
    const struct conf *c = e->c;
    float s = S(e);
    int W = e->g->w, img = st->imgs[st->cur], k;
    const struct colour *v = &st->work[img];
    int px = (int)(36 * s), pw = (int)(600 * s), y0 = (int)(124 * s);
    int rh = st->nrows > 12 ? (int)(39 * s) : (int)(42 * s);
    float tpx = 22 * s;
    char buf[300], val[120];

    gfx_fill(e->g, TH(e, BACKGROUND));
    text_fit(e, "COLOR CORRECTION", 46 * s, 28 * s, W - (int)(80 * s), W / 2, (int)(62 * s), 0,
             TH(e, HEADING));
    {
        int p = preset_of(st, &built_of(st, img)->built, img);
        const char *bn = built_of(st, img)->name;
        (void)p;
        snprintf(buf, sizeof buf, "%s  -  built with %s", c->img[img].title,
                 *bn ? bn : "a color profile of its own");
        text_fit(e, buf, 24 * s, 16 * s, W - (int)(80 * s), W / 2, (int)(100 * s), 0, TH(e, SUBTITLE));
    }

    for (k = 0; k < st->nrows; k++) {
        const struct row *r = &st->rows[k];
        int on = k == st->sel, y = y0 + k * rh, base = y + (int)(rh * 0.68f);
        int action = r->kind >= R_SAVE;
        if (action) y += (int)(10 * s), base += (int)(10 * s);
        if (on)
            gfx_round_frame(e->g, px, y + (int)(2 * s), pw, rh - (int)(4 * s), (int)(10 * s),
                            (int)((st->editing ? 5 : 3) * s), TH(e, FRAME_HL), TH(e, CARD_HL));
        else if (action)
            gfx_round_frame(e->g, px, y + (int)(2 * s), pw, rh - (int)(4 * s), (int)(10 * s),
                            (int)(2 * s), TH(e, FRAME), TH(e, CARD));
        if (action) {
            text_fit(e, row_label(st, r), tpx, 16 * s, pw - (int)(30 * s), px + pw / 2, base, 0,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
            continue;
        }
        text_fit(e, row_label(st, r), tpx, 16 * s, (int)(230 * s), px + (int)(16 * s), base, -1,
                 on ? TH(e, LABEL_HL) : TH(e, LABEL));
        if (r->kind == R_GAMMA || r->kind == R_GAIN) {
            int sq = (int)(14 * s);
            gfx_rect(e->g, px + (int)(252 * s), base - sq, sq, sq, CH_RGB[r->ch]);
            text_fit(e, CH_NAME[r->ch], tpx, 16 * s, (int)(100 * s), px + (int)(274 * s), base, -1,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
        }
        if (r->kind == R_GAME) {
            snprintf(val, sizeof val, "%s", c->img[img].title);
        } else if (r->kind == R_PRESET) {
            int p = on && st->editing ? st->preset_k : preset_of(st, v, img);
            snprintf(val, sizeof val, "%s", p == 0 ? "As built" : p > 0 ? PRESETS[p - 1].name
                                                                   : "Your own");
        } else {
            value_text(r, v, val, sizeof val);
        }
        if (on && st->editing) snprintf(buf, sizeof buf, "<  %s  >", val);
        else snprintf(buf, sizeof buf, "%s", val);
        {
            /* the value's room starts after the label, and after the channel
             * name on the rows that have one */
            int vx0 = r->kind == R_GAMMA || r->kind == R_GAIN ? (int)(380 * s) : (int)(250 * s);
            text_fit(e, buf, tpx, 14 * s, pw - vx0 - (int)(16 * s), px + pw - (int)(16 * s), base, 1,
                     on ? TH(e, TITLE_HL) : TH(e, SUBTITLE));
        }
    }

    /* THE TEST CARD, corrected with what the rows say now: the same maths the
     * game's shaders will run (colour.h), on the CPU */
    {
        int cx = (int)(672 * s), cy = (int)(124 * s), cw = W - cx - (int)(36 * s);
        int ch = cw * 400 / 640;
        struct colour_lut lut;
        if (cy + ch > (int)(600 * s)) {
            ch = (int)(600 * s) - cy;
            cw = ch * 640 / 400;
        }
        gfx_rect(e->g, cx, cy, cw, ch, 0x181818);       /* marks it dirty */
        colour_test_card(e->g->px, e->g->w * 4, cx, cy, cw, ch);
        colour_lut_build(&lut, v);
        colour_lut_apply(&lut, e->g->px + ((size_t)cy * (size_t)e->g->w + (size_t)cx) * 4, cw, ch,
                         e->g->w * 4);
        text_fit(e, "Test card, as this game will draw it", 22 * s, 16 * s, cw, cx + cw / 2,
                 cy + ch + (int)(34 * s), 0, TH(e, FOOTER));
        if (st->status[0])
            snprintf(buf, sizeof buf, "%s", st->status);
        else if (image_dirty(st, img))
            snprintf(buf, sizeof buf, "Changed, not saved yet");
        else if (st->has_saved[img])
            snprintf(buf, sizeof buf, "Set on this machine");
        else
            snprintf(buf, sizeof buf, "As built");
        text_fit(e, buf, 24 * s, 16 * s, cw, cx + cw / 2, cy + ch + (int)(72 * s), 0,
                 TH(e, TITLE_HL));
    }

    if (st->editing)
        draw_footer(e, "LEFT / RIGHT FLIPPER: less / more      START: done");
    else if (st->rows[st->sel].kind >= R_SAVE)
        draw_footer(e, "LEFT / RIGHT FLIPPER: move      START: do it");
    else
        draw_footer(e, "LEFT / RIGHT FLIPPER: move      START: change");
}

static void draw(struct state *st)
{
    if (st->screen == S_LIST) draw_list(st);
    else if (st->screen == S_COLOR) draw_colour(st);
}

/* ----------------------------------------------------------------- input */

static void click(struct state *st)
{
    struct settings_env *e = st->e;
    if (!e->au || !e->move) return;
    if (!audio_playing_clip(e->au, st->move_voice, e->move))
        st->move_voice = audio_play(e->au, e->move, 0);
}

/* START / ACTION / Select on the highlighted row */
static void activate(struct state *st)
{
    const struct conf *c = st->e->c;
    if (st->screen == S_LIST) {
        if (st->list_sel == 0) {
            st->screen = S_COLOR;
            colour_open(st);
        } else {
            sel_say("settings: back to the games");
            st->screen = S_DONE;
        }
        return;
    }
    switch (st->rows[st->sel].kind) {
    case R_SAVE: {
        int img = st->imgs[st->cur];
        if (save_image(st, img, &st->work[img]) == 0)
            snprintf(st->status, sizeof st->status, "Saved. %s starts with these colors next time.",
                     c->img[img].title);
        else
            snprintf(st->status, sizeof st->status, "Could not save: %s", strerror(errno));
        break;
    }
    case R_SAVE_ALL: {
        struct colour v = st->work[st->imgs[st->cur]];
        int k, bad = 0;
        for (k = 0; k < st->nimg; k++)
            if (save_image(st, st->imgs[k], &v) < 0) bad++;
        if (bad)
            snprintf(st->status, sizeof st->status, "Could not save %d of %d games", bad, st->nimg);
        else
            snprintf(st->status, sizeof st->status, "Saved for all %d games. They start with these colors next time.",
                     st->nimg);
        break;
    }
    case R_LEAVE:
        if (any_dirty(st)) sel_say("settings: left color correction, unsaved changes dropped");
        else sel_say("settings: left color correction");
        st->screen = S_LIST;
        break;
    default:
        st->editing = 1;
        st->status[0] = 0;
        if (st->rows[st->sel].kind == R_PRESET) {
            int img = st->imgs[st->cur], k = preset_of(st, &st->work[img], img);
            st->preset_k = k < 0 ? 0 : k;
        }
        break;
    }
}

static void key(struct state *st, int ev, long long now)
{
    int dir = (ev == EV_LEFT || ev == EV_MINUS) ? -1 : (ev == EV_RIGHT || ev == EV_PLUS) ? 1 : 0;
    int go = ev == EV_START || ev == EV_ACTION || ev == EV_SELECT;
    if (st->screen == S_LIST) {
        if (dir) { st->list_sel = (st->list_sel + 2 + dir) % 2; click(st); }
        else if (go) activate(st);
        return;
    }
    if (st->editing) {
        if (dir) {
            if (step_row(st, dir)) click(st);
            st->hold_ev = ev;
            st->next_rep = now + REPEAT_AFTER_MS;
        } else if (go) {
            int img = st->imgs[st->cur];
            char vals[200];
            st->editing = 0;
            st->hold_ev = 0;
            colour_format(&st->work[img], vals, sizeof vals);
            sel_log("color: image %d now %s", img, vals);
        }
        return;
    }
    if (dir) {
        st->sel = (st->sel + st->nrows + dir) % st->nrows;
        st->status[0] = 0;
        click(st);
    } else if (go) {
        activate(st);
    }
}

/* PAD_SETTINGS_IDLE_MS shortens the idle exit, FOR THE TESTS: two minutes is
 * the right wait on a machine and far too long for a test to sit through */
static long long idle_ms(void)
{
    const char *forced = getenv("PAD_SETTINGS_IDLE_MS");
    if (forced && *forced) {
        long ms = strtol(forced, NULL, 10);
        if (ms > 0) return (long long)ms;
    }
    return SETTINGS_IDLE_MS;
}

void settings_run(struct settings_env *e)
{
    struct state st;
    long long last, idle = idle_ms();
    int ev;
    memset(&st, 0, sizeof st);
    st.e = e;
    st.screen = S_LIST;
    st.move_voice = -1;
    sel_say("settings: open");
    draw(&st);
    last = sel_now_ms();
    while (!*e->stop && st.screen != S_DONE) {
        long long now = sel_now_ms();
        int dirty = 0;
        while ((ev = input_poll(e->in, now)) != EV_NONE) {
            if (ev >= EV_RAW_BASE) continue;
            sel_say("key: %s", input_event_name(ev));
            if (ev == EV_BACK) continue;        /* ignored, as in the menu */
            key(&st, ev, now);
            last = now;
            dirty = 1;
            if (st.screen == S_DONE) break;
        }
        if (st.screen == S_DONE) break;
        /* A HELD FLIPPER REPEATS while a value is being changed: the gamma of
         * one channel is 40 presses from end to end */
        if (st.editing && st.hold_ev) {
            if (!input_held(e->in, st.hold_ev)) {
                st.hold_ev = 0;
            } else if (now >= st.next_rep) {
                int dir = (st.hold_ev == EV_LEFT || st.hold_ev == EV_MINUS) ? -1 : 1;
                if (step_row(&st, dir)) { click(&st); dirty = 1; }
                st.next_rep = now - st.next_rep > REPEAT_EVERY_MS ? now + REPEAT_EVERY_MS
                                                                   : st.next_rep + REPEAT_EVERY_MS;
                last = now;
            }
        }
        if (now - last > idle) {
            sel_say("settings: nothing pressed for %lld s: back to the games%s", idle / 1000,
                    st.screen == S_COLOR && any_dirty(&st) ? ", unsaved changes dropped" : "");
            break;
        }
        audio_pump(e->au, now);
        if (dirty) draw(&st);
        e->present(e->ctx);
    }
    sel_say("settings: closed");
}

int settings_snapshot(struct settings_env *e, const char *screen, int row, int editing,
                      char *why, int whylen)
{
    struct state st;
    memset(&st, 0, sizeof st);
    st.e = e;
    st.move_voice = -1;
    if (!strcmp(screen, "settings")) {
        st.screen = S_LIST;
        st.list_sel = row >= 0 && row < 2 ? row : 0;
    } else if (!strcmp(screen, "color")) {
        if (e->c->ncolour < 1) {
            snprintf(why, (size_t)whylen, "--screen color: this conf has no color_profile= line");
            return -1;
        }
        st.screen = S_COLOR;
        colour_open(&st);
        st.sel = row >= 0 && row < st.nrows ? row : 0;
        st.editing = editing && st.rows[st.sel].kind < R_SAVE;
    } else {
        snprintf(why, (size_t)whylen, "--screen %s: not settings or color", screen);
        return -1;
    }
    draw(&st);
    return 0;
}
