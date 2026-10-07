#!/bin/sh
set -eu

exec python3 "$HOME/.local/share/workstation-manager/bleachbit-clean.py" "$@"
