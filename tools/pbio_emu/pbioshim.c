/*
 * pbioshim.c - LD_PRELOAD shim for vidprog, the screen program of Pinball
 * Brothers' Alien and ABBA, on the I/O-board rig (run_game.sh).  It runs
 * INSIDE the machine's own root (a chroot of its Buildroot image, glibc
 * 2.30), so it is built against that: build.sh proves no symbol asks for a
 * newer glibc, and takes dlsym from libdl.so.2 as glibc 2.30 has it.
 *
 * On the desktop (PBIO_WINDOWED=1, run_game.sh --visible) the game's
 * windows become ones a person can move and resize (PAD-322):
 *
 *   - SDL_CreateWindow loses BORDERLESS / FULLSCREEN and gains RESIZABLE, so
 *     each window has a title bar.  The machine asks for borderless slabs
 *     the size of its LCDs, placed on one X screen (PBIO_SCREEN, WxH: Alien
 *     2166x768 = the 1366x768 main LCD and the 800x480 Airlock to its right;
 *     ABBA one 1920x1080).  Every window is scaled by ONE factor that fits
 *     that whole screen inside PBIO_WIN_W x PBIO_WIN_H (default 1600x900),
 *     and placed at its scaled position from the top left - so Alien's two
 *     windows open side by side, as on the cabinet.
 *   - vidprog draws in the LCDs' pixels and sets its own render scale and
 *     clip rectangles, so SDL's logical size cannot scale it (the game's
 *     own SDL_RenderSetScale would undo it).  Instead the game draws into a
 *     texture the size of its LCD, and every SDL_RenderPresent copies that
 *     texture onto the window, scaled to fit with black bars - so any
 *     window size shows the whole picture.  The game's scale, viewport,
 *     clip and draw colour on that texture are carried across the copy.
 *
 * Always (hidden or not): the renderer SDL picked goes to stderr, and every
 * 5 s the frames each window presented a second (in the order the game made
 * them; on a hidden run the machine's own windows all count as one) go to
 * $PBIO_FPS_LOG (run_game.sh: /mnt/log/fps.log), the proof the screen keeps
 * its pace.  A hidden run's windows are otherwise the machine's own.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define REAL(name) \
    static __typeof__(&name) real_##name; \
    if (!real_##name) real_##name = dlsym(RTLD_NEXT, #name)

/* SDL2's calls, without SDL's headers: values from SDL_video.h,
 * SDL_render.h, SDL_pixels.h, SDL_blendmode.h (stable ABI across SDL 2.x) */
typedef struct SDL_Window SDL_Window;
typedef struct SDL_Renderer SDL_Renderer;
typedef struct SDL_Texture SDL_Texture;
typedef struct { int x, y, w, h; } PbioRect;
typedef struct {                       /* SDL_RendererInfo */
    const char *name;
    unsigned int flags, num_texture_formats, texture_formats[16];
    int max_texture_width, max_texture_height;
} PbioRendererInfo;
#define SDL_FULLSCREEN         0x00000001u
#define SDL_FULLSCREEN_DESKTOP 0x00001001u
#define SDL_BORDERLESS         0x00000010u
#define SDL_RESIZABLE          0x00000020u
#define SDL_PIXELFORMAT_ARGB8888 0x16362004u
#define SDL_TEXTUREACCESS_TARGET 2
#define SDL_BLENDMODE_NONE 0

SDL_Window *SDL_CreateWindow(const char *title, int x, int y, int w, int h,
                             unsigned int flags);
SDL_Renderer *SDL_CreateRenderer(SDL_Window *window, int index,
                                 unsigned int flags);
void SDL_RenderPresent(SDL_Renderer *renderer);

/* looked up, not linked: the shim needs no SDL to build */
#define SDLFN(ret, name, args) \
    static ret (*name##_p) args; \
    if (!name##_p) name##_p = (ret (*) args)dlsym(RTLD_NEXT, #name)

static int pbio_windowed(void) {
    const char *v = getenv("PBIO_WINDOWED");
    return v && v[0] == '1';
}

/* by hand: no strtol (glibc 2.38's __isoc23_strtol does not exist in 2.30) */
static const char *read_int(const char *v, int *n) {
    *n = 0;
    for (; v && *v >= '0' && *v <= '9' && *n < 100000; v++) *n = *n * 10 + (*v - '0');
    return v;
}

static int env_int(const char *name, int dflt) {
    int n;
    read_int(getenv(name), &n);
    return n > 0 ? n : dflt;
}

/* "WxH" -> *w, *h; unchanged when unset or malformed */
static void env_size(const char *name, int *w, int *h) {
    int a, b = 0;
    const char *v = read_int(getenv(name), &a);
    if (v && (*v == 'x' || *v == 'X')) read_int(v + 1, &b);
    if (a > 0 && b > 0) { *w = a; *h = b; }
}

/* each of the game's windows (Alien has two): its LCD's size, its renderer
 * and the texture the game draws into */
#define MAXWIN 4
static struct win {
    SDL_Window *w;
    int game_w, game_h;
    SDL_Renderer *r;
    SDL_Texture *canvas;
} wins[MAXWIN];

static struct win *win_of_window(SDL_Window *w) {
    for (int i = 0; i < MAXWIN; i++) if (w && wins[i].w == w) return &wins[i];
    return NULL;
}

static struct win *win_of_renderer(SDL_Renderer *r) {
    for (int i = 0; i < MAXWIN; i++) if (r && wins[i].r == r) return &wins[i];
    return NULL;
}

/* SDL_WINDOWPOS_UNDEFINED / _CENTERED are no place on the screen */
static int pos_or_zero(int p) {
    unsigned int m = (unsigned int)p & 0xFFFF0000u;
    return (m == 0x1FFF0000u || m == 0x2FFF0000u) ? 0 : p;
}

SDL_Window *SDL_CreateWindow(const char *title, int x, int y, int w, int h,
                             unsigned int flags) {
    REAL(SDL_CreateWindow);
    if (!real_SDL_CreateWindow) return NULL;
    if (!pbio_windowed() || w <= 0 || h <= 0)
        return real_SDL_CreateWindow(title, x, y, w, h, flags);

    unsigned int was = flags;
    int gw = w, gh = h, ox = pos_or_zero(x), oy = pos_or_zero(y);
    int max_w = env_int("PBIO_WIN_W", 1600), max_h = env_int("PBIO_WIN_H", 900);
    int scr_w = ox + w, scr_h = oy + h;
    env_size("PBIO_SCREEN", &scr_w, &scr_h);
    /* one factor for every window: the whole screen fits, never enlarged */
    double f = 1.0;
    if (scr_w * f > max_w) f = (double)max_w / scr_w;
    if (scr_h * f > max_h) f = (double)max_h / scr_h;
    flags &= ~(SDL_FULLSCREEN_DESKTOP | SDL_FULLSCREEN | SDL_BORDERLESS);
    flags |= SDL_RESIZABLE;
    w = (int)(gw * f + 0.5);
    h = (int)(gh * f + 0.5);
    x = 40 + (int)(ox * f + 0.5);
    y = 40 + (int)(oy * f + 0.5);
    fprintf(stderr, "pbioshim: window \"%s\" %dx%d at %d,%d flags 0x%x -> %dx%d at %d,%d "
            "flags 0x%x (windowed)\n", title ? title : "", gw, gh, ox, oy, was, w, h, x, y,
            flags);
    SDL_Window *win = real_SDL_CreateWindow(title, x, y, w, h, flags);
    for (int i = 0; win && i < MAXWIN; i++) {
        if (!wins[i].w) {
            wins[i].w = win;
            wins[i].game_w = gw;
            wins[i].game_h = gh;
            break;
        }
    }
    return win;
}

SDL_Renderer *SDL_CreateRenderer(SDL_Window *window, int index,
                                 unsigned int flags) {
    REAL(SDL_CreateRenderer);
    if (!real_SDL_CreateRenderer) return NULL;
    SDL_Renderer *r = real_SDL_CreateRenderer(window, index, flags);
    SDLFN(int, SDL_GetRendererInfo, (SDL_Renderer *, PbioRendererInfo *));
    if (r && SDL_GetRendererInfo_p) {
        PbioRendererInfo info;
        memset(&info, 0, sizeof info);
        if (SDL_GetRendererInfo_p(r, &info) == 0)
            fprintf(stderr, "pbioshim: renderer \"%s\"\n", info.name ? info.name : "?");
    }
    struct win *wn = win_of_window(window);
    if (r && wn && !wn->canvas) {
        SDLFN(SDL_Texture *, SDL_CreateTexture, (SDL_Renderer *, unsigned int, int, int, int));
        SDLFN(int, SDL_SetRenderTarget, (SDL_Renderer *, SDL_Texture *));
        SDLFN(int, SDL_SetTextureBlendMode, (SDL_Texture *, int));
        SDLFN(void, SDL_DestroyTexture, (SDL_Texture *));
        if (SDL_CreateTexture_p && SDL_SetRenderTarget_p && SDL_SetTextureBlendMode_p) {
            SDL_Texture *t = SDL_CreateTexture_p(r, SDL_PIXELFORMAT_ARGB8888,
                                                 SDL_TEXTUREACCESS_TARGET,
                                                 wn->game_w, wn->game_h);
            if (t && SDL_SetRenderTarget_p(r, t) == 0) {
                SDL_SetTextureBlendMode_p(t, SDL_BLENDMODE_NONE);
                wn->canvas = t;
            } else if (t && SDL_DestroyTexture_p) {
                SDL_DestroyTexture_p(t);
            }
        }
        fprintf(stderr, "pbioshim: %s %dx%d canvas, scaled to the window\n",
                wn->canvas ? "drawing on a" : "NO (unscaled) -", wn->game_w, wn->game_h);
    }
    if (r && wn && !wn->r) wn->r = r;
    return r;
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

/* frames presented, per window (in the order the game made them; a
 * renderer the shim does not know counts as the first), logged every 5 s */
static void count_frame(struct win *wn) {
    static double since;
    static long frames[MAXWIN];
    double t = now_s();
    if (since == 0) since = t;
    frames[wn ? (int)(wn - wins) : 0]++;
    if (t - since >= 5.0) {
        const char *path = getenv("PBIO_FPS_LOG");
        FILE *f = path ? fopen(path, "a") : NULL;
        if (f) {
            fprintf(f, "%.0f fps", t);
            for (int i = 0; i < MAXWIN; i++)
                if (i == 0 || wins[i].w) fprintf(f, " %.1f", frames[i] / (t - since));
            fprintf(f, " (over %.1f s)\n", t - since);
            fclose(f);
        }
        since = t;
        memset(frames, 0, sizeof frames);
    }
}

void SDL_RenderPresent(SDL_Renderer *renderer) {
    REAL(SDL_RenderPresent);
    if (!real_SDL_RenderPresent) return;
    struct win *wn = win_of_renderer(renderer);
    count_frame(wn);
    if (!wn || !wn->canvas) {
        real_SDL_RenderPresent(renderer);
        return;
    }
    SDLFN(int, SDL_SetRenderTarget, (SDL_Renderer *, SDL_Texture *));
    SDLFN(int, SDL_GetRendererOutputSize, (SDL_Renderer *, int *, int *));
    SDLFN(int, SDL_GetRenderDrawColor, (SDL_Renderer *, unsigned char *, unsigned char *,
                                        unsigned char *, unsigned char *));
    SDLFN(int, SDL_SetRenderDrawColor, (SDL_Renderer *, unsigned char, unsigned char,
                                        unsigned char, unsigned char));
    SDLFN(int, SDL_RenderClear, (SDL_Renderer *));
    SDLFN(int, SDL_RenderCopy, (SDL_Renderer *, SDL_Texture *, const PbioRect *,
                                const PbioRect *));
    SDLFN(void, SDL_RenderGetScale, (SDL_Renderer *, float *, float *));
    SDLFN(int, SDL_RenderSetScale, (SDL_Renderer *, float, float));
    SDLFN(void, SDL_RenderGetViewport, (SDL_Renderer *, PbioRect *));
    SDLFN(int, SDL_RenderSetViewport, (SDL_Renderer *, const PbioRect *));
    SDLFN(void, SDL_RenderGetClipRect, (SDL_Renderer *, PbioRect *));
    SDLFN(int, SDL_RenderSetClipRect, (SDL_Renderer *, const PbioRect *));
    SDLFN(int, SDL_RenderIsClipEnabled, (SDL_Renderer *));
    if (!SDL_SetRenderTarget_p || !SDL_GetRendererOutputSize_p || !SDL_RenderCopy_p
            || !SDL_RenderClear_p || !SDL_GetRenderDrawColor_p || !SDL_SetRenderDrawColor_p
            || !SDL_RenderGetScale_p || !SDL_RenderSetScale_p || !SDL_RenderGetViewport_p
            || !SDL_RenderSetViewport_p || !SDL_RenderGetClipRect_p
            || !SDL_RenderSetClipRect_p || !SDL_RenderIsClipEnabled_p) {
        real_SDL_RenderPresent(renderer);
        return;
    }
    /* the game's drawing state on the canvas: SDL resets it on every
     * change of target */
    float sx = 1, sy = 1;
    PbioRect vp, clip;
    int clipped = SDL_RenderIsClipEnabled_p(renderer);
    unsigned char cr, cg, cb, ca;
    SDL_RenderGetScale_p(renderer, &sx, &sy);
    SDL_RenderGetViewport_p(renderer, &vp);
    SDL_RenderGetClipRect_p(renderer, &clip);
    SDL_GetRenderDrawColor_p(renderer, &cr, &cg, &cb, &ca);

    /* the window: black, and the canvas scaled to fit it */
    int ww = 0, wh = 0, gw = wn->game_w, gh = wn->game_h;
    SDL_SetRenderTarget_p(renderer, NULL);
    SDL_GetRendererOutputSize_p(renderer, &ww, &wh);
    SDL_SetRenderDrawColor_p(renderer, 0, 0, 0, 255);
    SDL_RenderClear_p(renderer);
    if (ww > 0 && wh > 0) {
        PbioRect dst;
        if ((long)ww * gh <= (long)wh * gw) {
            dst.w = ww;
            dst.h = (int)((long)gh * ww / gw);
        } else {
            dst.h = wh;
            dst.w = (int)((long)gw * wh / gh);
        }
        dst.x = (ww - dst.w) / 2;
        dst.y = (wh - dst.h) / 2;
        SDL_RenderCopy_p(renderer, wn->canvas, NULL, &dst);
    }
    real_SDL_RenderPresent(renderer);

    /* back to the canvas, as the game left it */
    SDL_SetRenderTarget_p(renderer, wn->canvas);
    SDL_RenderSetScale_p(renderer, sx, sy);
    SDL_RenderSetViewport_p(renderer, &vp);
    SDL_RenderSetClipRect_p(renderer, clipped ? &clip : NULL);
    SDL_SetRenderDrawColor_p(renderer, cr, cg, cb, ca);
}
