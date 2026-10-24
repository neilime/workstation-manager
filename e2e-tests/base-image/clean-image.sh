#!/usr/bin/env bash
# This runs only against a new, offline cloud-image copy, never a test VM.
set -euo pipefail

apt-get clean
cloud-init clean --logs --machine-id
rm -f /etc/ssh/ssh_host_* /var/lib/dbus/machine-id
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
# Package installation may have generated logs, but no user or credentials exist.
find /var/log -type f -exec truncate --size=0 {} +
