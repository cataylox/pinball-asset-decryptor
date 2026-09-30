/*
 * spkshim.c - LD_PRELOAD shim that shows a Spooky Unity game (Beetlejuice)
 * the rig's emulated Warden board instead of the real USB one.
 *
 * Warden.Connect() opens "/dev/WARDEN" (the machine's udev symlink for the
 * USB product "WARDEN") with Mono's SerialPort.  spkwarden.py serves the
 * board on a pty; this shim only
 *
 *   - REWRITES THE PATH: /dev/WARDEN -> $SPK_WARDEN (the pty's slave), so
 *     every slot has its own board without touching the shared /dev;
 *   - makes the modem-line ioctls succeed on it: Mono sets DtrEnable right
 *     after Open(), a pty refuses TIOCMGET/TIOCMSET/TIOCMBIS/TIOCMBIC with
 *     ENOTTY, Mono turns that into an IOException, and the game gives up on
 *     the board (then tries COM4, then retries forever).
 *
 * Unity's Mono reaches the port through libMonoPosixHelper's open() and
 * ioctl() in libc, which is what this interposes.  build.sh proves no symbol
 * needs a glibc newer than 2.34.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

static const char *map_path(const char *path) {
    const char *w = getenv("SPK_WARDEN");
    if (path && w && *w && strcmp(path, "/dev/WARDEN") == 0)
        return w;
    return path;
}

#define REAL(name) \
    static __typeof__(&name) real_##name; \
    if (!real_##name) real_##name = dlsym(RTLD_NEXT, #name)

#define OPEN_MODE(flags, mode) \
    if (flags & (O_CREAT | O_TMPFILE)) { \
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); \
    }

int open(const char *path, int flags, ...) {
    mode_t mode = 0;
    OPEN_MODE(flags, mode);
    REAL(open);
    return real_open(map_path(path), flags, mode);
}

int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    OPEN_MODE(flags, mode);
    REAL(open64);
    return real_open64(map_path(path), flags, mode);
}

int openat(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    OPEN_MODE(flags, mode);
    REAL(openat);
    return real_openat(dirfd, map_path(path), flags, mode);
}

int openat64(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    OPEN_MODE(flags, mode);
    REAL(openat64);
    return real_openat64(dirfd, map_path(path), flags, mode);
}

int access(const char *path, int how) {
    REAL(access);
    return real_access(map_path(path), how);
}

/* Mono's File.Exists and friends stat the port name first on some paths. */
int stat(const char *path, struct stat *st) {
    static int (*real)(const char *, struct stat *);
    if (!real) real = dlsym(RTLD_NEXT, "stat");
    return real(map_path(path), st);
}

int stat64(const char *path, struct stat64 *st) {
    static int (*real)(const char *, struct stat64 *);
    if (!real) real = dlsym(RTLD_NEXT, "stat64");
    return real(map_path(path), st);
}

int ioctl(int fd, unsigned long req, ...) {
    va_list ap;
    va_start(ap, req);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    REAL(ioctl);
    int r = real_ioctl(fd, req, arg);
    if (r < 0 && errno == ENOTTY && isatty(fd)) {
        switch (req) {
        case TIOCMGET:
            if (arg) *(int *)arg = TIOCM_DTR | TIOCM_RTS | TIOCM_CTS | TIOCM_DSR | TIOCM_CAR;
            return 0;
        case TIOCMSET:
        case TIOCMBIS:
        case TIOCMBIC:
            return 0;
        }
    }
    return r;
}
