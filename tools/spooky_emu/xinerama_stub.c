/*
 * xinerama_stub.c - a libXinerama.so.1 that says "no Xinerama".
 *
 * Looney Tunes' Godot 4.1 loads libXinerama at start and gives up on X
 * ("Can't load Xinerama dynamically", then "all display drivers failed")
 * when it cannot; PAD-Runtime's Ubuntu does not carry it.  Godot only asks
 * it where the monitors are, and falls back to XRandR when Xinerama is not
 * active - which is what these four answer.  run_game.sh puts this on the
 * game's LD_LIBRARY_PATH only when the distro has no libXinerama.so.1.
 * build.sh builds it beside spkshim.so.
 */
typedef struct _XDisplay Display;
typedef int Bool;
typedef struct {
    int screen_number;
    short x_org, y_org, width, height;
} XineramaScreenInfo;

Bool XineramaQueryExtension(Display *d, int *event_base, int *error_base) {
    (void)d;
    if (event_base) *event_base = 0;
    if (error_base) *error_base = 0;
    return 0;
}

/* Godot refuses the library ("Unsupported Xinerama library version")
 * unless this succeeds with 1.1 or later. */
int XineramaQueryVersion(Display *d, int *major, int *minor) {
    (void)d;
    if (major) *major = 1;
    if (minor) *minor = 1;
    return 1;
}

Bool XineramaIsActive(Display *d) {
    (void)d;
    return 0;
}

XineramaScreenInfo *XineramaQueryScreens(Display *d, int *number) {
    (void)d;
    if (number) *number = 0;
    return 0;
}
