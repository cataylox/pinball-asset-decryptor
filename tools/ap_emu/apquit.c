/* apquit.c - LD_PRELOADed into AP's apiav (Hot Wheels, Galactic Tank Force):
 * closing one of its windows ends it.
 *
 * apiav draws the A/V titles' screens in SDL windows ("Screen_main",
 * "Screen_playfield_sim") and ignores SDL's close events, so their X did
 * nothing (PAD-292: David wants the X to close every emulator window).  Its
 * one event call is SDL_PollEvent; this wraps it, and on SDL_QUIT or a
 * window's SDL_WINDOWEVENT_CLOSE the process exits.  run_game.sh's ns.sh
 * then stops the game with it, and the app closes the switch window.
 *
 * Built inside WSL on first use (run_game.sh):
 *   gcc -shared -fPIC -O2 -I$AP_AV/include -o $AP_ROOT/apquit.so apquit.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>
#include <SDL2/SDL_events.h>

int SDL_PollEvent(SDL_Event *event)
{
    static int (*real)(SDL_Event *) = NULL;
    int got;

    if (!real)
        real = (int (*)(SDL_Event *))dlsym(RTLD_NEXT, "SDL_PollEvent");
    got = real(event);
    if (got && event && (event->type == SDL_QUIT ||
                         (event->type == SDL_WINDOWEVENT &&
                          event->window.event == SDL_WINDOWEVENT_CLOSE))) {
        fprintf(stderr, "apquit: a window was closed - apiav quits\n");
        fflush(stderr);
        _exit(0);
    }
    return got;
}
