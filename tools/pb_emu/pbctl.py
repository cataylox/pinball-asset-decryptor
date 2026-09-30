#!/usr/bin/env python3
"""pbctl.py [--slot N] <request...> | --stream - talk to a running Predator
rig's board (pbfast.py's control socket), as tools/spooky_emu/spkctl.py does
for a Spooky rig.

Requests: pbfast.py's (sw, tap, rip, plunge, drain, reset, pause, state,
leds).  Every reply is ONE JSON line: the board's own JSON as it is, and its
plain `ok` / `err <why>` as {"ok": true} / {"err": "<why>"} - the virtual
playfield (tools/ap_emu/appf.py via pbpf.py) reads JSON only.  Exit 1 when
the rig is not running or the request was refused.

--stream keeps ONE connection and forwards stdin line by line, printing each
reply - the switch window uses it, because starting wsl.exe per click costs
a few hundred milliseconds and a flipper cannot wait that long.
"""
import json
import os
import socket
import sys


def connect(slot):
    root = os.environ.get("PB_ROOT", "/var/tmp/pad_pb")
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(os.path.join(root, "rig%s" % slot, "ctl.sock"))
    return s


def as_json(reply):
    """The board's reply as one JSON line."""
    reply = reply.strip()
    if reply.startswith("{"):
        return reply
    if reply == "ok":
        return json.dumps({"ok": True})
    return json.dumps({"err": reply[4:] if reply.startswith("err ") else reply})


def ask(s, line):
    s.sendall((line.strip() + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk:
            raise OSError("rig closed the connection")
        buf += chunk
    return as_json(buf.decode())


def main(argv):
    slot = os.environ.get("PAD_SLOT", "0")
    if argv[:1] == ["--slot"]:
        slot, argv = argv[1], argv[2:]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        s = connect(slot)
        if argv == ["--stream"]:
            for line in sys.stdin:
                if line.strip():
                    print(ask(s, line), flush=True)
            return 0
        reply = ask(s, " ".join(argv))
    except OSError as e:
        print("pbctl: rig %s not running (%s)" % (slot, e), file=sys.stderr)
        return 1
    print(reply)
    return 1 if reply.startswith('{"err"') else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
