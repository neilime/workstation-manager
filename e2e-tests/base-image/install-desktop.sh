#!/usr/bin/env bash
# Shared by fresh Lima provisioning and the offline, unauthenticated image builder.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
# Desktop packages install a NetworkManager default. Preserve Lima's networkd
# renderer before installation and before the prepared image's first boot.
install -d -m 0755 /etc/netplan
cat >/etc/netplan/99-lima-networkd.yaml <<'EOF'
network:
  version: 2
  renderer: networkd
EOF
chmod 0600 /etc/netplan/99-lima-networkd.yaml

packages=(dconf-cli flatpak gdm3 gnome-keyring libpam-gnome-keyring ptyxis ubuntu-desktop-minimal)
recipe_digest="$(sha256sum "$0" | cut -d ' ' -f 1)"
marker=/var/lib/workstation-manager-e2e-base
if [[ -f "$marker" && "$(cat "$marker")" == "$recipe_digest" ]]; then
	for package in "${packages[@]}"; do
		[[ "$(dpkg-query -W -f='${db:Status-Status}' "$package")" == installed ]]
	done
	exit 0
fi

printf '%s\n' \
	'gdm3 shared/default-x-display-manager select gdm3' \
	'gdm3 gdm3/daemon_name string /usr/sbin/gdm3' |
	debconf-set-selections
# Bound stalled archive connections without weakening package verification.
sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources
apt_options=(-o Acquire::Retries=3 -o Acquire::https::Timeout=30)
apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update
apt-get "${apt_options[@]}" install -y --no-install-recommends "${packages[@]}"
printf '%s\n' "$recipe_digest" >"$marker"
