/* probe.c - a native libpinproc client, the shape of Dutch Pinball's AAIW
 * (C++ with libpinproc linked in, no fake mode): open the board, read the
 * switches, set rules, take a switch event, pulse a coil.  Prints one
 * "probe.c: ..." line per step and exits 0 only if every step held.
 * Built and run by run.sh against the real libpinproc + fakeftdi. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "pinproc.h"

static int fails;
#define CHECK(cond, ...) do { printf("probe.c: %s ", (cond) ? "ok  " : "FAIL"); \
    printf(__VA_ARGS__); printf("\n"); fflush(stdout); if (!(cond)) fails++; } while (0)

int main(int argc, char **argv)
{
    const char *ctl = argc > 1 ? argv[1] : "true";
    char cmd[512];
    PRHandle h = PRCreate(kPRMachinePDB);
    CHECK(h != kPRHandleInvalid, "PRCreate(PDB): %s", h ? "board found" : PRGetLastErrorText());
    if (h == kPRHandleInvalid)
        return 1;
    PRReset(h, kPRResetFlagUpdateDevice);

    PREventType st[256];
    CHECK(PRSwitchGetStates(h, st, 256) == kPRSuccess, "PRSwitchGetStates");
    int closed = 0;
    for (int i = 0; i < 256; i++)
        closed += st[i] == kPREventTypeSwitchClosedDebounced;
    CHECK(st[72] == kPREventTypeSwitchOpenDebounced && st[74] == kPREventTypeSwitchOpenDebounced &&
          st[75] == kPREventTypeSwitchClosedDebounced && st[9] == kPREventTypeSwitchClosedDebounced,
          "trough optos 72-74 open (3 balls), 75 closed (empty), coin door closed; %d closed", closed);

    PRSwitchConfig sc;
    memset(&sc, 0, sizeof sc);
    sc.hostEventsEnable = 1;
    sc.directMatrixScanLoopTime = 2;
    sc.pulsesBeforeCheckingRX = 10;
    sc.inactivePulsesAfterBurst = 12;
    sc.pulsesPerBurst = 6;
    sc.pulseHalfPeriodTime = 13;
    PRSwitchUpdateConfig(h, &sc);
    PRSwitchRule rule = {0, 1};             /* reloadActive, notifyHost */
    PRSwitchUpdateRule(h, 8, kPREventTypeSwitchClosedDebounced, &rule, NULL, 0, 0);
    PRDriverState coil;
    memset(&coil, 0, sizeof coil);
    coil.driverNum = 2;
    coil.polarity = 1;
    PRDriverStatePulse(&coil, 15);
    PRSwitchRule quiet = {0, 0};
    PRSwitchUpdateRule(h, 66, kPREventTypeSwitchClosedNondebounced, &quiet, &coil, 1, 0);
    PRFlushWriteData(h);

    snprintf(cmd, sizeof cmd, "%s sw startButton 1 >/dev/null && %s tap leftSling 50 >/dev/null", ctl, ctl);
    CHECK(system(cmd) == 0, "ctl: start button pressed, sling tapped");
    PREvent ev[16];
    int got = 0, seen8 = 0;
    for (int t = 0; t < 200 && !seen8; t++) {
        int n = PRGetEvents(h, ev, 16);
        for (int i = 0; i < n; i++)
            if (ev[i].type == kPREventTypeSwitchClosedDebounced && ev[i].value == 8)
                seen8 = 1;
        got += n > 0 ? n : 0;
        usleep(10000);
    }
    CHECK(seen8, "PRGetEvents: switch 8 closed-debounced arrived (%d events)", got);

    /* A PDB board's driver slots are blank (driverNum 0) until written, as
     * pyprocgame's pdb.py does for every driver at start. */
    PRDriverState d1;
    memset(&d1, 0, sizeof d1);
    d1.driverNum = 1;
    d1.polarity = 1;
    PRDriverUpdateState(h, &d1);
    CHECK(PRDriverPulse(h, 1, 40) == kPRSuccess, "PRDriverPulse(1, 40ms)");
    PRLED led = {0, 5};
    PRLEDColor(h, &led, 255);
    PRDriverWatchdogTickle(h);
    PRFlushWriteData(h);
    usleep(50000);
    snprintf(cmd, sizeof cmd, "%s log 10 | grep -q '\"driver\": 2, \"action\": \"pulse 15ms\", \"by\": \"rule sw66 closed\"'"
             " && %s log 10 | grep -q '\"driver\": 1, \"action\": \"pulse 40ms\", \"by\": \"host\"'"
             " && %s leds | grep -q '\"0:5\": 255'", ctl, ctl, ctl);
    CHECK(system(cmd) == 0, "board saw: sling rule fired coil 2, host pulsed coil 1, LED 0:5 = 255");
    PRDelete(h);
    printf("probe.c: %s\n", fails ? "FAILED" : "all ok");
    return fails ? 1 : 0;
}
