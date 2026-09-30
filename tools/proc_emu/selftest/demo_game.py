"""demo_game.py <machine.yaml> - the smallest pyprocgame title: boot, go to
attract, count the balls in the trough the way a game does (through its own
switch objects, NC optos and all), and start on the start button.

It uses the real framework path every AP / Spooky / Dutch Pinball title
does: GameController, load_config (PDBConfig programming the board), the
switch rules, enable_flippers (hardware rules), the run loop.  Prints
`DEMO ...` lines run.sh looks for.
"""
from __future__ import print_function

import logging
import sys

import yaml

import procgame.game

# pyprocgame predates PyYAML 5's Loader argument (6 requires it).
_yaml_load = yaml.load
yaml.load = lambda stream, Loader=yaml.SafeLoader: _yaml_load(stream, Loader=Loader)


def say(text):
    print("DEMO " + text)
    sys.stdout.flush()


class Attract(procgame.game.Mode):
    def mode_started(self):
        trough = sorted(s.name for s in self.game.switches if s.name.startswith("trough")
                        and s.is_active())
        say("attract balls=%d %s coinDoor_active=%s" % (
            len(trough), ",".join(trough), self.game.switches.coinDoor.is_active()))

    def sw_startButton_active(self, sw):
        say("start pressed")
        self.game.coils.trough.pulse()
        return procgame.game.SwitchStop

    def sw_flipperLwL_active(self, sw):
        say("flipper")


class Demo(procgame.game.GameController):
    def __init__(self, yaml_path):
        super(Demo, self).__init__("pdb")
        self.load_config(yaml_path)
        self.enable_flippers(True)
        self.modes.add(Attract(self, 1))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    game = Demo(sys.argv[1])
    game.run_loop()
