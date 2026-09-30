#!/bin/bash
# ctl.sh <request...> | --stream - pbioctl.py for callers that can only run
# bash scripts (the app's rig_cmd, a switch window's pipe).
exec python3 "$(dirname "$0")/pbioctl.py" --slot "${PAD_SLOT:-0}" "$@"
