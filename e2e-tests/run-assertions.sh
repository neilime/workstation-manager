#!/usr/bin/env bash

set -euo pipefail

umask 077
ssh_config_path="$1"
shift
assertion_config="$(mktemp /tmp/workstation-manager-e2e-ssh.XXXXXX)"
trap 'rm -f "$assertion_config"' EXIT

# Each phase gets its own container and fresh login, including updated groups.
# Keep reusable connections in that container; Lima's state is read-only.
cat >"$assertion_config" <<EOF
Host *
  ControlPath /tmp/workstation-manager-e2e-%C
Include "$ssh_config_path"
EOF

python3 -m pytest --ssh-config="$assertion_config" "$@"
