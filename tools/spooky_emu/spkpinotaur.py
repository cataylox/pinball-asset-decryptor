#!/usr/bin/env python3
"""spkpinotaur.py - the rig's Pinotaur: the playfield board of Spooky's
Halloween and Ultraman, on the same pty, control socket and logs as the
Warden (spkwarden.py starts it for a title whose profile says
"board": "pinotaur").

The game opens /dev/pinheck (the machine's udev name for USB cafe:4001;
spkshim.so maps it onto the rig's pty) with Mono's SerialPort, 1 ms read
timeout.  The wire protocol, from Halloween v1.18.1's Pinotar.cs:

  host -> board   0x3C ('<') <opcode> <0x81 + 2 * n> <n argument bytes>
                  - the third byte says how many arguments follow, so every
                  message frames itself (writeHalfPage's 32 data bytes are
                  its arguments, sent in a second write)
  board -> host   0x3E ('>') <opcode> <payload>, a fixed size per opcode:
                  0x00 system name, 9 bytes - the game plays only when it
                       contains "Pinotaur" (machineMode.IsGameInReadyState)
                  0x01 firmware, 5 bytes; 0x02 API, 5 bytes
                  0x58 <sw> <0|1>   reply to get_switch_state; a reply for
                       switch 95 is the board's "machine ready" (the game
                       asks for every switch twice at boot: those two and
                       its own loading make the three it waits for)
                  0x59 <0x80 | sw>  a switch went active; <sw> inactive;
                       0x7F = nothing changed (the game polls once at boot,
                       then sets report type 1 and the board pushes these)
                  0x28 <32 bytes>   reply to read_row - the row at 8064
                       says which game the board is set up for (0 0 =
                       Halloween, 0 1 = Ultraman); any reply lets the
                       game go on
                  0x6F <coil> <hi> <lo>   boot fault check: FF FF FF = none
                  0x20 <5 bytes> bank info, 0x0F <coil> <mA> last coil
                       current, 0x25 row erased, 0x2B page written

The game reads ONE message per frame, so replies queue in the pty until it
gets to them; each is written whole (the 1 ms timeout would split one that
arrives in pieces).  It reports RAW switch states: the game inverts its
reversed optos itself (SwitchConfig isReversed).

Everything else is kept, as the Warden does: coils (pulse 23, patter 18, hold time 17,
disable 22, 48 V 96, flippers 97), flipper buttons (30) with their
end-of-stroke switches (94), auto-actions (91: slings), GI strings (11/12),
the start and launch lamps (106/108), servos (123) and LEDs (48 colour, 49
blink, 50 pulse, 51 chase, 55 fade - 24-bit, one or `n` at a time - and
the light shows' frames, 62: 20 LEDs from <first>, each 0xRRGGBB low byte
first, drawn over the rest until 63 0 turns the shows off).  Its
first "coils enabled" (96 1) is attract starting: machine_state_3 turns
them on, the only time before a game.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spkwarden  # noqa: E402

TX, RX = 0x3C, 0x3E
LEN0 = 0x81                         # the length byte of a message with no args
SYSTEM_NAME = b"Pinotaur\0"         # 9 bytes
FIRMWARE = b"PAD 1"                 # 5 bytes each
API = b"PAD 1"
NO_CHANGE = 0x7F
#: read_row's game-name row; a board holds 0 0 there for Halloween, 0 1
#: for Ultraman (firmware.cs GameSetting) - the profile's "game_row".
GAME_ROW = 8064
#: Colour messages: opcode -> (first, r, g, b, count) positions in the args.
LED_OPS = {48: (0, 1, 2, 3, 4), 49: (0, 1, 2, 3, 5), 50: (0, 1, 2, 3, 5),
           51: (0, 1, 2, 3, 4), 55: (0, 1, 2, 3, None)}
LED_MODE = {48: "solid", 49: "blink", 50: "breathe", 51: "chase",
            55: "crossfade"}


class Pinotaur(spkwarden.Board):
    def __init__(self, rig, pty=True, title=None):
        super().__init__(rig, pty, title)
        self.flip_coils = {}        # button -> its coils (op 30)
        self.eos_of = {}            # high coil -> its end-of-stroke switch
        self.gi = {}                # string -> 0|1
        self.halves = 0             # writeHalfPage halves since a page
        self.power["flippers"] = 0
        self.ops = {}               # opcode -> messages seen

    def switch_msg(self, sw, on):
        return [RX, 0x59, (0x80 if on else 0) | sw]

    # -- host -> board --------------------------------------------------
    def host_bytes(self, buf):
        buf = self.pend + bytes(buf)
        i, n = 0, len(buf)
        while i < n:
            if buf[i] != TX:
                j = buf.find(bytes([TX]), i)
                j = j if j >= 0 else n
                self.say("skipped %d byte(s) outside a message" % (j - i))
                i = j
                continue
            if i + 2 >= n:
                break
            op, ln = buf[i + 1], buf[i + 2]
            if ln < LEN0 or not ln & 1:
                self.unknown[op] = self.unknown.get(op, 0) + 1
                self.say("bad length byte", ln, "for opcode", op)
                j = buf.find(bytes([TX]), i + 1)
                i = j if j >= 0 else n
                continue
            end = i + 3 + (ln - LEN0) // 2
            if end > n:
                break
            try:
                self.message(op, list(buf[i + 3:end]))
            except Exception as e:       # never let one message stop the board
                self.say("message", op, "failed:", e)
            i = end
        self.pend = buf[i:]
        return self.pend

    def reply(self, op, payload=()):
        self.send([RX, op] + list(payload))

    def message(self, op, a):
        self.ops[op] = self.ops.get(op, 0) + 1
        if op in LED_OPS:                     # most of the stream: first
            self.led(op, a)
        elif op == 62:                  # a light show frame: 20 LEDs
            for k in range(20):
                v = a[1 + 3 * k:4 + 3 * k]
                if len(v) == 3 and any(v):
                    self.overlay[a[0] + k] = (v[2], v[1], v[0])
                    self.led_mode[a[0] + k] = "show"
                else:
                    self.overlay.pop(a[0] + k, None)
        elif op == 63:                  # light shows on (a mask) / off
            if not a[0]:
                self.overlay.clear()
        elif op == 88:                                  # get_switch_state
            with self.lock:
                self.reply(88, [a[0], self.state.get(a[0], 0)])
        elif op == 89:
            self.reply(89, [NO_CHANGE])
        elif op == 0:
            self.reply(0, SYSTEM_NAME)
        elif op == 1:
            self.reply(1, FIRMWARE)
        elif op == 2:
            self.reply(2, API)
        elif op == 111:                                 # boot fault check
            self.reply(111, [255, 255, 255])
        elif op == 40:                                  # read_row
            addr = spkwarden.u32(a[:4])
            row = (bytes(self.title.get("game_row", [0, 0]))
                   if addr == GAME_ROW else b"")
            self.reply(40, row + b"\xff" * (32 - len(row)))
        elif op == 37:
            self.reply(37)
        elif op == 43:                  # a page is two halves
            self.halves += 1
            if self.halves % 2 == 0:
                self.reply(43)
        elif op == 32:
            self.reply(32, [0] * 5)
        elif op == 26:
            self.reply(15, [a[0], 0, 0])
        elif op == 23:                                  # pulse <coil> <ms>
            self.fire(a[0], "pulse" + (" %d ms" % a[1] if a[1] else ""))
        elif op == 18:                  # patter <on> <off>: held on
            if not a[1]:
                self.hold(a[0], False)
            elif a[0] not in self.coil_held:
                self.fire(a[0], "patter")
                self.hold(a[0], True)
        elif op == 22:
            self.hold(a[0], False)
        elif op in (17, 24, 19, 28, 93):   # hold / pulse time, hold pwm,
            #                                  current, flipper type
            self.coil_config.setdefault(a[0], [0, 0, 0, 0])
        elif op == 96:
            self.set_power("48v", a[0], "coils enabled", "coils disabled")
        elif op == 97:
            self.set_power("flippers", a[0], "flippers enabled",
                           "flippers disabled")
        elif op == 30:
            coils = [c for c in a[1:5] if c != 255]
            if coils:
                self.flip_coils[a[0]] = coils
            else:
                self.flip_coils.pop(a[0], None)
            self.rebuild_flippers()
        elif op == 94:
            self.eos_of[a[1]] = a[0]
            self.rebuild_flippers()
        elif op == 91:
            self.autoactions[a[0]] = (a[1], a[2] << 8 | a[3])
        elif op == 92:
            self.autoactions.pop(a[0], None)
        elif op in (11, 12):
            self.gi[a[0]] = int(op == 11)
        elif op in (106, 108):
            self.lamps["start" if op == 106 else "launch"] = a[0]
        elif op == 123:
            self.servos[a[0]] = a[1]
        elif op == 60:
            self.chain = [a[0], 0]
        elif op == 58:
            self.chain = [a[0] + 1, max(0, a[1] - a[0])]
        # else: ramp / debounce / clear switch, report type, servo and
        # motor limits, watchdog, light show frames: nothing to answer.

    def set_power(self, what, on, said_on, said_off):
        on = 1 if on else 0
        if self.power.get(what) != on:
            self.say(said_on if on else said_off)
        self.power[what] = on

    def rebuild_flippers(self):
        """spkwarden's flipper table: button -> (high coil, low, eos)."""
        self.flippers = {
            b: (c[0], c[1] if len(c) > 1 else 255, self.eos_of.get(c[0], 255))
            for b, c in self.flip_coils.items()}

    def led(self, op, a):
        first, r, g, b, count = LED_OPS[op]
        if len(a) <= b:
            return
        n = a[count] if count is not None and len(a) > count else 1
        col = (a[r], a[g], a[b])
        for i in range(a[first], a[first] + max(1, n)):
            if any(col):
                self.leds[i] = col
                self.led_mode[i] = LED_MODE[op]
            else:
                self.leds.pop(i, None)

    def command(self, line):
        """The Warden's requests; `state` adds the GI strings."""
        out = super().command(line)
        if line.split()[:1] == ["state"]:
            s = json.loads(out)
            s["gi"] = spkwarden._keyed(self.gi)
            s["board"] = "pinotaur"
            s["opcodes"] = spkwarden._keyed(self.ops)
            out = json.dumps(s)
        return out


if __name__ == "__main__":
    sys.argv[1:2] or sys.exit(__doc__)
    os.environ.setdefault("SPK_TITLE", "h78")
    spkwarden.main()
