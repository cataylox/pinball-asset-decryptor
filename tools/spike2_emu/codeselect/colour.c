/* colour.c - see colour.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include "colour.h"

/* THE ONE SHAPE pad_cp's numbers are written in (shader_profile.py's
 * TUNABLE_TEMPLATE - tests/test_stern_shader_profile.py holds the two to the
 * same bytes).  Each '#' run is an eight-character slot, "d.dddddd"; in order:
 * saturation, gain r g b, gamma r g b, lift r g b, lift r g b again (the lift
 * statement names its vector twice). */
static const char TUNABLE_TEMPLATE[] =
    "c=mix(vec3(dot(c,vec3(0.299,0.587,0.114))),c,########);"
    "c=pow(clamp(c*vec3(########,########,########),0.0,1.0),"
    "vec3(########,########,########));"
    "c=vec3(########,########,########)+(vec3(1.0)-vec3(########,########,########))*c;";
#define SLOT 8
#define NSLOTS 13
#define SLOT_MAX 9.999999f
/* a definition, never a call: the call site reads "= pad_cp(" */
static const char PAD_CP_DEF[] = "vec4 pad_cp(";
/* RAM the game still needs once its program sits in RAM as well */
#define RAM_MARGIN (96u << 20)

static const float LUMA[3] = { 0.299f, 0.587f, 0.114f };

void colour_identity(struct colour *c)
{
    int k;
    for (k = 0; k < 3; k++) {
        c->gamma[k] = 1.0f;
        c->gain[k] = 1.0f;
        c->lift[k] = 0.0f;
    }
    c->sat = 1.0f;
}

static void slot_text(float v, char out[SLOT + 1])
{
    char buf[32];
    if (!(v >= 0.0f)) v = 0.0f;          /* NaN too */
    if (v > SLOT_MAX) v = SLOT_MAX;
    snprintf(buf, sizeof buf, "%.6f", (double)v);
    memcpy(out, buf, SLOT);
    out[SLOT] = 0;
}

/* the thirteen slot values, in the template's order */
static void slot_values(const struct colour *c, float v[NSLOTS])
{
    int k;
    v[0] = c->sat;
    for (k = 0; k < 3; k++) {
        v[1 + k] = c->gain[k];
        v[4 + k] = c->gamma[k];
        v[7 + k] = c->lift[k];
        v[10 + k] = c->lift[k];
    }
}

int colour_equal(const struct colour *a, const struct colour *b)
{
    float va[NSLOTS], vb[NSLOTS];
    char sa[SLOT + 1], sb[SLOT + 1];
    int k;
    slot_values(a, va);
    slot_values(b, vb);
    for (k = 0; k < NSLOTS; k++) {
        slot_text(va[k], sa);
        slot_text(vb[k], sb);
        if (strcmp(sa, sb)) return 0;
    }
    return 1;
}

static int in_range(float v, float lo, float hi)
{
    return v >= lo && v <= hi;      /* false for NaN */
}

int colour_valid(const struct colour *c, char *why, int whylen)
{
    int k;
    for (k = 0; k < 3; k++) {
        if (!in_range(c->gamma[k], 0.1f, 5.0f)) {
            snprintf(why, (size_t)whylen, "gamma must be between 0.1 and 5");
            return -1;
        }
        if (!in_range(c->gain[k], 0.0f, 4.0f)) {
            snprintf(why, (size_t)whylen, "gain must be between 0 and 4");
            return -1;
        }
        if (!in_range(c->lift[k], 0.0f, 0.9f)) {
            snprintf(why, (size_t)whylen, "lift must be between 0 and 0.9");
            return -1;
        }
    }
    if (!in_range(c->sat, 0.0f, 4.0f)) {
        snprintf(why, (size_t)whylen, "saturation must be between 0 and 4");
        return -1;
    }
    return 0;
}

/* one to three numbers, space- or comma-separated; one number is all three */
static int parse_nums(const char *s, float *out, int want)
{
    float v[3];
    int n = 0;
    const char *p = s;
    while (*p && n < 3) {
        char *e;
        while (*p == ' ' || *p == '\t' || *p == ',') p++;
        if (!*p) break;
        v[n] = strtof(p, &e);
        if (e == p) return -1;
        n++;
        p = e;
    }
    while (*p == ' ' || *p == '\t' || *p == ',') p++;
    if (*p) return -1;
    if (n == 1 && want == 3) { v[1] = v[2] = v[0]; n = 3; }
    if (n != want) return -1;
    memcpy(out, v, sizeof(float) * (size_t)want);
    return 0;
}

int colour_parse(char *const fld[4], struct colour *out, char *why, int whylen)
{
    static const char *const NAMES[4] = { "gamma", "gain", "lift", "saturation" };
    struct colour c;
    float *dst[4];
    int k;
    dst[0] = c.gamma;
    dst[1] = c.gain;
    dst[2] = c.lift;
    dst[3] = &c.sat;
    for (k = 0; k < 4; k++) {
        if (!fld[k] || parse_nums(fld[k], dst[k], k == 3 ? 1 : 3) < 0) {
            snprintf(why, (size_t)whylen, "%s needs %s number%s", NAMES[k],
                     k == 3 ? "one" : "three", k == 3 ? "" : "s");
            return -1;
        }
    }
    if (colour_valid(&c, why, whylen) < 0) return -1;
    *out = c;
    return 0;
}

void colour_format(const struct colour *c, char *out, int outlen)
{
    snprintf(out, (size_t)outlen, "%.4f %.4f %.4f|%.4f %.4f %.4f|%.4f %.4f %.4f|%.4f",
             (double)c->gamma[0], (double)c->gamma[1], (double)c->gamma[2],
             (double)c->gain[0], (double)c->gain[1], (double)c->gain[2],
             (double)c->lift[0], (double)c->lift[1], (double)c->lift[2], (double)c->sat);
}

/* ----------------------------------------------------------------- preview */

void colour_lut_build(struct colour_lut *l, const struct colour *c)
{
    int ch, v;
    for (ch = 0; ch < 3; ch++) {
        double g = c->gamma[ch], k = c->gain[ch], lo = c->lift[ch];
        for (v = 0; v < 256; v++) {
            double x = v / 255.0 * k, y;
            if (x < 0) x = 0;
            if (x > 1) x = 1;
            y = lo + (1.0 - lo) * pow(x, g);
            y = y * 255.0 + 0.5;
            l->t[ch][v] = (unsigned char)(y < 0 ? 0 : y > 255 ? 255 : y);
        }
    }
    l->sat = c->sat;
}

static unsigned char clamp8(float v)
{
    v += 0.5f;
    return (unsigned char)(v < 0 ? 0 : v > 255 ? 255 : v);
}

void colour_lut_apply(const struct colour_lut *l, unsigned char *px, int w, int h, int stride)
{
    int x, y;
    int plain = fabsf(l->sat - 1.0f) < 1e-6f;
    for (y = 0; y < h; y++) {
        unsigned char *p = px + (size_t)y * (size_t)stride;
        for (x = 0; x < w; x++, p += 4) {
            if (plain) {
                p[0] = l->t[0][p[0]];
                p[1] = l->t[1][p[1]];
                p[2] = l->t[2][p[2]];
            } else {
                float luma = LUMA[0] * p[0] + LUMA[1] * p[1] + LUMA[2] * p[2];
                unsigned char r = clamp8(luma + l->sat * (p[0] - luma));
                unsigned char g = clamp8(luma + l->sat * (p[1] - luma));
                unsigned char b = clamp8(luma + l->sat * (p[2] - luma));
                p[0] = l->t[0][r];
                p[1] = l->t[1][g];
                p[2] = l->t[2][b];
            }
        }
    }
}

/* -------------------------------------------------------------- the file */

static char *trim(char *s)
{
    char *e;
    while (*s && isspace((unsigned char)*s)) s++;
    e = s + strlen(s);
    while (e > s && isspace((unsigned char)e[-1])) *--e = 0;
    return s;
}

/* a values-file line: "<device>|<four fields>" -> the device (trimmed, in
 * place) and the colour; 0 ok, -1 not a usable line */
static int parse_line(char *line, char **device, struct colour *c)
{
    char *s = trim(line), *fld[4], *p, why[120];
    int k;
    if (!*s || *s == '#') return -1;
    p = strchr(s, '|');
    if (!p) return -1;
    *p++ = 0;
    *device = trim(s);
    for (k = 0; k < 4; k++) {
        fld[k] = p;
        if (p) {
            char *bar = strchr(p, '|');
            if (bar) *bar++ = 0;
            fld[k] = trim(p);
            p = bar;
        }
    }
    return colour_parse(fld, c, why, sizeof why);
}

int colour_file_get(const char *path, const char *device, struct colour *out)
{
    FILE *f;
    char line[512];
    int found = 0;
    if (!path || !*path) return 0;
    f = fopen(path, "r");
    if (!f) return 0;
    while (fgets(line, sizeof line, f)) {
        char *dev;
        struct colour c;
        if (parse_line(line, &dev, &c) == 0 && !strcmp(dev, device)) {
            *out = c;
            found = 1;              /* the LAST line for a device wins */
        }
    }
    fclose(f);
    return found;
}

#define FILE_MAX_LINES 128

int colour_file_put(const char *path, const char *device, const struct colour *c)
{
    char keep[FILE_MAX_LINES][512], tmp[600], line[512], vals[200];
    int nkeep = 0, k, e;
    FILE *f;
    if (!path || !*path) { errno = EINVAL; return -1; }
    f = fopen(path, "r");
    if (f) {
        while (fgets(line, sizeof line, f) && nkeep < FILE_MAX_LINES) {
            char copy[512], *dev;
            struct colour other;
            snprintf(copy, sizeof copy, "%s", line);
            if (parse_line(copy, &dev, &other) < 0 || !strcmp(dev, device)) continue;
            snprintf(keep[nkeep++], sizeof keep[0], "%s", trim(line));
        }
        fclose(f);
    }
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    f = fopen(tmp, "w");
    if (!f) return -1;
    fprintf(f, "# Color correction set on this machine in the boot menu (Settings > Color correction).\n"
               "# <image device>|<gamma r g b>|<gain r g b>|<lift r g b>|<saturation>\n"
               "# An image with no line here draws with the colors it was built with.\n");
    for (k = 0; k < nkeep; k++) fprintf(f, "%s\n", keep[k]);
    if (c) {
        colour_format(c, vals, sizeof vals);
        fprintf(f, "%s|%s\n", device, vals);
    }
    if (fflush(f) != 0 || fsync(fileno(f)) != 0) { /* fsync may fail on odd fs: tolerate */ }
    if (fclose(f) != 0) { e = errno; unlink(tmp); errno = e; return -1; }
    if (rename(tmp, path) != 0) { e = errno; unlink(tmp); errno = e; return -1; }
    /* the rename itself, to the card: a power cut right after Save must not
     * bring the old values back */
    {
        char dir[600], *slash;
        int fd;
        snprintf(dir, sizeof dir, "%s", path);
        slash = strrchr(dir, '/');
        if (slash) {
            if (slash == dir) slash[1] = 0;
            else *slash = 0;
            fd = open(dir, O_RDONLY);
            if (fd >= 0) { fsync(fd); close(fd); }
        }
    }
    return 0;
}

/* ------------------------------------------------------------ apply step */

/* bytes of RAM free for a new tmpfs file: MemAvailable, else MemFree +
 * Cached; 0 when /proc/meminfo cannot say (then nothing is refused) */
static unsigned long long ram_available(void)
{
    FILE *f = fopen("/proc/meminfo", "r");
    char line[128];
    unsigned long long avail = 0, freek = 0, cached = 0, v;
    if (!f) return 0;
    while (fgets(line, sizeof line, f)) {
        if (sscanf(line, "MemAvailable: %llu", &v) == 1) avail = v;
        else if (sscanf(line, "MemFree: %llu", &v) == 1) freek = v;
        else if (sscanf(line, "Cached: %llu", &v) == 1) cached = v;
    }
    fclose(f);
    return (avail ? avail : freek + cached) * 1024ull;
}

/* does the template match at p (n bytes left)?  Fills slot[] with the offset
 * of each slot from p. */
static int template_at(const unsigned char *p, size_t n, size_t slot[NSLOTS])
{
    size_t tl = sizeof TUNABLE_TEMPLATE - 1, i;
    int ns = 0;
    if (n < tl) return 0;
    for (i = 0; i < tl; ) {
        if (TUNABLE_TEMPLATE[i] == '#') {
            int k;
            for (k = 0; k < SLOT; k++) {
                unsigned char ch = p[i + (size_t)k];
                if (k == 1 ? ch != '.' : !isdigit(ch)) return 0;
            }
            if (ns < NSLOTS) slot[ns] = i;
            ns++;
            i += SLOT;
        } else {
            if (p[i] != (unsigned char)TUNABLE_TEMPLATE[i]) return 0;
            i++;
        }
    }
    return ns == NSLOTS;
}

static size_t count_defs(const unsigned char *m, size_t n)
{
    size_t defs = 0, dl = sizeof PAD_CP_DEF - 1;
    const unsigned char *p = m, *end = m + n;
    while (p < end) {
        const unsigned char *h = memmem(p, (size_t)(end - p), PAD_CP_DEF, dl);
        if (!h) break;
        defs++;
        p = h + dl;
    }
    return defs;
}

static int copy_file(int in, int out)
{
    static unsigned char buf[1 << 20];
    for (;;) {
        ssize_t r = read(in, buf, sizeof buf), w = 0;
        if (r < 0) { if (errno == EINTR) continue; return -1; }
        if (r == 0) return 0;
        while (w < r) {
            ssize_t k = write(out, buf + w, (size_t)(r - w));
            if (k < 0) { if (errno == EINTR) continue; return -1; }
            w += k;
        }
    }
}

int colour_apply_program(const char *program, const char *out, const struct colour *c,
                         char *msg, int msglen)
{
    char tmp[600], slots[NSLOTS][SLOT + 1];
    float vals[NSLOTS];
    struct stat st;
    unsigned long long ram;
    unsigned char *m = MAP_FAILED;
    size_t prefix, defs, n = 0, k;
    int in = -1, fd = -1, rc = -1, i;
    const unsigned char *pfx;

    errno = 0;
    if (stat(program, &st) < 0 || !S_ISREG(st.st_mode)) {
        snprintf(msg, (size_t)msglen, "%s: %s", program, errno ? strerror(errno) : "not a regular file");
        return -1;
    }
    ram = ram_available();
    if (ram && (unsigned long long)st.st_size + RAM_MARGIN > ram) {
        snprintf(msg, (size_t)msglen, "%s is %lld MB and only %llu MB of RAM is free: "
                 "the game keeps the colors it was built with", program,
                 (long long)st.st_size >> 20, ram >> 20);
        return -1;
    }
    slot_values(c, vals);
    for (i = 0; i < NSLOTS; i++) slot_text(vals[i], slots[i]);
    snprintf(tmp, sizeof tmp, "%s.tmp", out);
    in = open(program, O_RDONLY);
    if (in < 0) { snprintf(msg, (size_t)msglen, "open %s: %s", program, strerror(errno)); goto done; }
    fd = open(tmp, O_RDWR | O_CREAT | O_TRUNC, 0700);
    if (fd < 0) { snprintf(msg, (size_t)msglen, "create %s: %s", tmp, strerror(errno)); goto done; }
    if (copy_file(in, fd) < 0) { snprintf(msg, (size_t)msglen, "copy to %s: %s", tmp, strerror(errno)); goto done; }
    close(in);
    in = -1;
    if (st.st_size <= 0) { snprintf(msg, (size_t)msglen, "%s is empty", program); goto done; }
    m = mmap(NULL, (size_t)st.st_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (m == MAP_FAILED) { snprintf(msg, (size_t)msglen, "map %s: %s", tmp, strerror(errno)); goto done; }
    defs = count_defs(m, (size_t)st.st_size);
    if (!defs) {
        snprintf(msg, (size_t)msglen, "%s carries no color profile to adjust", program);
        goto done;
    }
    /* every template, found by its fixed opening up to the first slot */
    prefix = (size_t)(strchr(TUNABLE_TEMPLATE, '#') - TUNABLE_TEMPLATE);
    pfx = m;
    while (pfx < m + st.st_size) {
        size_t at[NSLOTS];
        const unsigned char *h = memmem(pfx, (size_t)(m + st.st_size - pfx),
                                        TUNABLE_TEMPLATE, prefix);
        if (!h) break;
        if (template_at(h, (size_t)(m + st.st_size - h), at)) {
            for (k = 0; k < NSLOTS; k++) memcpy((unsigned char *)h + at[k], slots[k], SLOT);
            n++;
            pfx = h + sizeof TUNABLE_TEMPLATE - 1;
        } else {
            pfx = h + prefix;
        }
    }
    /* ALL OR NOTHING: a program whose shaders disagreed with each other after
     * this would draw half its screen one way and half the other */
    if (n != defs) {
        snprintf(msg, (size_t)msglen, "%s has %zu color function(s) and %zu in the adjustable shape "
                 "(built before the shape was fixed?): left as it is", program, defs, n);
        goto done;
    }
    if (msync(m, (size_t)st.st_size, MS_SYNC) < 0) {
        snprintf(msg, (size_t)msglen, "write %s: %s", tmp, strerror(errno));
        goto done;
    }
    if (fchmod(fd, st.st_mode & 07777) < 0) {
        snprintf(msg, (size_t)msglen, "chmod %s: %s", tmp, strerror(errno));
        goto done;
    }
    munmap(m, (size_t)st.st_size);
    m = MAP_FAILED;
    if (close(fd) < 0) { fd = -1; snprintf(msg, (size_t)msglen, "close %s: %s", tmp, strerror(errno)); goto done; }
    fd = -1;
    if (rename(tmp, out) < 0) { snprintf(msg, (size_t)msglen, "rename to %s: %s", out, strerror(errno)); goto done; }
    snprintf(msg, (size_t)msglen, "%zu color function(s) rewritten in a %lld-byte copy", n,
             (long long)st.st_size);
    rc = (int)n;
done:
    if (m != MAP_FAILED) munmap(m, (size_t)st.st_size);
    if (fd >= 0) close(fd);
    if (in >= 0) close(in);
    if (rc < 0) unlink(tmp);
    return rc;
}

/* -------------------------------------------------------------- test card */

static void card_rect(unsigned char *px, int stride, int ox, int oy, double sx, double sy,
                      double x0, double y0, double x1, double y1, int r, int g, int b)
{
    int X0 = ox + (int)(x0 * sx + 0.5), Y0 = oy + (int)(y0 * sy + 0.5);
    int X1 = ox + (int)(x1 * sx + 0.5), Y1 = oy + (int)(y1 * sy + 0.5);
    int x, y;
    for (y = Y0; y < Y1; y++) {
        unsigned char *p = px + (size_t)y * (size_t)stride + (size_t)X0 * 4;
        for (x = X0; x < X1; x++, p += 4) {
            p[0] = (unsigned char)r;
            p[1] = (unsigned char)g;
            p[2] = (unsigned char)b;
            p[3] = 255;
        }
    }
}

void colour_test_card(unsigned char *px, int stride, int x, int y, int w, int h)
{
    /* drawn on the tab's own 640 x 400 grid, scaled */
    static const int greys[16] = { 0, 8, 16, 24, 32, 48, 64, 80, 96, 112, 128, 160, 192, 224, 240, 255 };
    static const int full[6][3] = { {255, 0, 0}, {0, 255, 0}, {0, 0, 255}, {0, 255, 255},
                                    {255, 0, 255}, {255, 255, 0} };
    static const int sea[6][3] = { {8, 24, 40}, {8, 32, 56}, {12, 48, 80}, {16, 64, 104},
                                   {24, 80, 128}, {32, 96, 152} };
    static const int skin[6][3] = { {255, 224, 196}, {234, 192, 160}, {198, 145, 110},
                                    {160, 105, 75}, {110, 70, 50}, {70, 45, 32} };
    double sx = w / 640.0, sy = h / 400.0, cw = 608, step;
    int i;
    card_rect(px, stride, x, y, sx, sy, 0, 0, 640, 400, 24, 24, 24);
    step = cw / 16;
    for (i = 0; i < 16; i++)
        card_rect(px, stride, x, y, sx, sy, 16 + i * step, 16, 16 + (i + 1) * step, 76,
                  greys[i], greys[i], greys[i]);
    step = cw / 6;
    for (i = 0; i < 6; i++) {
        card_rect(px, stride, x, y, sx, sy, 16 + i * step, 88, 16 + (i + 1) * step, 138,
                  full[i][0], full[i][1], full[i][2]);
        card_rect(px, stride, x, y, sx, sy, 16 + i * step, 140, 16 + (i + 1) * step, 190,
                  full[i][0] / 2, full[i][1] / 2, full[i][2] / 2);
        card_rect(px, stride, x, y, sx, sy, 16 + i * step, 202, 16 + (i + 1) * step, 250,
                  sea[i][0], sea[i][1], sea[i][2]);
        card_rect(px, stride, x, y, sx, sy, 16 + i * step, 254, 16 + (i + 1) * step, 302,
                  skin[i][0], skin[i][1], skin[i][2]);
    }
    /* the smooth ramp, one column per canvas pixel */
    {
        int X0 = x + (int)(16 * sx + 0.5), X1 = x + (int)((16 + cw) * sx + 0.5);
        int Y0 = y + (int)(314 * sy + 0.5), Y1 = y + (int)(384 * sy + 0.5), xx, yy;
        for (xx = X0; xx < X1; xx++) {
            int v = X1 - X0 > 1 ? (int)((double)(xx - X0) * 255.0 / (X1 - X0 - 1) + 0.5) : 0;
            for (yy = Y0; yy < Y1; yy++) {
                unsigned char *p = px + (size_t)yy * (size_t)stride + (size_t)xx * 4;
                p[0] = p[1] = p[2] = (unsigned char)v;
                p[3] = 255;
            }
        }
    }
}
