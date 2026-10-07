#!/bin/sh
set -eu

systemctl --user daemon-reload
exec systemctl --user start workstation-manager-bleachbit-clean.timer
