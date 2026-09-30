/* dpinput.c - switch input for a Dutch Pinball game on a PC.
 *
 * LD_PRELOADed into the game (`start`, a PyInstaller build over pygame and
 * the SDL 1.2 it bundles).  The game runs on FakePinPROC (argv fakepinproc),
 * which turns pygame KEYDOWN/KEYUP into switch events through the build's own
 * config/keyboard.yaml (1 = Start, n/m = flippers, 7/8/9/0 = service
 * buttons, ...).  A key has to reach pygame's event queue, and a hidden run
 * has nobody to type into its window - and PAD-Runtime has no xdotool or
 * XTest library to fake one.  So this shim puts the event straight onto
 * SDL's queue: a thread reads commands from the FIFO named by $DPEMU_FIFO
 * and calls SDL_PushEvent, which is thread-safe in SDL 1.2 (it takes the
 * queue lock).  No window focus, no X server involvement.
 *
 * Commands, one per line:
 *     down <keysym>        key pressed      (keysym = SDL 1.2 number:
 *     up <keysym>          key released      '1' = 49, 'n' = 110, left = 276)
 *     tap <keysym> [ms]    press, hold ms (default 150), release
 *
 * It also writes the video mode the game sets (SDL_SetVideoMode) to
 * $DPEMU_LOG, so the rig knows the window size without X tools, and for a
 * run on the desktop frames the window and labels its title (below).
 *
 * Build: gcc -shared -fPIC -O2 -o dpinput.so dpinput.c -ldl -lpthread
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* SDL 1.2 event layout (SDL_events.h, SDL_keyboard.h). */
enum { EV_KEYDOWN = 2, EV_KEYUP = 3 };
typedef struct {
    uint8_t scancode;
    int sym;            /* SDLKey */
    int mod;            /* SDLMod */
    uint16_t unicode;
} dp_keysym;
typedef struct {
    uint8_t type, which, state;
    dp_keysym keysym;
} dp_keyevent;
typedef union {
    uint8_t type;
    dp_keyevent key;
    uint8_t pad[64];    /* SDL_Event is 20 bytes; room to spare */
} dp_event;

static void logf_(const char *fmt, ...)
{
    const char *path = getenv("DPEMU_LOG");
    FILE *f;
    va_list ap;
    if (!path || !(f = fopen(path, "a")))
        return;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fclose(f);
}

/* SDL itself.  pygame's modules dlopen it RTLD_LOCAL (Python's default), so
 * neither RTLD_DEFAULT nor RTLD_NEXT can see its symbols from here: ask for
 * the already-loaded library by name. */
static void *sdl_sym(const char *name)
{
    static void *lib;
    if (!lib)
        lib = dlopen("libSDL-1.2.so.0", RTLD_LAZY | RTLD_NOLOAD);
    return lib ? dlsym(lib, name) : NULL;
}

static int push(dp_event *ev)
{
    static int (*sdl_push)(dp_event *);
    if (!sdl_push)
        sdl_push = (int (*)(dp_event *))sdl_sym("SDL_PushEvent");
    if (!sdl_push) {
        logf_("input: SDL_PushEvent not loaded yet\n");
        return -1;
    }
    return sdl_push(ev);
}

static void key(int sym, int down)
{
    dp_event ev;
    memset(&ev, 0, sizeof ev);
    ev.key.type = down ? EV_KEYDOWN : EV_KEYUP;
    ev.key.state = down ? 1 : 0;
    ev.key.keysym.sym = sym;
    ev.key.keysym.unicode = (sym > 0 && sym < 128) ? sym : 0;
    push(&ev);
}

static void sleep_ms(int ms)
{
    struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L };
    while (nanosleep(&ts, &ts) == -1 && errno == EINTR)
        ;
}

static void run_line(char *line)
{
    char cmd[16];
    int a = 0, b = -1;
    int n = sscanf(line, "%15s %d %d", cmd, &a, &b);
    if (n < 2)
        return;
    if (!strcmp(cmd, "down"))
        key(a, 1);
    else if (!strcmp(cmd, "up"))
        key(a, 0);
    else if (!strcmp(cmd, "tap")) {
        key(a, 1);
        sleep_ms(n == 3 && b > 0 ? b : 150);
        key(a, 0);
    } else
        return;
    logf_("input: %s", line);
}

static void *reader(void *arg)
{
    const char *path = arg;
    char buf[512], line[512];
    size_t used = 0;
    /* O_RDWR: the FIFO never reports EOF when a writer goes away. */
    int fd = open(path, O_RDWR);
    if (fd < 0) {
        logf_("input: cannot open %s: %s\n", path, strerror(errno));
        return NULL;
    }
    logf_("input: listening on %s\n", path);
    for (;;) {
        ssize_t got = read(fd, buf, sizeof buf);
        if (got <= 0) {
            if (got < 0 && errno == EINTR)
                continue;
            sleep_ms(100);
            continue;
        }
        for (ssize_t i = 0; i < got; i++) {
            if (buf[i] == '\n' || used == sizeof line - 2) {
                line[used++] = '\n';
                line[used] = 0;
                run_line(line);
                used = 0;
            } else
                line[used++] = buf[i];
        }
    }
    return NULL;
}

/* The reader starts with the game's first window, not at load: the
 * PyInstaller bootloader re-executes itself (so LD_PRELOAD must stay in the
 * environment for the real game process), and anything the game shells out
 * to inherits it too.  Only the process that opens a window reads the FIFO. */
static void start_reader(void)
{
    static int started;
    const char *path = getenv("DPEMU_FIFO");
    pthread_t t;
    if (started || !path || !*path)
        return;
    started = 1;
    pthread_create(&t, NULL, reader, strdup(path));
    pthread_detach(t);
}

/* The window: log every mode the game sets.  On a desktop ($DPEMU_FRAME)
 * give it a frame: the game asks for a borderless one (SDL_NOFRAME, a
 * cabinet LCD has nothing else on it), which on a PC is a slab with no title
 * bar to drag.  SDL 1.2 places it at $SDL_VIDEO_WINDOW_POS. */
#define DP_SDL_NOFRAME 0x00000020u
void *SDL_SetVideoMode(int w, int h, int bpp, uint32_t flags)
{
    static void *(*real)(int, int, int, uint32_t);
    if (!real)
        real = (void *(*)(int, int, int, uint32_t))sdl_sym("SDL_SetVideoMode");
    if (getenv("DPEMU_FRAME"))
        flags &= ~DP_SDL_NOFRAME;
    logf_("video: %dx%d bpp %d flags 0x%x\n", w, h, bpp, flags);
    start_reader();
    return real ? real(w, h, bpp, flags) : NULL;
}

/* The title: "<$DPEMU_LABEL> - <the game's>", so a window on the desktop
 * says which ticket or app run it belongs to (every rig window does). */
void SDL_WM_SetCaption(const char *title, const char *icon)
{
    static void (*real)(const char *, const char *);
    const char *label = getenv("DPEMU_LABEL");
    char buf[256];
    if (!real)
        real = (void (*)(const char *, const char *))sdl_sym("SDL_WM_SetCaption");
    if (!real)
        return;
    if (label && *label && title) {
        snprintf(buf, sizeof buf, "%s - %s", label, title);
        real(buf, icon);
    } else
        real(title, icon);
}
