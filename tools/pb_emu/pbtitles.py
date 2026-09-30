#!/usr/bin/env python3
"""pbtitles.py - what each Pinball Brothers FAST title needs around it.

Switch and driver numbers are the game's own (pinprog's names_of_switches /
names_of_drives, read with gdb from its debug info); the FAST boards are the
ones fast.c lists at start-up ("FAST: adding board ...").

  python3 pbtitles.py get <key> <field>    one field (for shell scripts)
  python3 pbtitles.py switches <key>       the named switches, JSON
"""
import json
import sys

TITLES = {
    "predator": {
        "title": "Predator",
        "maker": "Pinball Brothers",
        # the update's /opt/game: both programs and their media
        "programs": ["pinprog", "vidprog"],
        "neuron_fw": "02.26",
        # NN: replies, node order: (name, drivers, switches)
        "nodes": [("FP-I/O-0024", 8, 24), ("FP-I/O-3208", 8, 32),
                  ("FP-I/O-1616", 16, 16), ("FP-I/O-3208", 8, 32)],
        # expansion bus: address -> board (Neuron's own LEDs at 48)
        "exp_boards": {"48": "FP-CPU-2000", "B4": "FP-EXP-0071",
                       "D0": "FP-EXP-0051", "30": "FP-EXP-1313"},
        "trough_switches": [24, 25, 26, 27, 28, 29],
        "shooter_switch": 31,
        "trough_eject_driver": 0x11,        # TROUGH RELEASE
        "launch_drivers": [0x10],           # AUTO LAUNCH
        # bank reset driver -> the drop targets it stands back up
        "drop_resets": {"23": [45, 46, 47],     # LEFT BANK RESET
                        "24": [65],             # SINGLE DROP RESET
                        "28": [61, 62, 63]},    # TOP BANK RESET
        "active_at_boot": [4],               # INTERLOCK: coin door closed
        # mach_opto_mask: trough + jam, scoop, locks, drops, toy sensors...
        "optos": [24, 25, 26, 27, 28, 29, 30, 41, 42, 48, 49, 52, 53, 65, 66,
                  73, 80, 81, 83, 84, 85, 86, 87, 88, 89, 90, 91, 96, 97, 98],
        # what the rig's run_game.sh waits for in raven.log
        "attract": r"deff_start 01 AMODE",
        "switches": {
            "0": "ESCAPE", "1": "DOWN", "2": "UP", "3": "ENTER",
            "4": "INTERLOCK", "5": "COIN 2", "6": "COIN 3", "7": "COIN 4",
            "8": "LEFT BUTTON", "9": "UPPER LEFT BUTTON",
            "10": "START BUTTON", "11": "TILT", "14": "LOCK DOWN BAR",
            "16": "RIGHT BUTTON", "17": "UPPER RIGHT BUTTON",
            "18": "LAUNCH BUTTON", "19": "COIN BOX ALARM",
            "24": "TROUGH 1", "25": "TROUGH 2", "26": "TROUGH 3",
            "27": "TROUGH 4", "28": "TROUGH 5", "29": "TROUGH 6",
            "30": "TROUGH JAM", "31": "SHOOTER", "32": "LEFT INLANE",
            "33": "LEFT OUTLANE", "34": "MINIGUN LANE", "35": "LEFT SLING",
            "36": "LEFT EOS", "38": "VILLAGE TARGET 1",
            "39": "VILLAGE TARGET 2", "40": "LOWER RIGHT STANDUP",
            "41": "REVERSO RAMP LEFT", "42": "SCOOP",
            "43": "LEFT POP BUMPER", "44": "RIGHT POP BUMPER",
            "45": "LEFT BANK 3", "46": "LEFT BANK 2", "47": "LEFT BANK 1",
            "48": "MINIGUN LOCK 3", "49": "MINIGUN LOCK 2",
            "50": "RIGHT OUTLANE", "51": "RIGHT INLANE",
            "52": "MINIGUN LOCK 1", "53": "MINIGUN LOADER", "54": "RIGHT EOS",
            "55": "RIGHT SLING", "56": "RAVEN 3", "57": "RAVEN 2",
            "58": "RAVEN 1", "59": "LEFT CRYPT SPINNER",
            "60": "UPPER STANDUP 1", "61": "TOP BANK 3", "62": "TOP BANK 2",
            "63": "TOP BANK 1", "64": "UNDER RAMP DETECT",
            "65": "SINGLE DROP TARGET", "66": "REVERSO RAMP RIGHT",
            "67": "UPPER RIGHT EOS", "68": "RIGHT ORBIT MADE",
            "69": "UNDER RAMP ENTRY", "70": "RIGHT ORBIT TOP",
            "71": "RIGHT ORBIT BOTTOM", "73": "SUBWAY",
            "74": "LEFT ORBIT SPINNER", "75": "RAMP DIVERTOR EOS",
            "79": "LEFT ORBIT MADE", "80": "TOY IN PROGRESS",
            "81": "TOY ERROR", "83": "TOY DOWN", "84": "TOY LEFT",
            "85": "TOY RIGHT", "86": "TOY CENTER", "87": "TOY UP",
            "88": "LEFT RAMP ENTRY", "89": "LEFT RAMP MADE",
            "90": "RIGHT RAMP EXIT LOCK 1", "91": "RIGHT RAMP EXIT LOCK 2",
            "92": "RIGHT CRYPT SPINNER", "96": "RIGHT RAMP FIRST EXIT",
            "97": "RIGHT RAMP ENTRY", "98": "RIGHT RAMP IN TRANSIT",
        },
    },
}


def main(argv):
    if len(argv) >= 3 and argv[0] == "get":
        v = TITLES.get(argv[1], {}).get(argv[2], "")
        print(v if isinstance(v, str) else json.dumps(v))
        return 0
    if len(argv) >= 2 and argv[0] == "switches":
        print(json.dumps(TITLES[argv[1]]["switches"]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
