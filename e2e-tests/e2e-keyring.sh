#!/usr/bin/env bash

set -euo pipefail

case "$(hostname)" in
lima-*) ;;
*)
	printf '%s\n' "Run this keyring fixture inside the Lima VM." >&2
	exit 1
	;;
esac

umask 077
XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
keyring_password="$XDG_RUNTIME_DIR/workstation-manager-e2e-keyring-password"

case "${1:-}" in
prepare)
	# Autologin supplies no PAM password. Keep a random fixture password in
	# private runtime storage so desktop restarts can unlock the same keyring.
	if [[ ! -f "$keyring_password" ]]; then
		head -c 32 /dev/urandom | base64 -w 0 >"$keyring_password"
	fi
	keyring_unit="$HOME/.config/systemd/user/gnome-keyring-daemon.service.d"
	mkdir -p "$keyring_unit"
	cat >"$keyring_unit/workstation-manager-e2e.conf" <<'UNIT'
[Service]
StandardInput=file:%t/workstation-manager-e2e-keyring-password
ExecStart=
ExecStart=/usr/bin/gnome-keyring-daemon --foreground --components=pkcs11,secrets --control-directory=%t/keyring --unlock
UNIT
	systemctl --user daemon-reload
	;&
unlock)
	# Supply the password to the actual Secret Service process. A separate
	# --unlock invocation starts another daemon and cannot unlock this one.
	systemctl --user restart gnome-keyring-daemon.service
	;;
check) ;;
*)
	printf '%s\n' "Usage: e2e-keyring.sh prepare|unlock|check" >&2
	exit 2
	;;
esac

[[ -f "$keyring_password" ]] || exit 1
for _attempt in $(seq 1 10); do
	# Readiness probes run during provisioning and must not activate a second,
	# uninitialized Secret Service before the configured daemon owns its bus name.
	if locked="$(busctl --user --auto-start=no --timeout=1 call \
		org.freedesktop.secrets /org/freedesktop/secrets/aliases/default \
		org.freedesktop.DBus.Properties Get ss \
		org.freedesktop.Secret.Collection Locked 2>/dev/null)" && [[ "$locked" == 'v b false' ]]; then
		exit 0
	fi
	[[ "$1" != check ]] || exit 1
	sleep 0.2
done

printf '%s\n' "The fixture keyring stayed locked or unavailable; check gnome-keyring-daemon.service." >&2
exit 1
