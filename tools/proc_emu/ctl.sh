#!/bin/bash
# ctl.sh <command...> | --stream - procctl.py for callers that can only run
# bash scripts.
exec python3 "$(dirname "$0")/procctl.py" --slot "${PAD_SLOT:-0}" "$@"
