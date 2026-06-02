#!/usr/bin/env sh

set -eu

ssh_executable="$(command -v ssh)"

# Keep E2E commands independent from Lima's shared SSH master and detect a
# maintenance-related transport interruption promptly so callers can reconnect.
exec "$ssh_executable" \
	-o ControlMaster=no \
	-o ControlPath=none \
	-o ControlPersist=no \
	-o ConnectTimeout=10 \
	-o ConnectionAttempts=1 \
	-o ServerAliveInterval=15 \
	-o ServerAliveCountMax=4 \
	"$@"
