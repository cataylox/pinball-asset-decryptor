#!/bin/bash
# ctl.sh <command...> | --stream - dpctl.py for callers that can only run
# bash scripts (the app's rig_cmd, the switch window's pipe).
exec python3 "$(dirname "$0")/dpctl.py" --slot "${PAD_SLOT:-0}" "$@"
