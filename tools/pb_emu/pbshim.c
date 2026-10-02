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
 * plus three behaviour fixes:
 *
 *   - a pty refuses the modem-line ioctls (DTR/RTS), which a USB CDC port
 *     accepts; those report success.
 *   - mlockall() is a no-op.  pinprog locks all its memory, present and
 *     FUTURE, as a real-time cabinet program; under an ordinary user's
 *     RLIMIT_MEMLOCK every later mmap then fails with EAGAIN - PulseAudio's
 *     shared-memory pool among them ("mmap() failed: Resource temporarily
 *     unavailable"), so SDL_mixer opened no sound and the game was silent
 *     (PAD-313).
 *   - on the desktop (PB_WINDOWED=1, run_game.sh --visible) vidprog's window
 *     gets a title bar: its SDL_CreateWindow flags lose BORDERLESS and
 *     FULLSCREEN and gain RESIZABLE, and it opens near the top left.  The
 *     cabinet's borderless 1920x1080 slab could not be moved (PAD-313).  A
 *     hidden run keeps the window exactly as the machine makes it.
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

/* No memory locking on a PC: see the header (the game's sound). */
int mlockall(int flags) {
    (void)flags;
    return 0;
}

/* SDL2's window and renderer calls, without SDL's headers.  Flag values
 * from SDL_video.h (stable ABI across SDL 2.x).
 *
 * On the desktop the window gets a title bar, opens near the top left at
 * PB_WIN_W x PB_WIN_H (default 1280x720, so it fits a 1080p screen with its
 * title bar) and can be resized: vidprog draws in 1920x1080 coordinates with
 * no logical size of its own, so the renderer is given the game's size as
 * its logical size and SDL scales the picture to whatever the window is. */
typedef struct SDL_Window SDL_Window;
typedef struct SDL_Renderer SDL_Renderer;
#define PB_SDL_FULLSCREEN         0x00000001u
#define PB_SDL_FULLSCREEN_DESKTOP 0x00001001u
#define PB_SDL_BORDERLESS         0x00000010u
#define PB_SDL_RESIZABLE          0x00000020u
SDL_Window *SDL_CreateWindow(const char *title, int x, int y, int w, int h,
                             unsigned int flags);
SDL_Renderer *SDL_CreateRenderer(SDL_Window *window, int index,
                                 unsigned int flags);

static int pb_windowed(void) {
    const char *v = getenv("PB_WINDOWED");
    return v && v[0] == '1';
}

static int pb_env_int(const char *name, int dflt) {
    /* by hand: atoi/strtol pull in glibc 2.38's __isoc23_strtol (build.sh) */
    const char *v = getenv(name);
    int n = 0;
    for (; v && *v >= '0' && *v <= '9' && n < 100000; v++) n = n * 10 + (*v - '0');
    return n > 0 ? n : dflt;
}

/* the game's own drawing size, from its window call */
static int game_w, game_h;

SDL_Window *SDL_CreateWindow(const char *title, int x, int y, int w, int h,
                             unsigned int flags) {
    REAL(SDL_CreateWindow);
    if (!real_SDL_CreateWindow) return NULL;
    if (pb_windowed()) {
        unsigned int was = flags;
        flags &= ~(PB_SDL_FULLSCREEN_DESKTOP | PB_SDL_FULLSCREEN | PB_SDL_BORDERLESS);
        flags |= PB_SDL_RESIZABLE;
        game_w = w;
        game_h = h;
        x = 40;
        y = 40;
        w = pb_env_int("PB_WIN_W", 1280);
        h = pb_env_int("PB_WIN_H", 720);
        fprintf(stderr, "pbshim: window \"%s\" %dx%d flags 0x%x -> %dx%d flags 0x%x "
                "(windowed)\n", title ? title : "", game_w, game_h, was, w, h, flags);
    }
    return real_SDL_CreateWindow(title, x, y, w, h, flags);
}

SDL_Renderer *SDL_CreateRenderer(SDL_Window *window, int index,
                                 unsigned int flags) {
    REAL(SDL_CreateRenderer);
    if (!real_SDL_CreateRenderer) return NULL;
    SDL_Renderer *r = real_SDL_CreateRenderer(window, index, flags);
    if (r && pb_windowed() && game_w > 0 && game_h > 0) {
        int (*logical)(SDL_Renderer *, int, int) =
            (int (*)(SDL_Renderer *, int, int))dlsym(RTLD_NEXT, "SDL_RenderSetLogicalSize");
        if (logical) {
            int rc = logical(r, game_w, game_h);
            fprintf(stderr, "pbshim: renderer logical size %dx%d (%d)\n",
                    game_w, game_h, rc);
        }
    }
    return r;
}
