/* colour.h - the colour correction a Spike 2 game draws through (PAD-305), as
 * the boot menu's Settings > Color correction adjusts it on the machine
 * (PAD-307).
 *
 * WHERE THE NUMBERS LIVE.  A build with a colour profile rewrites the game's
 * drawing shaders to pass every pixel through pad_cp(), with the profile's
 * numbers as GLSL literals in ONE fixed shape (shader_profile.py's
 * TUNABLE_TEMPLATE, mirrored in colour.c): thirteen eight-character slots per
 * function.  images.conf names the numbers each image was BUILT with
 * (color=<image>|...); the operator's own go to a small file on /data
 * (DEF_COLOUR_FILE, one line per image device), and the boot hook
 * (select.sh) has this program copy the chosen image's game program into RAM
 * with the slots rewritten (--apply-color) and binds the copy over the
 * original.  Nothing on the card's game trees is ever written.
 *
 * THE MATHS are the profile's (core/colour_profile.py):
 *   1. saturation: each pixel mixed toward its Rec.601 grey (1 = unchanged)
 *   2. per channel: out = lift + (1 - lift) * clip(in * gain) ^ gamma
 */
#ifndef CODESELECT_COLOUR_H
#define CODESELECT_COLOUR_H

struct colour {
    float gamma[3], gain[3], lift[3], sat;
};

/* The ranges the menu's controls move in: the Color profile tab's own
 * (webui/tabs/color.py LIMITS), so a profile made on the PC and one made on
 * the machine are the same kind of thing.  What a conf or the values file
 * may hold is the profile file's wider range (colour_valid). */
#define COLOUR_GAMMA_MIN 0.50f
#define COLOUR_GAMMA_MAX 2.50f
#define COLOUR_GAIN_MIN  0.50f
#define COLOUR_GAIN_MAX  1.50f
#define COLOUR_LIFT_MIN  0.00f
#define COLOUR_LIFT_MAX  0.30f
#define COLOUR_SAT_MIN   0.00f
#define COLOUR_SAT_MAX   2.00f

void colour_identity(struct colour *c);
/* equal as the shader spells them (%.6f), which is what decides whether a
 * copy of the program would differ from the one on the card */
int  colour_equal(const struct colour *a, const struct colour *b);
/* 0 when every number is inside the profile file's range (colour_profile.parse:
 * gamma 0.1-5, gain 0-4, lift 0-0.9, saturation 0-4), else -1 with why */
int  colour_valid(const struct colour *c, char *why, int whylen);

/* "<gamma r g b>|<gain r g b>|<lift r g b>|<saturation>" - the four fields of
 * an images.conf color= line after its index, and of a values-file line
 * after its device.  colour_parse takes the four fields already split; 0 ok,
 * -1 with why.  colour_format writes them back (%.4f). */
int  colour_parse(char *const fld[4], struct colour *out, char *why, int whylen);
void colour_format(const struct colour *c, char *out, int outlen);

/* THE PREVIEW: the correction applied on the CPU to pixels already drawn on
 * the menu's canvas (RGBA, `stride` bytes a row), the same maths the shader
 * runs on the GPU. */
struct colour_lut {
    unsigned char t[3][256];
    float sat;
};
void colour_lut_build(struct colour_lut *l, const struct colour *c);
void colour_lut_apply(const struct colour_lut *l, unsigned char *px, int w, int h, int stride);

/* THE OPERATOR'S VALUES (DEF_COLOUR_FILE on /data).  One line per image:
 *   <device>|<gamma r g b>|<gain r g b>|<lift r g b>|<saturation>
 * with '#' comments.  colour_file_get: 1 = a line for `device` (into *out),
 * 0 = none (or the file is missing), a bad line is skipped.  colour_file_put
 * rewrites the file atomically (tmp + fsync + rename) with `device`'s line
 * replaced by *c, or removed when c is NULL; every other device's line is
 * kept as it was.  0 ok, -1 with errno. */
int  colour_file_get(const char *path, const char *device, struct colour *out);
int  colour_file_put(const char *path, const char *device, const struct colour *c);

/* THE APPLY STEP (--apply-color): copy `program` to `out` with every pad_cp
 * slot rewritten to *c.  Refused - nothing left at `out` - when the program
 * carries no pad_cp, when any pad_cp is not in the fixed shape, or when the
 * RAM it would take is not there.  Returns the number of functions rewritten
 * (> 0), or -1 with the reason in msg. */
int  colour_apply_program(const char *program, const char *out, const struct colour *c,
                          char *msg, int msglen);

/* THE TEST CARD the screen shows corrected: the Color profile tab's own
 * (webui/tabs/color.py test_card_png) - grey steps, full and half colours,
 * dark sea tones, skin tones and a smooth ramp, the shades a display gets
 * wrong first - drawn into the RGBA buffer at x, y, w x h. */
void colour_test_card(unsigned char *px, int stride, int x, int y, int w, int h);

#endif
