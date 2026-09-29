/*
 * bofhwshim.c - LD_PRELOAD shim that shows a Barrels of Fun game the
 * emulated FAST / BICS serial ports instead of real USB hardware.
 *
 * A BoF title is a native x86-64 Godot export.  Its engine carries the
 * wjwwood `serial` library, whose Linux port enumeration
 *
 *   glob("/dev/ttyACM*") ... then per port
 *   realpath("/sys/class/tty/<name>/device") -> dirname -> read
 *   manufacturer / product / serial / idVendor / idProduct
 *
 * is how the game tells the FAST Neuron (desc contains "FAST Pinball") from
 * the BICS board (hw_id contains "PID=2341:", an Arduino).  bofhw.py makes a
 * pty per port, links it into $BOFHW_DEV (ttyACM0 -> /dev/pts/N) and writes a
 * matching fake sysfs tree under $BOFHW_SYS.  This shim only REWRITES PATHS:
 *
 *   /dev/ttyACM*, /dev/ttyUSB*      -> $BOFHW_DEV/...  (real ones are hidden)
 *   /dev/<name> present in $BOFHW_DEV (e.g. bof_worm) -> $BOFHW_DEV/<name>
 *   /sys/class/tty/ttyACM* | ttyUSB* -> $BOFHW_SYS/class/tty/...
 *
 * plus one behaviour fix: a pty refuses the modem-line ioctls (TIOCMBIS for
 * set_dtr/set_rts), and wjwwood THROWS on that failure, which would abort the
 * game.  Those ioctls report success on a tty.
 *
 * No symbol needs a glibc newer than 2.34 (dlsym's version since libdl moved
 * into libc; build.sh proves it), and the game itself needs 2.33, so the .so
 * loads wherever the game does.  stat/stat64 are resolved at run time so a
 * glibc without the 2.33 stat exports still works.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

#define PATHMAX 4096

static const char *dev_root(void) { return getenv("BOFHW_DEV"); }
static const char *sys_root(void) { return getenv("BOFHW_SYS"); }

static int starts(const char *s, const char *p) {
    return strncmp(s, p, strlen(p)) == 0;
}

/* Rewrite `path` into `buf` when it names an emulated device or its sysfs
 * entry.  Returns buf, or the original path when nothing applies. */
static const char *map_path(const char *path, char *buf) {
    const char *dev = dev_root(), *sys = sys_root();
    if (!path)
        return path;
    if (dev && starts(path, "/dev/") && !strchr(path + 5, '/')) {
        const char *name = path + 5;
        int serial = starts(name, "ttyACM") || starts(name, "ttyUSB");
        snprintf(buf, PATHMAX, "%s/%s", dev, name);
        if (serial)
            return buf;
        static int (*real_access)(const char *, int);
        if (!real_access)
            real_access = dlsym(RTLD_NEXT, "access");
        if (real_access && real_access(buf, F_OK) == 0)
            return buf;
        return path;
    }
    if (sys && starts(path, "/sys/class/tty/")) {
        const char *name = path + 15;
        if (starts(name, "ttyACM") || starts(name, "ttyUSB")) {
            snprintf(buf, PATHMAX, "%s/%s", sys, path + 5);
            return buf;
        }
    }
    return path;
}

#define REAL(name) \
    static __typeof__(&name) real_##name; \
    if (!real_##name) real_##name = dlsym(RTLD_NEXT, #name)

int open(const char *path, int flags, ...) {
    char buf[PATHMAX];
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    REAL(open);
    return real_open(map_path(path, buf), flags, mode);
}

int open64(const char *path, int flags, ...) {
    char buf[PATHMAX];
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    REAL(open64);
    return real_open64(map_path(path, buf), flags, mode);
}

int openat(int dirfd, const char *path, int flags, ...) {
    char buf[PATHMAX];
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    REAL(openat);
    return real_openat(dirfd, map_path(path, buf), flags, mode);
}

int openat64(int dirfd, const char *path, int flags, ...) {
    char buf[PATHMAX];
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    REAL(openat64);
    return real_openat64(dirfd, map_path(path, buf), flags, mode);
}

FILE *fopen(const char *path, const char *mode) {
    char buf[PATHMAX];
    REAL(fopen);
    return real_fopen(map_path(path, buf), mode);
}

FILE *fopen64(const char *path, const char *mode) {
    char buf[PATHMAX];
    REAL(fopen64);
    return real_fopen64(map_path(path, buf), mode);
}

int access(const char *path, int amode) {
    char buf[PATHMAX];
    REAL(access);
    return real_access(map_path(path, buf), amode);
}

char *realpath(const char *path, char *resolved) {
    char buf[PATHMAX];
    REAL(realpath);
    return real_realpath(map_path(path, buf), resolved);
}

/* stat/stat64 are real exported functions from glibc 2.33 on; older glibc
 * only has __xstat.  Resolve lazily so the shim loads on both. */
int stat64(const char *path, struct stat64 *st) {
    char buf[PATHMAX];
    static int (*real)(const char *, struct stat64 *);
    static int (*real_x)(int, const char *, struct stat64 *);
    if (!real && !real_x) {
        real = dlsym(RTLD_NEXT, "stat64");
        if (!real)
            real_x = dlsym(RTLD_NEXT, "__xstat64");
    }
    if (real)
        return real(map_path(path, buf), st);
    return real_x(1, map_path(path, buf), st);
}

int stat(const char *path, struct stat *st) {
    char buf[PATHMAX];
    static int (*real)(const char *, struct stat *);
    static int (*real_x)(int, const char *, struct stat *);
    if (!real && !real_x) {
        real = dlsym(RTLD_NEXT, "stat");
        if (!real)
            real_x = dlsym(RTLD_NEXT, "__xstat");
    }
    if (real)
        return real(map_path(path, buf), st);
    return real_x(1, map_path(path, buf), st);
}

/* glob("/dev/ttyACM*") must list the emulated ports under their /dev names:
 * glob the pattern inside $BOFHW_DEV, then rename what it appended.  glibc
 * frees every gl_pathv entry separately, so each can be swapped for its own
 * allocation. */
static int remap_glob(const char *pattern, int flags,
                      int (*errfunc)(const char *, int), void *pglob,
                      int is64) {
    char fake[PATHMAX];
    const char *dev = dev_root();
    glob_t *g = pglob;           /* glob_t and glob64_t share their layout */
    size_t before = (flags & GLOB_APPEND) ? g->gl_pathc : 0;
    int rc;
    snprintf(fake, sizeof fake, "%s/%s", dev, pattern + 5);
    if (is64) {
        static int (*real)(const char *, int, int (*)(const char *, int), void *);
        if (!real) real = dlsym(RTLD_NEXT, "glob64");
        rc = real(fake, flags, errfunc, pglob);
    } else {
        static int (*real)(const char *, int, int (*)(const char *, int), void *);
        if (!real) real = dlsym(RTLD_NEXT, "glob");
        rc = real(fake, flags, errfunc, pglob);
    }
    size_t offs = (flags & GLOB_DOOFFS) ? g->gl_offs : 0;
    size_t dlen = strlen(dev);
    for (size_t i = before; i < g->gl_pathc; i++) {
        char *p = g->gl_pathv[offs + i];
        if (p && strncmp(p, dev, dlen) == 0 && p[dlen] == '/') {
            char *n = malloc(strlen(p) - dlen + 5);
            if (!n)
                continue;
            strcpy(n, "/dev");
            strcat(n, p + dlen);
            free(p);
            g->gl_pathv[offs + i] = n;
        }
    }
    return rc;
}

static int wants_remap(const char *pattern) {
    return dev_root() && pattern &&
           (starts(pattern, "/dev/ttyACM") || starts(pattern, "/dev/ttyUSB"));
}

int glob64(const char *pattern, int flags,
           int (*errfunc)(const char *, int), glob64_t *pglob) {
    if (wants_remap(pattern))
        return remap_glob(pattern, flags, errfunc, pglob, 1);
    static int (*real)(const char *, int, int (*)(const char *, int), glob64_t *);
    if (!real) real = dlsym(RTLD_NEXT, "glob64");
    return real(pattern, flags, errfunc, pglob);
}

int glob(const char *pattern, int flags,
         int (*errfunc)(const char *, int), glob_t *pglob) {
    if (wants_remap(pattern))
        return remap_glob(pattern, flags, errfunc, pglob, 0);
    static int (*real)(const char *, int, int (*)(const char *, int), glob_t *);
    if (!real) real = dlsym(RTLD_NEXT, "glob");
    return real(pattern, flags, errfunc, pglob);
}

int ioctl(int fd, unsigned long req, ...) {
    va_list ap;
    va_start(ap, req);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    REAL(ioctl);
    int rc = real_ioctl(fd, req, arg);
    if (rc == -1 && (req == TIOCMBIS || req == TIOCMBIC || req == TIOCMSET ||
                     req == TIOCMGET) && isatty(fd)) {
        if (req == TIOCMGET && arg)
            *(int *)arg = TIOCM_DTR | TIOCM_RTS | TIOCM_CTS | TIOCM_DSR | TIOCM_CD;
        errno = 0;
        return 0;
    }
    return rc;
}
