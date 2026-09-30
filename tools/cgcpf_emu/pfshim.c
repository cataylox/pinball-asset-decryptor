/*
 * pfshim.c - LD_PRELOAD for CGC's Pulp Fiction `pin` (ARM hard-float, run by
 * qemu-arm in the rig's chroot of the machine's own Ubuntu 12.10).
 *
 * The machine is a BeagleBone: the game draws on HDMI through libdrm "dumb"
 * buffers, and talks to the playfield board over SPI driven by the AM335x
 * PRU coprocessor (/dev/uio0 + ./pru_spi.bin).  The settings, audits and
 * high scores live in an 8 KiB SPI FRAM on the same bus.  This shim stands
 * in for all of it, inside the game's own process:
 *
 *   libdrm       drm* are defined here (they win over libdrm.so.2): one
 *                connector (PF_MODES), one CRTC; dumb buffers live in
 *                $PF_RIG/fb.bin
 *                (a 4 KiB header, then the buffers) and drmModeSetCrtc - the
 *                game's flip - records which one is on screen.  shot.py reads
 *                it.
 *   /dev/uio0    the PRU subsystem's 512 KiB is plain memory; a thread plays
 *                the PRU firmware's side of the mailbox at shared RAM +0x2000
 *                (docs/plans/cgcpf_emulator.md has the contract).
 *   the board    tx[0] = 0x13, 41 bytes: the game's outputs; the reply is the
 *                board's 'C' packet with the switches from $PF_RIG/io.bin.
 *   FRAM         READ 03 / WRITE 02 / WREN 06 / RDSR 05 on $PF_NV/fram.bin.
 *   /dev/mem     GPIO / control-module windows: zeroed private memory.
 *   the cabinet  switches 64-79 come over a GPIO bus the game bit-bangs
 *                through /dev/mem; its bus-read routine is hooked to read
 *                them from io.bin (the end of this file).
 *   /dev/spidev1.0  opened and configured first; accepts its ioctls.
 *   the clock    settimeofday() is a no-op: the game sets the system time
 *                from its RTC, and this process shares the PC's clock.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

/* ------------------------------------------------------------------ log */
static FILE *logf_;
static void plog(const char *fmt, ...)
{
    if (!logf_) {
        const char *p = getenv("PF_SHIMLOG");
        logf_ = fopen(p ? p : "/dev/null", "a");
        if (!logf_) return;
        setvbuf(logf_, NULL, _IOLBF, 0);
    }
    va_list ap;
    va_start(ap, fmt);
    vfprintf(logf_, fmt, ap);
    va_end(ap);
}

static const char *rig(const char *leaf, char *buf, size_t n)
{
    const char *r = getenv("PF_RIG");
    snprintf(buf, n, "%s/%s", r ? r : "/tmp", leaf);
    return buf;
}

/* -------------------------------------------------------------- io.bin */
/* Shared with sw.py (its OFF_* constants; tests/test_cgcpf_emu_rig.py
 * holds the two in step). */
struct pf_io {
    char magic[4];          /* "PFI2" */
    uint32_t xfers;         /* playfield exchanges so far */
    uint8_t sw[16];         /* switch n closed = bit n%8 of sw[n/8]; the game's
                             * numbering: 0-63 the playfield board, 64-79 the
                             * cabinet (GPIO bus).  Active low on the wire. */
    uint8_t ext[8];         /* raw: the 8 bytes after the 'C' packet's flag */
    uint8_t out[40];        /* the game's last 41-byte packet, bytes 1..40 */
    uint32_t fram_ops;      /* FRAM commands seen */
    uint8_t type;           /* the 'C' packet's second byte */
    uint8_t pad[3];
    uint32_t cab_reads;     /* cabinet bus reads (the hook below) */
    uint32_t pulses[40 * 8];/* rising edges seen on each output bit */
};
static struct pf_io *io;
static pthread_once_t io_once = PTHREAD_ONCE_INIT;

static void io_map(void)
{
    char p[512];
    int fd = open(rig("io.bin", p, sizeof p), O_RDWR | O_CREAT, 0666);
    if (fd < 0) { plog("io.bin: %s\n", strerror(errno)); return; }
    if (ftruncate(fd, 4096) < 0) plog("io.bin truncate: %s\n", strerror(errno));
    struct pf_io *m = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (m == MAP_FAILED) return;
    if (memcmp(m->magic, "PFI2", 4)) {
        memset(m, 0, sizeof *m);
        memcpy(m->magic, "PFI2", 4);
    }
    io = m;
}

static void io_open(void) { pthread_once(&io_once, io_map); }

/* ---------------------------------------------------------------- FRAM */
static uint8_t fram[8192];
static char fram_path[512];
static int fram_wel, fram_dirty;

static void fram_load(void)
{
    const char *nv = getenv("PF_NV");
    snprintf(fram_path, sizeof fram_path, "%s/fram.bin", nv ? nv : "/tmp");
    int fd = open(fram_path, O_RDONLY);
    if (fd >= 0) {
        ssize_t n = read(fd, fram, sizeof fram);
        close(fd);
        plog("fram: loaded %d bytes from %s\n", (int)n, fram_path);
    } else {
        memset(fram, 0, sizeof fram);
        plog("fram: new (%s)\n", fram_path);
    }
}

static void fram_save(void)
{
    char tmp[600];
    snprintf(tmp, sizeof tmp, "%s.tmp", fram_path);
    int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) return;
    if (write(fd, fram, sizeof fram) == (ssize_t)sizeof fram) {
        close(fd);
        rename(tmp, fram_path);
    } else close(fd);
}

static void fram_xfer(const uint8_t *tx, uint8_t *rx, int len)
{
    unsigned a;
    if (io) io->fram_ops++;
    switch (tx[0]) {
    case 0x06: fram_wel = 1; break;                        /* WREN */
    case 0x04: fram_wel = 0; break;                        /* WRDI */
    case 0x05: if (len > 1) rx[1] = fram_wel ? 2 : 0; break; /* RDSR */
    case 0x03:                                             /* READ */
        a = ((tx[1] << 8) | tx[2]) & 0x1fff;
        for (int i = 3; i < len; i++) rx[i] = fram[(a + i - 3) & 0x1fff];
        break;
    case 0x02:                                             /* WRITE */
        if (!fram_wel) break;
        a = ((tx[1] << 8) | tx[2]) & 0x1fff;
        for (int i = 3; i < len; i++) fram[(a + i - 3) & 0x1fff] = tx[i];
        fram_wel = 0;
        fram_dirty = 1;              /* fram_saver() writes it out */
        break;
    default:
        plog("fram: unknown command %02x len %d\n", tx[0], len);
    }
}

/* Off the PRU thread: a file write there would outlast the game's patience
 * (it gives a transfer a few ms) and fail the transfer. */
static void *fram_saver(void *arg)
{
    (void)arg;
    for (;;) {
        sleep(1);
        if (fram_dirty) { fram_dirty = 0; fram_save(); }
    }
    return NULL;
}

/* ----------------------------------------------------- playfield board */
static void board_xfer(const uint8_t *tx, uint8_t *rx, int len)
{
    uint8_t p[21];
    memset(rx, 0, len);
    if (io) {
        for (int i = 0; i < 40 && i + 1 < len; i++) {
            uint8_t rise = tx[i + 1] & ~io->out[i];
            for (int b = 0; b < 8; b++)
                if (rise & (1 << b)) io->pulses[i * 8 + b]++;
            io->out[i] = tx[i + 1];
        }
        io->xfers++;
    }
    p[0] = 'C';
    p[1] = io ? io->type : 0;
    unsigned ck = p[0] + p[1];
    for (int i = 0; i < 8; i++) {
        p[2 + i] = io ? (uint8_t)~io->sw[i] : 0xff;
        ck += p[2 + i];
    }
    p[10] = ck & 0xff;
    p[11] = 0;
    for (int i = 0; i < 8; i++) p[12 + i] = io ? io->ext[i] : 0;
    p[20] = 0;
    memcpy(rx, p, len < 21 ? len : 21);
}

/* ------------------------------------------------------------- the PRU */
#define PRUSS_SIZE 0x80000
#define PRU_SHARED 0x10000
#define MBOX (PRU_SHARED + 0x2000)
static uint8_t *pruss;
static pthread_t pru_thread;

static void *pru_main(void *arg)
{
    volatile uint32_t *w0 = (volatile uint32_t *)(pruss + MBOX);
    uint8_t *tx = pruss + MBOX + 4, *rx = pruss + MBOX + 0x144;
    uint8_t txc[320], rxc[320];
    struct timespec busy = {0, 0};
    (void)arg;
    pthread_t saver;
    fram_load();
    io_open();
    pthread_create(&saver, NULL, fram_saver, NULL);
    __sync_synchronize();
    *w0 = 0x40000000;                       /* ready */
    for (;;) {
        uint32_t v = *w0;
        if (!(v & 0x80000000u)) {
            /* The game polls ~100000 times (a few ms under qemu) and then
             * calls the transfer lost: stay close while the bus is busy. */
            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            if (now.tv_sec - busy.tv_sec < 3) { sched_yield(); continue; }
            usleep(50);
            continue;
        }
        clock_gettime(CLOCK_MONOTONIC, &busy);
        __sync_synchronize();
        if (v & 0x20000000u) {              /* firmware version */
            *(volatile uint32_t *)rx = 0x0102;
        } else {
            int len = v & 0xffff;
            if (len > 316) len = 316;
            memcpy(txc, tx, len);
            memset(rxc, 0, len);
            if (txc[0] == 0x13) board_xfer(txc, rxc, len);
            else fram_xfer(txc, rxc, len);
            memcpy(rx, rxc, len);
        }
        __sync_synchronize();
        *w0 = (v & ~0x80000000u) | 0x40000000u;
    }
    return NULL;
}

/* ------------------------------------------------------ fake devices */
enum { FD_NONE, FD_UIO, FD_MEM, FD_DRM, FD_SPI };
static int fdkind[1024];
static int drm_fd = -1;

static int (*real_open)(const char *, int, ...);
static FILE *(*real_fopen)(const char *, const char *);
static void *(*real_mmap)(void *, size_t, int, int, int, off_t);

static void init_real(void)
{
    if (!real_open) {
        real_open = dlsym(RTLD_NEXT, "open");
        real_fopen = dlsym(RTLD_NEXT, "fopen");
        real_mmap = dlsym(RTLD_NEXT, "mmap");
    }
}

/* the uio sysfs files prussdrv reads */
static const char *sysfs_text(const char *path)
{
    if (!strcmp(path, "/sys/class/uio/uio0/maps/map0/addr")) return "0x4a300000\n";
    if (!strcmp(path, "/sys/class/uio/uio0/maps/map0/size")) return "0x00080000\n";
    if (!strcmp(path, "/sys/class/uio/uio0/maps/map1/addr")) return "0x9c940000\n";
    if (!strcmp(path, "/sys/class/uio/uio0/maps/map1/size")) return "0x00040000\n";
    if (!strcmp(path, "/sys/class/uio/uio0/maps/map2/addr")) return "0x9c980000\n";
    if (!strcmp(path, "/sys/class/uio/uio0/maps/map2/size")) return "0x00040000\n";
    return NULL;
}

static int text_fd(const char *s)
{
    char p[512], b[480];
    static int n;
    snprintf(p, sizeof p, "%s.%d", rig("sysfs", b, sizeof b), n++);
    int fd = real_open(p, O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) return -1;
    if (write(fd, s, strlen(s)) < 0) { close(fd); return -1; }
    lseek(fd, 0, SEEK_SET);
    unlink(p);
    return fd;
}

static int fake_open(const char *path, int flags, mode_t mode)
{
    const char *t;
    int fd;
    init_real();
    if (!path) return real_open(path, flags, mode);
    if ((t = sysfs_text(path))) {
        plog("open %s (sysfs)\n", path);
        return text_fd(t);
    }
    if (!strncmp(path, "/dev/spidev", 11)) {
        fd = real_open("/dev/zero", O_RDWR);
        if (fd >= 0 && fd < 1024) fdkind[fd] = FD_SPI;
        plog("open %s -> %d\n", path, fd);
        return fd;
    }
    if (!strncmp(path, "/dev/uio", 8) || !strcmp(path, "/dev/mem") ||
        !strcmp(path, "/dev/dri/card0")) {
        char p[512];
        if (!strcmp(path, "/dev/dri/card0"))
            fd = real_open(rig("fb.bin", p, sizeof p), O_RDWR | O_CREAT, 0666);
        else
            fd = real_open("/dev/zero", O_RDWR);
        if (fd >= 0 && fd < 1024)
            fdkind[fd] = path[5] == 'u' ? FD_UIO : path[5] == 'm' ? FD_MEM : FD_DRM;
        if (path[5] == 'd') drm_fd = fd;
        plog("open %s -> %d\n", path, fd);
        return fd;
    }
    fd = real_open(path, flags, mode);
    if (!strncmp(path, "/dev/", 5) || !strncmp(path, "/sys/", 5))
        plog("open %s -> %d (%s)\n", path, fd, fd < 0 ? strerror(errno) : "real");
    if (fd >= 0 && fd < 1024) fdkind[fd] = FD_NONE;
    return fd;
}

int open(const char *path, int flags, ...)
{
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    return fake_open(path, flags, mode);
}

int open64(const char *path, int flags, ...)
{
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    return fake_open(path, flags | O_LARGEFILE, mode);
}

FILE *fopen(const char *path, const char *m)
{
    const char *t;
    init_real();
    if (path && (t = sysfs_text(path))) {
        int fd = text_fd(t);
        return fd < 0 ? NULL : fdopen(fd, "r");
    }
    return real_fopen(path, m);
}

/* /dev/mem windows, one private block per physical page range */
struct memwin { off_t off; size_t len; void *p; };
static struct memwin memwins[32];

void *mmap(void *addr, size_t len, int prot, int flags, int fd, off_t off)
{
    init_real();
    int k = (fd >= 0 && fd < 1024) ? fdkind[fd] : FD_NONE;
    if (k == FD_UIO) {
        if (off == 0) {
            if (!pruss) {
                size_t n = len > PRUSS_SIZE ? len : PRUSS_SIZE;
                pruss = real_mmap(NULL, n, PROT_READ | PROT_WRITE,
                                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
                /* the INTC revision prussdrv reads to call this an AM33xx */
                *(uint32_t *)(pruss + 0x20000) = 0x4e82a900;
                pthread_create(&pru_thread, NULL, pru_main, NULL);
            }
            plog("mmap uio map0 len %#zx -> %p\n", len, (void *)pruss);
            return pruss;
        }
        void *p = real_mmap(NULL, len, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        plog("mmap uio off %#lx len %#zx -> %p\n", (long)off, len, p);
        return p;
    }
    if (k == FD_MEM) {
        for (int i = 0; i < 32; i++)
            if (memwins[i].p && memwins[i].off == off && memwins[i].len >= len)
                return memwins[i].p;
        void *p = real_mmap(NULL, len, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        for (int i = 0; i < 32; i++)
            if (!memwins[i].p) { memwins[i] = (struct memwin){off, len, p}; break; }
        plog("mmap /dev/mem %#lx len %#zx -> %p\n", (long)off, len, p);
        return p;
    }
    return real_mmap(addr, len, prot, flags, fd, off);
}

void *mmap64(void *addr, size_t len, int prot, int flags, int fd, off64_t off)
{
    return mmap(addr, len, prot, flags, fd, (off_t)off);
}

/* spidev: the mode / word size / speed setup succeeds; the game's traffic
 * goes through the PRU. */
int ioctl(int fd, unsigned long req, ...)
{
    static int (*real_ioctl)(int, unsigned long, ...);
    va_list ap;
    va_start(ap, req);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    if (!real_ioctl) real_ioctl = dlsym(RTLD_NEXT, "ioctl");
    if (fd >= 0 && fd < 1024 && fdkind[fd] == FD_SPI) {
        static uint32_t spiset[16];                     /* by ioctl nr */
        unsigned nr = req & 15, sz = (req >> 16) & 0x3fff, dir = req >> 30;
        plog("spidev ioctl %#lx\n", req);
        if ((req & 0xff00) == 0x6b00 && arg && sz <= 4) {
            if (dir == 1) memcpy(&spiset[nr], arg, sz);   /* _IOW: keep */
            if (dir == 2) memcpy(arg, &spiset[nr], sz);   /* _IOR: echo */
        }
        return 0;
    }
    return real_ioctl(fd, req, arg);
}

int settimeofday(const struct timeval *tv, const struct timezone *tz)
{
    (void)tz;
    plog("settimeofday(%ld) ignored\n", tv ? (long)tv->tv_sec : 0L);
    return 0;
}

/* --------------------------------------------------------------- libdrm */
#define FB_HDR 4096
struct pf_fbhdr {
    char magic[4];           /* "PFFB" */
    uint32_t width, height, pitch, bpp;
    uint32_t front;          /* byte offset of the buffer on screen, 0 = none */
    uint32_t flips;
    uint32_t nbuf;
    uint32_t off[8];         /* each dumb buffer's offset */
};
static struct pf_fbhdr *fbh;
static uint32_t fb_next = FB_HDR;
static uint32_t dumb_off[16];            /* by handle */
static uint32_t fb_handle[16];           /* by fb id */
static int nfb;

static void fb_header(void)
{
    if (fbh) return;
    if (ftruncate(drm_fd, FB_HDR) < 0) plog("fb.bin: %s\n", strerror(errno));
    fbh = real_mmap(NULL, FB_HDR, PROT_READ | PROT_WRITE, MAP_SHARED, drm_fd, 0);
    if (fbh == MAP_FAILED) { fbh = NULL; return; }
    memset(fbh, 0, sizeof *fbh);
    memcpy(fbh->magic, "PFFB", 4);
    fb_next = FB_HDR;
}

int drmIoctl(int fd, unsigned long req, void *arg)
{
    init_real();
    switch (req) {
    case DRM_IOCTL_MODE_CREATE_DUMB: {
        struct drm_mode_create_dumb *c = arg;
        fb_header();
        c->pitch = c->width * ((c->bpp + 7) / 8);
        c->size = (uint64_t)c->pitch * c->height;
        uint32_t h = 1;
        while (h < 16 && dumb_off[h]) h++;
        if (h >= 16) { errno = ENOMEM; return -1; }
        dumb_off[h] = fb_next;
        fb_next += (c->size + 4095) & ~4095u;
        if (ftruncate(fd, fb_next) < 0) plog("fb grow: %s\n", strerror(errno));
        c->handle = h;
        if (fbh) {
            fbh->width = c->width; fbh->height = c->height;
            fbh->pitch = c->pitch; fbh->bpp = c->bpp;
            if (fbh->nbuf < 8) fbh->off[fbh->nbuf++] = dumb_off[h];
        }
        plog("create_dumb %ux%u bpp %u -> handle %u off %#x\n",
             c->width, c->height, c->bpp, h, dumb_off[h]);
        return 0;
    }
    case DRM_IOCTL_MODE_MAP_DUMB: {
        struct drm_mode_map_dumb *m = arg;
        m->offset = m->handle < 16 ? dumb_off[m->handle] : 0;
        return 0;
    }
    case DRM_IOCTL_MODE_DESTROY_DUMB:
        return 0;
    default:
        plog("drmIoctl %#lx ignored\n", req);
        return 0;
    }
}

int drmGetCap(int fd, uint64_t cap, uint64_t *value)
{
    (void)fd;
    *value = cap == DRM_CAP_DUMB_BUFFER ? 1 : 0;
    return 0;
}

drmModeResPtr drmModeGetResources(int fd)
{
    (void)fd;
    drmModeResPtr r = calloc(1, sizeof *r);
    r->count_fbs = 0;
    r->count_crtcs = 1; r->crtcs = calloc(1, sizeof(uint32_t)); r->crtcs[0] = 30;
    r->count_connectors = 1; r->connectors = calloc(1, sizeof(uint32_t)); r->connectors[0] = 40;
    r->count_encoders = 1; r->encoders = calloc(1, sizeof(uint32_t)); r->encoders[0] = 50;
    r->min_width = 0; r->max_width = 2048; r->min_height = 0; r->max_height = 2048;
    return r;
}

void drmModeFreeResources(drmModeResPtr r)
{
    if (!r) return;
    free(r->crtcs); free(r->connectors); free(r->encoders); free(r->fbs); free(r);
}

static void mode_fill(drmModeModeInfo *m, int w, int h, int pref)
{
    memset(m, 0, sizeof *m);
    m->hdisplay = w; m->vdisplay = h;
    m->hsync_start = w + 16; m->hsync_end = w + 32; m->htotal = w + 64;
    m->vsync_start = h + 3; m->vsync_end = h + 6; m->vtotal = h + 30;
    m->vrefresh = 60;
    m->clock = (m->htotal * m->vtotal * 60) / 1000;
    m->type = DRM_MODE_TYPE_DRIVER | (pref ? DRM_MODE_TYPE_PREFERRED : 0);
    snprintf(m->name, sizeof m->name, "%dx%d", w, h);
}

/* The monitor's modes: PF_MODES, "WxH,WxH..." (first = preferred), else
 * DEFAULT_MODES.  The game takes a 1280-wide mode at least 768 tall - the
 * smallest such - else the first 1280-wide one. */
#define DEFAULT_MODES "1280x720"
drmModeConnectorPtr drmModeGetConnector(int fd, uint32_t id)
{
    (void)fd;
    const char *list = getenv("PF_MODES");
    if (!list || !*list) list = DEFAULT_MODES;
    drmModeConnectorPtr c = calloc(1, sizeof *c);
    c->connector_id = id;
    c->encoder_id = 50;
    c->connector_type = DRM_MODE_CONNECTOR_HDMIA;
    c->connector_type_id = 1;
    c->connection = DRM_MODE_CONNECTED;
    c->mmWidth = 520; c->mmHeight = 290;
    c->modes = calloc(16, sizeof(drmModeModeInfo));
    for (const char *p = list; *p && c->count_modes < 16; ) {
        int w, h, n = 0;
        if (sscanf(p, "%dx%d%n", &w, &h, &n) != 2) break;
        mode_fill(&c->modes[c->count_modes], w, h, c->count_modes == 0);
        c->count_modes++;
        p += n;
        if (*p == ',') p++;
    }
    if (!c->count_modes) { mode_fill(&c->modes[0], 1280, 720, 1); c->count_modes = 1; }
    c->count_encoders = 1;
    c->encoders = calloc(1, sizeof(uint32_t));
    c->encoders[0] = 50;
    return c;
}

void drmModeFreeConnector(drmModeConnectorPtr c)
{
    if (!c) return;
    free(c->modes); free(c->encoders); free(c->props); free(c->prop_values); free(c);
}

drmModeEncoderPtr drmModeGetEncoder(int fd, uint32_t id)
{
    (void)fd;
    drmModeEncoderPtr e = calloc(1, sizeof *e);
    e->encoder_id = id;
    e->encoder_type = DRM_MODE_ENCODER_TMDS;
    e->crtc_id = 30;
    e->possible_crtcs = 1;
    return e;
}

void drmModeFreeEncoder(drmModeEncoderPtr e) { free(e); }

drmModeCrtcPtr drmModeGetCrtc(int fd, uint32_t id)
{
    (void)fd;
    drmModeCrtcPtr c = calloc(1, sizeof *c);
    c->crtc_id = id;
    return c;
}

void drmModeFreeCrtc(drmModeCrtcPtr c) { free(c); }

int drmModeAddFB(int fd, uint32_t w, uint32_t h, uint8_t depth, uint8_t bpp,
                 uint32_t pitch, uint32_t handle, uint32_t *id)
{
    (void)fd; (void)depth;
    if (nfb >= 15) { errno = ENOMEM; return -1; }
    fb_handle[++nfb] = handle;
    *id = 100 + nfb;
    plog("addfb %ux%u bpp %u pitch %u handle %u -> %u\n", w, h, bpp, pitch, handle, *id);
    return 0;
}

int drmModeRmFB(int fd, uint32_t id) { (void)fd; (void)id; return 0; }

int drmModeSetCrtc(int fd, uint32_t crtc, uint32_t fb, uint32_t x, uint32_t y,
                   uint32_t *conns, int n, drmModeModeInfoPtr mode)
{
    (void)fd; (void)crtc; (void)x; (void)y; (void)conns; (void)n; (void)mode;
    unsigned i = fb - 100;
    if (fbh && i >= 1 && i < 16 && fb_handle[i] < 16) {
        fbh->front = dumb_off[fb_handle[i]];
        fbh->flips++;
    }
    return 0;
}

/* ------------------------------------------------------- the cabinet bus */
/* The cabinet switches (Start, coins, flippers, the coin door's buttons)
 * reach the BeagleBone on a GPIO parallel bus: the game drives a chip
 * select and reads eight data pins straight out of /dev/mem, with no gap a
 * helper thread could fill.  So the one routine that reads them each loop
 * (pin 1.0.2: 0x5667c, `void read(uint8_t out[2])`) is sent here instead.
 * The hook is only placed over the exact bytes this build has there. */
static void pf_cab_read(uint8_t *out)
{
    io_open();
    if (!io) { out[0] = out[1] = 0xff; return; }
    out[0] = ~io->sw[8];
    out[1] = ~io->sw[9];
    io->cab_reads++;
}

struct hook { uint32_t addr; uint8_t orig[8]; void *to; };
static const struct hook hooks[] = {
    { 0x5667c, {0xaf, 0x4b, 0x2d, 0xe9, 0xf0, 0x0f, 0xa2, 0xb0}, (void *)pf_cab_read },
};

__attribute__((constructor)) static void pf_hooks(void)
{
    extern char *program_invocation_short_name;
    /* LD_PRELOAD reaches the shell that starts the game, too */
    if (strcmp(program_invocation_short_name, "pin")) return;
    for (unsigned i = 0; i < sizeof hooks / sizeof hooks[0]; i++) {
        const struct hook *h = &hooks[i];
        uint8_t *p = (uint8_t *)(uintptr_t)h->addr;
        if (memcmp(p, h->orig, sizeof h->orig)) {
            plog("hook %#x: not this build's code there, left alone\n", h->addr);
            continue;
        }
        uintptr_t page = (uintptr_t)p & ~4095u;
        if (mprotect((void *)page, 8192, PROT_READ | PROT_WRITE | PROT_EXEC)) {
            plog("hook %#x: mprotect: %s\n", h->addr, strerror(errno));
            continue;
        }
        /* ldr.w pc, [pc, #0] ; .word target  (the address is 4-aligned, so
         * the literal sits right after the instruction; bit 0 of the target
         * picks Thumb or ARM) */
        uint32_t to = (uint32_t)(uintptr_t)h->to;
        p[0] = 0xdf; p[1] = 0xf8; p[2] = 0x00; p[3] = 0xf0;
        memcpy(p + 4, &to, 4);
        __builtin___clear_cache((char *)p, (char *)p + 8);
        mprotect((void *)page, 8192, PROT_READ | PROT_EXEC);
        plog("hook %#x -> %#x\n", h->addr, to);
    }
}
