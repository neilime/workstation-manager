#!/usr/bin/env bash
# This runs only against a new, offline cloud-image copy, never a test VM.
set -euo pipefail

apt-get clean
cloud-init clean --logs
rm -f /etc/ssh/ssh_host_* /etc/machine-id /var/lib/dbus/machine-id
# The offline chroot has no running systemd for cloud-init to detect.
# Keep a regular first-boot marker so systemd can persist the fresh identity.
printf 'uninitialized\n' >/etc/machine-id
chmod 0444 /etc/machine-id
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
# Package installation may have generated logs, but no user or credentials exist.
find /var/log -type f -exec truncate --size=0 {} +
