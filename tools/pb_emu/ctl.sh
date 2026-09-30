#!/bin/bash
# ctl.sh <request...> | --stream - pbctl.py for callers that can only run
# bash scripts (the app's rig_cmd, the switch window's pipe).
exec python3 "$(dirname "$0")/pbctl.py" --slot "${PAD_SLOT:-0}" "$@"
