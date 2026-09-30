/*
 * cgcshim.c - the hardware of a Chicago Gaming BeagleBone game, for a run
 * under qemu-arm on a PC (tools/cgc_emu, PAD-273).
 *
 * LD_PRELOADed into the machine's own program (emumm for Medieval Madness,
 * pin for Cactus Canyon...), inside the machine's own armhf libraries.  The
 * program is a WPC-95 emulator: a 6809 running the Williams ROM, CGC's
 * colour screen and sound on top.  On the machine it talks to its boards by
 * poking registers through /dev/mem (McSPI to the playfield, four GPIO banks
 * bit-banging the backbox bus) and draws with libdrm dumb buffers on
 * /dev/dri/card0.  None of that exists here, so:
 *
 *   /dev/mem           -> /dev/zero, and a map of it plain anonymous
 *                         memory (a register offset past a /dev/zero
 *                         object's end would be SIGBUS)
 *   /dev/spidev1.0     -> /dev/null, its ioctls answered 0
 *   /dev/input/event1  -> /dev/null (the service keyboard; nothing to read)
 *   /dev/dri/card0     -> $CGC_FB, a file: a header and the three RGB565
 *                         frame buffers the game draws in.  The drm* calls
 *                         are answered here (one 1280x768 panel); a page
 *                         flip writes the shown buffer's index in the
 *                         header, and the rig's viewer / shot.py read it.
 *
 * The board traffic itself is cut at the function the program names it by:
 * `io` (backbox + playfield exchange, once per millisecond) and `spi_init`
 * return "ok" without touching a register, found by name in the program's
 * own symbol table (CGC ships them unstripped).  Switches are then the
 * program's own switch state, which only this shim writes: a thread reads
 * $CGC_CTL (a FIFO) for
 *
 *   sw <n> <0|1>            playfield matrix switch n (WPC numbering, 11..88)
 *                           closed / open, whatever its wiring
 *   pf <n> <0|1>            the same switch's raw matrix value
 *   sys <bank> <bit> <0|1>  coin door (bank 0: D1..D8) / flipper (bank 1)
 *   plunge, drain, hole <n>, balls reset   the ball model (below)
 *
 * The FRAM (the game's NVRAM) is modelled at the program's spi_* byte
 * exchange and kept in $CGC_NV (see "the FRAM" below).
 *
 * The shim writes $CGC_STATE every 50 ms: switches, lamps and solenoids as the
 * program holds them, for the rig's ball model and switch window.
 *
 * Built against the machine's own glibc (2.13): see build.sh.
 */
/* _DEFAULT_SOURCE, not _GNU_SOURCE: glibc 2.38+ headers under _GNU_SOURCE
 * send sscanf/strtol to __isoc23_* names the machine's 2.13 lacks. */
#define _DEFAULT_SOURCE
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/ucontext.h>
#include <unistd.h>

#ifndef RTLD_NEXT
#define RTLD_NEXT ((void *)-1l)
#endif

/* ---------------------------------------------------------------- log -- */

static FILE *logf_;
static void slog(const char *fmt, ...)
{
    va_list ap;
    if (!logf_) {
        const char *p = getenv("CGC_LOG");
        logf_ = p ? fopen(p, "a") : NULL;
        if (!logf_) logf_ = stderr;
        setvbuf(logf_, NULL, _IOLBF, 0);
    }
    fprintf(logf_, "cgcshim: ");
    va_start(ap, fmt);
    vfprintf(logf_, fmt, ap);
    va_end(ap);
    fputc('\n', logf_);
}

/* ----------------------------------------------- the program's symbols -- */

typedef struct { char name[48]; uint32_t addr; } sym_t;
static sym_t syms[64];
static int nsyms;

/* Every FUNC symbol of the running program whose name is in `want`. */
static void find_syms(const char *const *want)
{
    int fd = open("/proc/self/exe", O_RDONLY);
    if (fd < 0) { slog("cannot open /proc/self/exe"); return; }
    off_t size = lseek(fd, 0, SEEK_END);
    uint8_t *m = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (m == MAP_FAILED) return;
    Elf32_Ehdr *eh = (Elf32_Ehdr *)m;
    Elf32_Shdr *sh = (Elf32_Shdr *)(m + eh->e_shoff);
    for (int i = 0; i < eh->e_shnum; i++) {
        if (sh[i].sh_type != SHT_SYMTAB) continue;
        Elf32_Sym *s = (Elf32_Sym *)(m + sh[i].sh_offset);
        const char *str = (const char *)(m + sh[sh[i].sh_link].sh_offset);
        int n = sh[i].sh_size / sizeof(Elf32_Sym);
        for (int k = 0; k < n; k++) {
            if (ELF32_ST_TYPE(s[k].st_info) != STT_FUNC || !s[k].st_value) continue;
            const char *nm = str + s[k].st_name;
            for (int w = 0; want[w]; w++) {
                if (strcmp(nm, want[w]) == 0 && nsyms < 64) {
                    snprintf(syms[nsyms].name, sizeof syms[0].name, "%s", nm);
                    syms[nsyms++].addr = s[k].st_value;
                }
            }
        }
    }
    munmap(m, size);
}

static uint32_t sym(const char *name)
{
    for (int i = 0; i < nsyms; i++)
        if (strcmp(syms[i].name, name) == 0) return syms[i].addr;
    return 0;
}

/* Rewrite the first bytes of function `name`: either "return val" at once,
 * or (fn != NULL) a jump to fn here, which takes the same arguments.  Both
 * Thumb and ARM entries (a symbol's bit 0).  The program is not PIE and its
 * text is its own private mapping, so this is the program only. */
static int patch(const char *name, int val, void *fn)
{
    uint32_t a = sym(name);
    if (!a) return 0;
    long pg = sysconf(_SC_PAGESIZE);
    uintptr_t p = a & ~1u, base = p & ~(uintptr_t)(pg - 1);
    if (mprotect((void *)base, pg * 2, PROT_READ | PROT_WRITE | PROT_EXEC)) {
        slog("mprotect %s: %s", name, strerror(errno));
        return 0;
    }
    uint32_t to = (uint32_t)(uintptr_t)fn;
    if (a & 1) {
        uint16_t *t = (uint16_t *)p;
        if (!fn) {                      /* movs r0,#val ; bx lr */
            t[0] = 0x2000 | (val & 0xff);
            t[1] = 0x4770;
        } else {                        /* [nop ;] ldr.w pc,[pc,#0] ; .word fn */
            if (p & 2) *t++ = 0xbf00;
            t[0] = 0xf8df; t[1] = 0xf000;
            memcpy(t + 2, &to, 4);
        }
    } else {
        uint32_t *w = (uint32_t *)p;
        if (!fn) {                      /* mov r0,#val ; bx lr */
            w[0] = 0xe3a00000 | (val & 0xff);
            w[1] = 0xe12fff1e;
        } else {                        /* ldr pc,[pc,#-4] ; .word fn */
            w[0] = 0xe51ff004;
            w[1] = to;
        }
    }
    mprotect((void *)base, pg * 2, PROT_READ | PROT_EXEC);
    __builtin___clear_cache((char *)p, (char *)p + 12);
    if (fn) slog("hooked %s at %#x", name, a);
    else slog("stubbed %s at %#x -> %d", name, a, val);
    return 1;
}
#define stub_return(name, val) patch(name, val, NULL)
#define hook(name, fn) patch(name, 0, (void *)(fn))

/* ------------------------------------------------------------- files -- */

static int (*real_open)(const char *, int, ...);
static int (*real_ioctl)(int, unsigned long, ...);
static int spi_fd = -1, drm_fd = -1, mem_fd = -1;

static void resolve(void)
{
    if (!real_open) real_open = dlsym(RTLD_NEXT, "open");
    if (!real_ioctl) real_ioctl = dlsym(RTLD_NEXT, "ioctl");
}

int open(const char *path, int flags, ...)
{
    mode_t mode = 0;
    resolve();
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    if (strcmp(path, "/dev/mem") == 0) {
        mem_fd = real_open("/dev/zero", O_RDWR);
        slog("open /dev/mem -> /dev/zero (fd %d)", mem_fd);
        return mem_fd;
    }
    if (strncmp(path, "/dev/spidev", 11) == 0) {
        spi_fd = real_open("/dev/null", O_RDWR);
        slog("open %s -> /dev/null (fd %d)", path, spi_fd);
        return spi_fd;
    }
    if (strncmp(path, "/dev/input/", 11) == 0)
        return real_open("/dev/null", O_RDONLY | O_NONBLOCK);
    if (strcmp(path, "/dev/dri/card0") == 0) {
        const char *fb = getenv("CGC_FB");
        if (!fb) { errno = ENOENT; return -1; }
        drm_fd = real_open(fb, O_RDWR | O_CREAT, 0644);
        slog("open /dev/dri/card0 -> %s (fd %d)", fb, drm_fd);
        return drm_fd;
    }
    return real_open(path, flags, mode);
}

void *mmap(void *addr, size_t len, int prot, int flags, int fd, off_t off)
{
    static void *(*real_mmap)(void *, size_t, int, int, int, off_t);
    if (!real_mmap) real_mmap = dlsym(RTLD_NEXT, "mmap");
    if (fd >= 0 && fd == mem_fd)
        return real_mmap(addr, len, prot, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    return real_mmap(addr, len, prot, flags, fd, off);
}

int ioctl(int fd, unsigned long req, ...)
{
    va_list ap;
    void *arg;
    resolve();
    va_start(ap, req);
    arg = va_arg(ap, void *);
    va_end(ap);
    if (fd >= 0 && fd == spi_fd) return 0;
    return real_ioctl(fd, req, arg);
}

/* ------------------------------------------------------ the fake panel -- */

#define FB_W 1280
#define FB_H 768
#define FB_NBUF 4
#define FB_HDR 4096

/* $CGC_FB's first page; readers: shot.py, view.py */
struct fbhdr {
    char magic[4];                      /* "CGCF" */
    uint32_t w, h, pitch, bpp;
    uint32_t front;                     /* index of the buffer on screen */
    uint32_t frames;                    /* page flips so far */
    uint32_t nbuf, bufsize;
    uint32_t offset[FB_NBUF];           /* file offset of each buffer */
    uint32_t heartbeat;                 /* state-thread ticks */
};
static struct fbhdr *hdr;
static uint32_t fb_ids[FB_NBUF];
static int nbufs;

/* libdrm's public structs, 32-bit layout (libdrm 2.4.40 on the machine) */
typedef struct {
    uint32_t clock;
    uint16_t hdisplay, hsync_start, hsync_end, htotal, hskew;
    uint16_t vdisplay, vsync_start, vsync_end, vtotal, vscan;
    uint32_t vrefresh, flags, type;
    char name[32];
} mode_info;
typedef struct {
    int count_fbs; uint32_t *fbs;
    int count_crtcs; uint32_t *crtcs;
    int count_connectors; uint32_t *connectors;
    int count_encoders; uint32_t *encoders;
    uint32_t min_width, max_width, min_height, max_height;
} mode_res;
typedef struct {
    uint32_t connector_id, encoder_id, connector_type, connector_type_id;
    int connection;
    uint32_t mmWidth, mmHeight;
    int subpixel;
    int count_modes; mode_info *modes;
    int count_props; uint32_t *props; uint64_t *prop_values;
    int count_encoders; uint32_t *encoders;
} mode_conn;
typedef struct {
    uint32_t encoder_id, encoder_type, crtc_id, possible_crtcs, possible_clones;
} mode_enc;
typedef struct {
    uint32_t crtc_id, buffer_id, x, y, width, height;
    int mode_valid;
    mode_info mode;
    int gamma_size;
} mode_crtc;

static uint32_t ids_crtc[1] = { 40 }, ids_conn[1] = { 30 }, ids_enc[1] = { 20 };

static int fb_setup(void)
{
    if (hdr) return 0;
    uint32_t bufsize = (FB_W * 2 * FB_H + 4095) & ~4095u;
    if (ftruncate(drm_fd, FB_HDR + FB_NBUF * bufsize)) return -1;
    hdr = mmap(NULL, FB_HDR, PROT_READ | PROT_WRITE, MAP_SHARED, drm_fd, 0);
    if (hdr == MAP_FAILED) { hdr = NULL; return -1; }
    memset(hdr, 0, sizeof *hdr);
    hdr->w = FB_W; hdr->h = FB_H; hdr->pitch = FB_W * 2; hdr->bpp = 16;
    hdr->nbuf = FB_NBUF; hdr->bufsize = bufsize;
    for (int i = 0; i < FB_NBUF; i++) hdr->offset[i] = FB_HDR + i * bufsize;
    memcpy(hdr->magic, "CGCF", 4);
    return 0;
}

int drmGetCap(int fd, uint64_t cap, uint64_t *value)
{
    (void)fd; (void)cap;
    *value = 1;                         /* DRM_CAP_DUMB_BUFFER: yes */
    return 0;
}

void *drmModeGetResources(int fd)
{
    (void)fd;
    mode_res *r = calloc(1, sizeof *r);
    r->count_crtcs = 1; r->crtcs = ids_crtc;
    r->count_connectors = 1; r->connectors = ids_conn;
    r->count_encoders = 1; r->encoders = ids_enc;
    r->max_width = FB_W; r->max_height = FB_H;
    return r;
}
void drmModeFreeResources(void *p) { free(p); }

void *drmModeGetConnector(int fd, uint32_t id)
{
    (void)fd;
    mode_conn *c = calloc(1, sizeof *c);
    mode_info *m = calloc(1, sizeof *m);
    m->clock = 65000;
    m->hdisplay = FB_W; m->hsync_start = FB_W + 64; m->hsync_end = FB_W + 192; m->htotal = FB_W + 384;
    m->vdisplay = FB_H; m->vsync_start = FB_H + 3; m->vsync_end = FB_H + 10; m->vtotal = FB_H + 30;
    m->vrefresh = 60; m->type = 0x48;
    snprintf(m->name, sizeof m->name, "%dx%d", FB_W, FB_H);
    c->connector_id = id;
    c->connector_type = 11;             /* HDMI-A */
    c->connection = 1;                  /* connected */
    c->count_modes = 1; c->modes = m;
    c->count_encoders = 1; c->encoders = ids_enc;
    return c;
}
void drmModeFreeConnector(void *p)
{
    if (p) free(((mode_conn *)p)->modes);
    free(p);
}

void *drmModeGetEncoder(int fd, uint32_t id)
{
    (void)fd;
    mode_enc *e = calloc(1, sizeof *e);
    e->encoder_id = id; e->encoder_type = 2;
    e->possible_crtcs = 1;
    return e;
}
void drmModeFreeEncoder(void *p) { free(p); }

void *drmModeGetCrtc(int fd, uint32_t id)
{
    (void)fd;
    mode_crtc *c = calloc(1, sizeof *c);
    c->crtc_id = id;
    return c;
}
void drmModeFreeCrtc(void *p) { free(p); }

int drmModeAddFB(int fd, uint32_t w, uint32_t h, uint8_t depth, uint8_t bpp,
                 uint32_t pitch, uint32_t handle, uint32_t *buf_id)
{
    (void)fd; (void)depth;
    slog("AddFB %ux%u bpp %u pitch %u handle %u", w, h, bpp, pitch, handle);
    if (handle < 1 || handle > FB_NBUF) { errno = EINVAL; return -1; }
    fb_ids[handle - 1] = 100 + handle;
    *buf_id = 100 + handle;
    return 0;
}
int drmModeRmFB(int fd, uint32_t id) { (void)fd; (void)id; return 0; }

int drmModeSetCrtc(int fd, uint32_t crtc, uint32_t fb, uint32_t x, uint32_t y,
                   uint32_t *conns, int n, void *mode)
{
    (void)fd; (void)crtc; (void)x; (void)y; (void)conns; (void)n; (void)mode;
    for (int i = 0; i < FB_NBUF; i++) {
        if (fb_ids[i] == fb && hdr) {
            hdr->front = i;
            hdr->frames++;
            return 0;
        }
    }
    return 0;
}

/* DRM_IOCTL_MODE_CREATE_DUMB / MAP_DUMB / DESTROY_DUMB */
struct create_dumb { uint32_t height, width, bpp, flags, handle, pitch; uint64_t size; };
struct map_dumb { uint32_t handle, pad; uint64_t offset; };

int drmIoctl(int fd, unsigned long req, void *arg)
{
    switch (req & 0xff) {
    case 0xb2: {
        struct create_dumb *c = arg;
        if (fb_setup() || nbufs >= FB_NBUF || c->width != FB_W || c->height != FB_H || c->bpp != 16) {
            slog("CREATE_DUMB %ux%u bpp %u refused", c->width, c->height, c->bpp);
            errno = EINVAL;
            return -1;
        }
        c->handle = ++nbufs;
        c->pitch = FB_W * 2;
        c->size = (uint64_t)c->pitch * c->height;
        return 0;
    }
    case 0xb3: {
        struct map_dumb *m = arg;
        if (!hdr || m->handle < 1 || m->handle > (uint32_t)nbufs) { errno = EINVAL; return -1; }
        m->offset = hdr->offset[m->handle - 1];
        return 0;
    }
    case 0xb4:
        return 0;
    }
    slog("drmIoctl %#lx on fd %d: not answered", req, fd);
    errno = EINVAL;
    return -1;
}

/* ----------------------------------------------------------- the FRAM -- */

/* The game's non-volatile memory (settings, audits, high scores: the 6809's
 * NVRAM and CGC's own adjustments) is an SPI FRAM on the machine, read whole
 * at power-up and written a byte at a time from then on (sam_fram_*), over
 * the same McSPI the playfield uses.  Here it is $CGC_NV, a 32 KiB file
 * mapped shared, so every write is kept the moment it happens; the
 * program's spi_* byte exchange is answered by this model of the chip:
 * 06 WREN, 04 WRDI, 05 RDSR, 03 READ a16, 02 WRITE a16. */
#define FRAM_SIZE 32768
static uint8_t *fram;
static int fram_n;                      /* bytes into this chip select */
static uint8_t fram_cmd;
static uint16_t fram_addr;

static void fram_open(void)
{
    const char *p = getenv("CGC_NV");
    int fd = p ? real_open(p, O_RDWR | O_CREAT, 0644) : -1;
    if (fd >= 0 && lseek(fd, 0, SEEK_END) < FRAM_SIZE && ftruncate(fd, FRAM_SIZE) == 0)
        slog("FRAM %s: new", p);
    if (fd >= 0) {
        fram = mmap(NULL, FRAM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        close(fd);
        if (fram == MAP_FAILED) fram = NULL;
    }
    if (!fram) {
        slog("FRAM: no $CGC_NV, kept in memory only");
        fram = calloc(1, FRAM_SIZE);
    }
}

static void fram_cs_on(void) { fram_n = 0; }
static void fram_cs_off(void) { fram_n = 0; }
static void fram_nop(void) { }

static int fram_x(int b)
{
    int out = 0;
    b &= 0xff;
    if (fram_n == 0) {
        fram_cmd = b;
    } else if ((fram_cmd == 2 || fram_cmd == 3) && fram_n <= 2) {
        fram_addr = fram_n == 1 ? (b << 8) : (fram_addr | b);
    } else if (fram_cmd == 3) {
        out = fram[fram_addr++ % FRAM_SIZE];
    } else if (fram_cmd == 2) {
        fram[fram_addr++ % FRAM_SIZE] = b;
    }
    fram_n++;
    return out;
}

/* ------------------------------------------------ switches and outputs -- */

typedef void (*set_pf_t)(int, int);
typedef int (*get_pf_t)(int);
typedef void (*set_sys_t)(int, int, int);
typedef int (*get_sys_t)(int, int);
typedef int (*get_n_t)(int);

static set_pf_t set_pf;
static get_pf_t get_pf;
static set_sys_t set_sys;
static get_sys_t get_sys;
static get_n_t lamp_get, sol_get;

/* The board.  The program's switch array holds what the WPC CPU reads: a
 * set bit is a CLOSED switch, except an opto, which reads set when its beam
 * is clear (open).  $CGC_BALLS names the title's optos, so every command
 * here speaks closed/open, and describes a counting ball model:
 *
 *   optos=31,32,33,34,35,36,41;trough=32,33,34,35;eject=2;shooter=18;
 *   launch=1;holes=36:3,28:9
 *
 * At power-up the program leaves the array as the machine at rest: balls
 * home in the trough, the coin door closed, every other switch open (MM:
 * the game serves - fires TROUGH EJECT - at Start from exactly that, and
 * says "OPEN COIN DOOR" with 22 set).  Once the game runs the board writes
 * the switches it models to the same (trough full, shooter lane and holes
 * empty) and leaves the rest alone.
 *
 * A trough switch is closed while a ball sits on it; the eject coil moves
 * one to the shooter lane (over the exit switch if the title has one); the
 * launch coil (an autoplunger) or `plunge` (a player's plunger) puts it in
 * play; `drain` returns one; `hole <sw>` drops the ball in play into a
 * kickout whose coil (sw:coil) puts it back in play.  Counting, not
 * physics. */
static uint8_t idle[100], have_idle, opto[100];
static int trough[8], ntrough, trough_n, eject_coil, shooter_sw, exit_sw, launch_coil;
static int holes[16][2], nholes, held[100];
static int shooter_ball, in_play;
/* A two-position motor (MB's up/down bank and Frankenstein table, MM's
 * drawbridge): its coil runs the motor, a switch closes at each end.  The
 * motor leaves its end after MECH_LEAVE_MS of running and reaches the
 * other after MECH_TRAVEL_MS; a game that runs it and never sees the far
 * switch waits forever (MB would not serve a ball). */
#define MECH_LEAVE_MS 60
#define MECH_TRAVEL_MS 700
struct mech { int coil, sw[2], pos, run, idle_ms; };
static struct mech mechs[8];
static int nmechs;
static void sw_set(int n, int closed);

static void mech_tick(uint32_t sols)
{
    for (int i = 0; i < nmechs; i++) {
        struct mech *m = &mechs[i];
        if (sols & (1u << (m->coil - 1))) m->idle_ms = 0;
        else if (m->idle_ms < 1000) m->idle_ms++;
        if (m->idle_ms > 30) continue;          /* stopped (PWM gaps < 30 ms) */
        m->run++;
        if (m->run == MECH_LEAVE_MS) sw_set(m->sw[m->pos], 0);
        if (m->run >= MECH_TRAVEL_MS) {
            m->pos ^= 1;
            sw_set(m->sw[m->pos], 1);
            m->run = 0;
        }
    }
}
static pthread_mutex_t board_mu = PTHREAD_MUTEX_INITIALIZER;
static unsigned long now_ms;            /* the board thread's clock */
/* a served ball's way out: the kick empties trough position 1 at once, the
 * rest roll down after ROLL_MS, the ball reaches the shooter lane after
 * SHOOT_MS.  A game that sees no trough switch move re-kicks. */
#define ROLL_MS 400
#define SHOOT_MS 600
static unsigned long roll_at, shoot_at, exit_on, exit_off;

static int valid_sw(int n) { return n >= 11 && n <= 88 && n % 10 >= 1 && n % 10 <= 8; }

/* closed = 1: the raw bit the CPU reads for that */
static void sw_set(int n, int closed)
{
    if (!valid_sw(n) || !set_pf) return;
    set_pf(n, closed ? !opto[n] : opto[n]);
}

/* trough[0] is the eject end: balls sit at 0..trough_n-1 */
static void trough_show(void)
{
    for (int i = 0; i < ntrough; i++) sw_set(trough[i], i < trough_n);
}

/* "32,33,34" -> ints; returns how many */
static int int_list(char *t, int *out, int max)
{
    int n = 0;
    while (t && *t && n < max) {
        out[n++] = atoi(t);
        t = strchr(t, ',');
        if (t) t++;
    }
    return n;
}

static void parse_balls(void)
{
    const char *c = getenv("CGC_BALLS");
    if (!c) return;
    char buf[256], *save = NULL;
    snprintf(buf, sizeof buf, "%s", c);
    for (char *kv = strtok_r(buf, ";", &save); kv; kv = strtok_r(NULL, ";", &save)) {
        char *v = strchr(kv, '=');
        if (!v) continue;
        *v++ = 0;
        if (!strcmp(kv, "optos")) {
            int o[64], k = int_list(v, o, 64);
            for (int i = 0; i < k; i++) if (valid_sw(o[i])) opto[o[i]] = 1;
        } else if (!strcmp(kv, "trough")) {
            ntrough = int_list(v, trough, 8);
        } else if (!strcmp(kv, "eject")) {
            eject_coil = atoi(v);
        } else if (!strcmp(kv, "shooter")) {
            shooter_sw = atoi(v);
        } else if (!strcmp(kv, "launch")) {
            launch_coil = atoi(v);
        } else if (!strcmp(kv, "exit")) {
            exit_sw = atoi(v);
        } else if (!strcmp(kv, "mechs")) {
            /* "16:81:82,15:83:84" - motor coil : rest end : far end */
            for (char *t = v; t && *t && nmechs < 8; ) {
                struct mech *m = &mechs[nmechs++];
                m->coil = atoi(t);
                m->idle_ms = 1000;              /* not running */
                char *c = strchr(t, ':');
                m->sw[0] = c ? atoi(c + 1) : 0;
                c = c ? strchr(c + 1, ':') : NULL;
                m->sw[1] = c ? atoi(c + 1) : 0;
                t = strchr(t, ',');
                if (t) t++;
            }
        } else if (!strcmp(kv, "holes")) {
            int flat[32], k = int_list(v, flat, 32);
            /* "36:2" -> atoi stops at ':'; the coil follows it */
            char *t = v;
            for (int i = 0; i < k && nholes < 16; i++) {
                holes[nholes][0] = flat[i];
                char *colon = strchr(t, ':');
                holes[nholes++][1] = colon ? atoi(colon + 1) : 0;
                t = strchr(t, ',');
                if (!t) break;
                t++;
            }
        }
    }
    trough_n = ntrough;
    slog("balls: %d in the trough, eject coil %d, shooter %d, %d holes, %d motors",
         ntrough, eject_coil, shooter_sw, nholes, nmechs);
}

static void on_coil(int n)
{
    if (n == eject_coil && trough_n > 0 && !shooter_ball && !shoot_at) {
        trough_n--;
        sw_set(trough[0], 0);           /* the kicked ball leaves position 1 */
        roll_at = now_ms + ROLL_MS;
        shoot_at = now_ms + SHOOT_MS;
        if (exit_sw) { exit_on = now_ms + 100; exit_off = now_ms + 250; }
    }
    if (n == launch_coil && shooter_ball) {
        shooter_ball = 0;
        sw_set(shooter_sw, 0);
        in_play++;
    }
    for (int i = 0; i < nholes; i++) {
        int sw = holes[i][0];
        if (holes[i][1] == n && held[sw]) {
            held[sw] = 0;
            sw_set(sw, 0);
            in_play++;
        }
    }
}

static void do_line(char *l)
{
    int a, b, c;
    pthread_mutex_lock(&board_mu);
    if (sscanf(l, "pf %d %d", &a, &b) == 2 && set_pf) {
        set_pf(a, b);                   /* raw */
    } else if (sscanf(l, "sw %d %d", &a, &b) == 2) {
        sw_set(a, b);                   /* closed / open */
    } else if (sscanf(l, "sys %d %d %d", &a, &b, &c) == 3 && set_sys) {
        set_sys(a, b, c);
    } else if (!strcmp(l, "plunge")) {
        if (shooter_ball) {
            shooter_ball = 0;
            sw_set(shooter_sw, 0);
            in_play++;
        }
    } else if (!strcmp(l, "drain")) {
        if (in_play > 0 && trough_n < ntrough) {
            in_play--;
            trough_n++;
            trough_show();
        }
    } else if (sscanf(l, "hole %d", &a) == 1) {
        if (in_play > 0 && valid_sw(a) && !held[a]) {
            in_play--;
            held[a] = 1;
            sw_set(a, 1);
        }
    } else if (!strcmp(l, "balls reset")) {
        trough_n = ntrough; shooter_ball = 0; in_play = 0; roll_at = shoot_at = 0;
        memset(held, 0, sizeof held);
        for (int i = 0; i < nholes; i++) sw_set(holes[i][0], 0);
        sw_set(shooter_sw, 0);
        trough_show();
    } else if (l[0]) {
        slog("ctl: not understood: %s", l);
    }
    pthread_mutex_unlock(&board_mu);
}

/* 1 kHz: coil edges (a pulse is 20-40 ms; the state file's 50 ms would miss
 * them), the ball model's answers, and $CGC_EVENTS - one line per coil
 * pulse, "<ms> sol <n>", for tests and the switch window.  A coil driven
 * as PWM (a hold, a flasher's dim) counts once, when it starts. */
static void *board_thread(void *unused)
{
    (void)unused;
    const char *ev = getenv("CGC_EVENTS");
    FILE *evf = ev ? fopen(ev, "a") : NULL;
    uint32_t last = 0;
    unsigned long ms = 0, off_since[33] = { 0 };
    if (evf) setvbuf(evf, NULL, _IOLBF, 0);
    for (;; ms++) {
        usleep(1000);
        now_ms = ms;
        if (roll_at && ms >= roll_at) {
            pthread_mutex_lock(&board_mu);
            roll_at = 0;
            trough_show();
            pthread_mutex_unlock(&board_mu);
        }
        if (exit_on && ms >= exit_on) {
            pthread_mutex_lock(&board_mu);
            exit_on = 0;
            sw_set(exit_sw, 1);
            pthread_mutex_unlock(&board_mu);
        }
        if (exit_off && ms >= exit_off) {
            pthread_mutex_lock(&board_mu);
            exit_off = 0;
            sw_set(exit_sw, 0);
            pthread_mutex_unlock(&board_mu);
        }
        if (shoot_at && ms >= shoot_at) {
            pthread_mutex_lock(&board_mu);
            shoot_at = 0;
            shooter_ball = 1;
            sw_set(shooter_sw, 1);
            pthread_mutex_unlock(&board_mu);
        }
        if (!have_idle) {
            /* the program has set its switches' resting state by its first
             * frames; take it once, before anything here writes one */
            if (!hdr || hdr->frames < 30 || !get_pf) continue;
            pthread_mutex_lock(&board_mu);
            for (int n = 11; n <= 88; n++)
                if (valid_sw(n)) idle[n] = get_pf(n) ? 1 : 0;
            have_idle = 1;
            /* every opto clear (MB's program powers up with them all at 0,
             * blocked, and its ROM then asks for the opto 12 V fuses),
             * then the balls where they rest */
            for (int n = 11; n <= 88; n++)
                if (valid_sw(n) && opto[n]) sw_set(n, 0);
            for (int i = 0; i < nmechs; i++) {  /* each motor at its rest end */
                sw_set(mechs[i].sw[0], 1);
                sw_set(mechs[i].sw[1], 0);
            }
            trough_show();
            sw_set(shooter_sw, 0);
            if (exit_sw) sw_set(exit_sw, 0);
            for (int i = 0; i < nholes; i++) sw_set(holes[i][0], 0);
            pthread_mutex_unlock(&board_mu);
            {
                char set[256] = "";
                for (int n = 11; n <= 88; n++)
                    if (valid_sw(n) && idle[n])
                        snprintf(set + strlen(set), sizeof set - strlen(set), " %d", n);
                slog("switches at power-up (frame %u), set:%s", hdr->frames, set);
            }
        }
        if (!sol_get) continue;
        uint32_t sols = 0;
        for (int s = 1; s <= 32; s++)
            if (sol_get(s)) sols |= 1u << (s - 1);
        uint32_t ch = sols ^ last;
        if (nmechs && have_idle) {
            pthread_mutex_lock(&board_mu);
            mech_tick(sols);
            pthread_mutex_unlock(&board_mu);
        }
        if (!ch) continue;
        pthread_mutex_lock(&board_mu);
        for (int s = 1; s <= 32; s++) {
            if (!(ch & (1u << (s - 1)))) continue;
            int on = !!(sols & (1u << (s - 1)));
            /* a pulse, not PWM: logged when the coil had rested >= 50 ms */
            if (on && ms - off_since[s] >= 50) {
                if (evf) fprintf(evf, "%lu sol %d\n", ms, s);
                on_coil(s);
            }
            if (!on) off_since[s] = ms;
        }
        pthread_mutex_unlock(&board_mu);
        last = sols;
    }
    return NULL;
}

static void *ctl_thread(void *unused)
{
    (void)unused;
    const char *path = getenv("CGC_CTL");
    char buf[512];
    size_t have = 0;
    if (!path) return NULL;
    for (;;) {
        int fd = real_open(path, O_RDONLY);
        if (fd < 0) { sleep(1); continue; }
        ssize_t n;
        while ((n = read(fd, buf + have, sizeof buf - 1 - have)) > 0) {
            have += n;
            buf[have] = 0;
            char *s = buf, *nl;
            while ((nl = strchr(s, '\n'))) {
                *nl = 0;
                do_line(s);
                s = nl + 1;
            }
            have = strlen(s);
            memmove(buf, s, have);
            if (have >= sizeof buf - 1) have = 0;
        }
        close(fd);
    }
    return NULL;
}

/* $CGC_STATE: one line each, rewritten whole every 50 ms (rename):
 *   sw <hex: bit n-11 of the matrix, WPC 11..88 as col*8+row>
 *   sys <hex of banks 0..1>
 *   lamps <hex: lamps 11..88 the same way>
 *   sols <hex: solenoids 1..32 bit n-1>
 *   frames <n>
 *   balls trough=<n> shooter=<0|1> play=<n> held=<sw,...>
 *   idle <0|1>      (switches' resting state taken yet) */
static void *state_thread(void *unused)
{
    (void)unused;
    const char *path = getenv("CGC_STATE");
    char tmp[512];
    if (!path) return NULL;
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    for (;;) {
        usleep(50 * 1000);
        FILE *f = fopen(tmp, "w");
        if (!f) continue;
        uint8_t sw[8] = { 0 }, lm[8] = { 0 };
        for (int c = 1; c <= 8; c++)
            for (int r = 1; r <= 8; r++) {
                int n = c * 10 + r;
                if (get_pf && get_pf(n)) sw[c - 1] |= 1 << (r - 1);
                if (lamp_get && lamp_get(n)) lm[c - 1] |= 1 << (r - 1);
            }
        fprintf(f, "sw ");
        for (int i = 0; i < 8; i++) fprintf(f, "%02x", sw[i]);
        fprintf(f, "\nsys ");
        for (int b = 0; b < 2; b++) {
            unsigned v = 0;
            for (int k = 0; k < 8; k++)
                if (get_sys && get_sys(b, k)) v |= 1u << k;
            fprintf(f, "%02x", v);
        }
        fprintf(f, "\nlamps ");
        for (int i = 0; i < 8; i++) fprintf(f, "%02x", lm[i]);
        uint32_t sols = 0;
        for (int s = 1; s <= 32; s++)
            if (sol_get && sol_get(s)) sols |= 1u << (s - 1);
        fprintf(f, "\nsols %08x\nframes %u\n", sols, hdr ? hdr->frames : 0);
        fprintf(f, "balls trough=%d shooter=%d play=%d held=", trough_n, shooter_ball, in_play);
        for (int n = 11, first = 1; n <= 88; n++)
            if (held[n]) { fprintf(f, first ? "%d" : ",%d", n); first = 0; }
        fprintf(f, "\nidle %d\n", have_idle);
        fclose(f);
        rename(tmp, path);
        if (hdr) hdr->heartbeat++;
    }
    return NULL;
}

/* A crash says where, in the program's own addresses: the rig's log is
 * the only record of a run nobody watched. */
static void on_crash(int sig, siginfo_t *si, void *ctx)
{
    ucontext_t *uc = ctx;
    mcontext_t *m = &uc->uc_mcontext;
    slog("signal %d at pc %#lx lr %#lx addr %p; r0 %#lx r1 %#lx r2 %#lx r3 %#lx r4 %#lx r5 %#lx sp %#lx",
         sig, m->arm_pc, m->arm_lr, si->si_addr, m->arm_r0, m->arm_r1, m->arm_r2,
         m->arm_r3, m->arm_r4, m->arm_r5, m->arm_sp);
    signal(sig, SIG_DFL);
    raise(sig);
}

/* ------------------------------------------------- lamps and coils -- */

/* The WPC state block every emumm keeps: lamp columns at +1..+8, solenoid
 * bytes from +9, switch columns from +17 (MM's wms_lamp_get / wms_sol_get
 * read exactly these).  Not every build has those two getters (AFM has
 * neither), so the block's address is read out of emu_getPF_Sw, which
 * loads it with a Thumb-2 movw/movt pair into one register. */
static uint8_t *wpc_state;

static uint32_t t2_imm16(const uint16_t *h)
{
    return ((h[0] & 0xf) << 12) | (((h[0] >> 10) & 1) << 11) |
           (((h[1] >> 12) & 7) << 8) | (h[1] & 0xff);
}

static uint8_t *find_wpc_state(void)
{
    uint32_t f = sym("emu_getPF_Sw");
    if (!(f & 1)) return NULL;
    const uint16_t *h = (const uint16_t *)(uintptr_t)(f & ~1u);
    uint32_t lo[16] = { 0 }, have_lo = 0;
    for (int i = 0; i < 40; i++) {
        uint16_t op = h[i] & 0xfbf0;
        int rd = (h[i + 1] >> 8) & 0xf;
        if (op == 0xf240) {                     /* movw */
            lo[rd] = t2_imm16(h + i);
            have_lo |= 1u << rd;
            i++;
        } else if (op == 0xf2c0 && (have_lo & (1u << rd))) {   /* movt */
            uint32_t a = (t2_imm16(h + i) << 16) | lo[rd];
            /* not the /10 constant 0x66666667 it also loads: an address
             * in the program's own data */
            if (a > 0x10000 && a < 0x08000000) return (uint8_t *)(uintptr_t)a;
            i++;
        }
    }
    return NULL;
}

static int state_lamp(int n)
{
    return wpc_state[n / 10] & (1 << (n % 10 - 1));
}

static int state_sol(int n)
{
    return wpc_state[9 + ((n - 1) >> 3)] & (1 << ((n - 1) & 7));
}

/* ------------------------------------------------------------- start -- */

__attribute__((constructor)) static void cgcshim_init(void)
{
    static const char *const want[] = {
        "io", "sam_io", "spi_init", "emu_setPF_Sw", "emu_getPF_Sw", "emu_setSys_Sw",
        "emu_getSys_Sw", "wms_lamp_get", "wms_sol_get",
        "spi_setup", "spi_cs_on", "spi_cs_off", "spi_done", "spix", NULL
    };
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_crash;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGILL, &sa, NULL);
    resolve();
    find_syms(want);
    slog("pid %d, %d of the program's functions found", getpid(), nsyms);
    /* the once-a-millisecond board exchange: io() (MM) or sam_io() (AFM) */
    if (!stub_return("io", 1) && !stub_return("sam_io", 1))
        slog("no io() or sam_io() to stub: the board traffic will run");
    stub_return("spi_init", 1);
    fram_open();
    hook("spi_setup", fram_nop);
    hook("spi_cs_on", fram_cs_on);
    hook("spi_cs_off", fram_cs_off);
    hook("spi_done", fram_nop);
    hook("spix", fram_x);
    set_pf = (set_pf_t)(uintptr_t)sym("emu_setPF_Sw");
    get_pf = (get_pf_t)(uintptr_t)sym("emu_getPF_Sw");
    set_sys = (set_sys_t)(uintptr_t)sym("emu_setSys_Sw");
    get_sys = (get_sys_t)(uintptr_t)sym("emu_getSys_Sw");
    lamp_get = (get_n_t)(uintptr_t)sym("wms_lamp_get");
    sol_get = (get_n_t)(uintptr_t)sym("wms_sol_get");
    if ((!lamp_get || !sol_get) && (wpc_state = find_wpc_state())) {
        slog("WPC state block at %p (no wms_lamp_get/wms_sol_get)", (void *)wpc_state);
        if (!lamp_get) lamp_get = state_lamp;
        if (!sol_get) sol_get = state_sol;
    }
    parse_balls();
    pthread_t t;
    pthread_create(&t, NULL, ctl_thread, NULL);
    pthread_create(&t, NULL, board_thread, NULL);
    pthread_create(&t, NULL, state_thread, NULL);
}
