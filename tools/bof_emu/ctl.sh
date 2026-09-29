#!/bin/bash
# ctl.sh <command...> | --stream - bofctl.py for callers that can only run bash
# scripts (the app's rig_cmd).
exec python3 "$(dirname "$0")/bofctl.py" --slot "${PAD_SLOT:-0}" "$@"
