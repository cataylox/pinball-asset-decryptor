/* apquit.c - LD_PRELOADed into AP's apiav (Hot Wheels, Galactic Tank Force):
 * closing one of its windows ends it, and a key pressed in one reaches the
 * game.
 *
 * apiav draws the A/V titles' screens in SDL windows ("Screen_main",
 * "Screen_playfield_sim") and ignores SDL's close events, so their X did
 * nothing (PAD-292: David wants the X to close every emulator window).  Its
 * one event call is SDL_PollEvent; this wraps it, and on SDL_QUIT or a
 * window's SDL_WINDOWEVENT_CLOSE the process exits.  run_game.sh's ns.sh
 * then stops the game with it, and the app closes the switch window.
 *
 * Keys (David: "i should be able to use the keyboard shortcuts in the
 * display window when it's focused"): every key going down or up is written
 * to the game's input FIFO ($AP_FIFO) as `!key <SDL keycode> 1|0`; py/aprun.py
 * maps it through the same keymap as the virtual playfield.  apiav still
 * sees the key.
 *
 * Built inside WSL on first use (run_game.sh):
 *   gcc -shared -fPIC -O2 -I$AP_AV/include -o $AP_ROOT/apquit.so apquit.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <SDL2/SDL_events.h>

static void forward_key(const SDL_KeyboardEvent *k)
{
    const char *fifo = getenv("AP_FIFO");
    char line[48];
    int fd, n;

    if (!fifo || k->repeat)
        return;
    /* non-blocking: with nobody reading, a plain open would wait forever */
    fd = open(fifo, O_WRONLY | O_NONBLOCK);
    if (fd < 0)
        return;
    n = snprintf(line, sizeof line, "!key %d %d\n", (int)k->keysym.sym,
                 k->type == SDL_KEYDOWN ? 1 : 0);
    if (write(fd, line, (size_t)n) < 0) {
        /* the game is not reading: the key is lost, as on a frozen machine */
    }
    close(fd);
}

int SDL_PollEvent(SDL_Event *event)
{
    static int (*real)(SDL_Event *) = NULL;
    int got;

    if (!real)
        real = (int (*)(SDL_Event *))dlsym(RTLD_NEXT, "SDL_PollEvent");
    got = real(event);
    if (!got || !event)
        return got;
    if (event->type == SDL_QUIT ||
        (event->type == SDL_WINDOWEVENT &&
         event->window.event == SDL_WINDOWEVENT_CLOSE)) {
        fprintf(stderr, "apquit: a window was closed - apiav quits\n");
        fflush(stderr);
        _exit(0);
    }
    if (event->type == SDL_KEYDOWN || event->type == SDL_KEYUP)
        forward_key(&event->key);
    return got;
}
