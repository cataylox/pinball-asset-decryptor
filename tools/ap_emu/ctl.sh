#!/bin/bash
# ctl.sh <command...> | --stream - apctl.py for callers that can only run
# bash scripts (the app's rig_cmd, the switch window's pipe).
exec python3 "$(dirname "$0")/apctl.py" --slot "${PAD_SLOT:-0}" "$@"
