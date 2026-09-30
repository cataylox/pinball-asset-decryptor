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
 *     the board (then tries COM4, then retries forever);
 *   - lets a WRITE to it wait as long as it takes: Mono polls the port for
 *     POLLOUT with the game's 20 ms WriteTimeout, the game counts every
 *     timeout as a comms error, and after ten it resets its board link and
 *     stops reacting to switches.  A real Warden at 115200 baud paces the
 *     game the same way - a slow moment on the PC must not look like a
 *     dead board (PAD-266).  Reads keep their timeout.
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
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

/* The last descriptor the game opened on the board (Mono reopens it after
 * a comms reset). */
static int warden_fd = -1;

static const char *map_path(const char *path) {
    const char *w = getenv("SPK_WARDEN");
    if (path && w && *w && strcmp(path, "/dev/WARDEN") == 0)
        return w;
    return path;
}

static int opened(const char *path, int fd) {
    if (fd >= 0 && path && strcmp(path, "/dev/WARDEN") == 0 && getenv("SPK_WARDEN"))
        warden_fd = fd;
    return fd;
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
    return opened(path, real_open(map_path(path), flags, mode));
}

int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    OPEN_MODE(flags, mode);
    REAL(open64);
    return opened(path, real_open64(map_path(path), flags, mode));
}

int openat(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    OPEN_MODE(flags, mode);
    REAL(openat);
    return opened(path, real_openat(dirfd, map_path(path), flags, mode));
}

int openat64(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    OPEN_MODE(flags, mode);
    REAL(openat64);
    return opened(path, real_openat64(dirfd, map_path(path), flags, mode));
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

/* Mono opens the port O_NONBLOCK and reports ANY failed write as a
 * TimeoutException - including EAGAIN when the line is momentarily full.  On
 * the board's line, wait for room and carry on instead. */
ssize_t write(int fd, const void *buf, size_t n) {
    REAL(write);
    REAL(poll);
    ssize_t r = real_write(fd, buf, n);
    while (r < 0 && errno == EAGAIN && fd == warden_fd) {
        struct pollfd p = { .fd = fd, .events = POLLOUT };
        if (real_poll(&p, 1, -1) < 0 && errno != EINTR)
            return -1;
        r = real_write(fd, buf, n);
    }
    return r;
}

int poll(struct pollfd *fds, nfds_t nfds, int timeout) {
    REAL(poll);
    if (timeout >= 0 && warden_fd >= 0) {
        for (nfds_t i = 0; i < nfds; i++)
            if (fds[i].fd == warden_fd && (fds[i].events & POLLOUT)
                    && !(fds[i].events & POLLIN))
                return real_poll(fds, nfds, -1);
    }
    return real_poll(fds, nfds, timeout);
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
