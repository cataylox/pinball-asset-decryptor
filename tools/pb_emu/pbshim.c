/*
 * pbshim.c - LD_PRELOAD shim that puts Pinball Brothers' Predator on the rig
 * instead of the machine.
 *
 * Predator is two native programs: pinprog (the rules, FreeWPC-derived C,
 * talking to a FAST Neuron over two USB CDC ports) and vidprog (the screen,
 * SDL2 + GStreamer), joined by TCP on 127.0.0.1:5555 (pinprog listens).  This
 * shim only rewrites WHERE they reach:
 *
 *   /dev/ttyACM0, /dev/ttyACM1   -> $PB_DEV/ttyACM0, 1 (pbfast.py's ptys)
 *   TCP port 5555 (bind/connect) -> $PB_VIDPORT, so several rigs can run at
 *                                   once without a network namespace (which
 *                                   would hide the rig's Xvfb, whose only
 *                                   socket in PAD-Runtime is abstract)
 *
 * plus one behaviour fix: a pty refuses the modem-line ioctls (DTR/RTS), which
 * a USB CDC port accepts; those report success.
 *
 * Nothing needs a glibc newer than 2.34 (build.sh proves it); the game needs
 * 2.39.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <termios.h>
#include <unistd.h>

#define PATHMAX 4096
#define GAME_VIDEO_PORT 5555

#define REAL(name) \
    static __typeof__(&name) real_##name; \
    if (!real_##name) real_##name = dlsym(RTLD_NEXT, #name)

static const char *map_path(const char *path, char *buf) {
    const char *dev = getenv("PB_DEV");
    if (dev && path && strncmp(path, "/dev/ttyACM", 11) == 0
            && !strchr(path + 5, '/')) {
        snprintf(buf, PATHMAX, "%s/%s", dev, path + 5);
        return buf;
    }
    return path;
}

#define OPEN_MODE(flags) \
    mode_t mode = 0; \
    if ((flags) & (O_CREAT | O_TMPFILE)) { \
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); \
    }

int open(const char *path, int flags, ...) {
    char buf[PATHMAX];
    OPEN_MODE(flags);
    REAL(open);
    return real_open(map_path(path, buf), flags, mode);
}

int open64(const char *path, int flags, ...) {
    char buf[PATHMAX];
    OPEN_MODE(flags);
    REAL(open64);
    return real_open64(map_path(path, buf), flags, mode);
}

int openat(int dirfd, const char *path, int flags, ...) {
    char buf[PATHMAX];
    OPEN_MODE(flags);
    REAL(openat);
    return real_openat(dirfd, map_path(path, buf), flags, mode);
}

int openat64(int dirfd, const char *path, int flags, ...) {
    char buf[PATHMAX];
    OPEN_MODE(flags);
    REAL(openat64);
    return real_openat64(dirfd, map_path(path, buf), flags, mode);
}

int access(const char *path, int amode) {
    char buf[PATHMAX];
    REAL(access);
    return real_access(map_path(path, buf), amode);
}

/* The video link's port, moved to this rig's. */
static const struct sockaddr *map_addr(const struct sockaddr *sa,
                                       socklen_t len, struct sockaddr_in *buf) {
    const char *p = getenv("PB_VIDPORT");
    if (!p || !sa || sa->sa_family != AF_INET || len < sizeof(*buf))
        return sa;
    memcpy(buf, sa, sizeof(*buf));
    if (ntohs(buf->sin_port) != GAME_VIDEO_PORT)
        return sa;
    unsigned port = 0;          /* not atoi: glibc 2.38 redirects it */
    while (*p >= '0' && *p <= '9')
        port = port * 10 + (unsigned)(*p++ - '0');
    buf->sin_port = htons((unsigned short)port);
    return (const struct sockaddr *)buf;
}

int bind(int fd, const struct sockaddr *sa, socklen_t len) {
    struct sockaddr_in buf;
    REAL(bind);
    return real_bind(fd, map_addr(sa, len, &buf), len);
}

int connect(int fd, const struct sockaddr *sa, socklen_t len) {
    struct sockaddr_in buf;
    REAL(connect);
    return real_connect(fd, map_addr(sa, len, &buf), len);
}

int ioctl(int fd, unsigned long req, ...) {
    va_list ap;
    va_start(ap, req);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    REAL(ioctl);
    int r = real_ioctl(fd, req, arg);
    if (r < 0 && isatty(fd) && (req == TIOCMBIS || req == TIOCMBIC
                                || req == TIOCMSET)) {
        return 0;
    }
    if (r < 0 && isatty(fd) && req == TIOCMGET && arg) {
        *(int *)arg = TIOCM_DTR | TIOCM_RTS | TIOCM_CTS | TIOCM_DSR;
        return 0;
    }
    return r;
}
