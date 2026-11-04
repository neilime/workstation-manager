#!/usr/bin/env bash
# Local Goss execution; hosted CI uses ci-github-iac/actions/vm/test directly.
set -euo pipefail
umask 077
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Provisioning can change groups after Lima opens its shared SSH connection.
export SSH="$script_dir/lima-ssh.sh"
workspace_dir="$(cd -- "$script_dir/.." && pwd)"
vm_name="${1:?Expected VM name}"
phase="${2:?Expected assertion phase}"
case "$phase" in backup | setup | cleanup) ;; *) exit 2 ;; esac
report_dir="${REPORTS_DIR:-.reports}"
tooling_image="${TOOLING_IMAGE:-workstation-manager-tooling:local}"
bash "$script_dir/prepare-assertions.sh" "$vm_name" "$phase"
report_dir="$(cd -- "$report_dir" && pwd)"
mkdir -p "$report_dir/tests"
staging=$(mktemp -d)
guest=""
# Invoked indirectly by the EXIT trap, including after interrupted guest execution.
# shellcheck disable=SC2329
cleanup() {
	local result=$?
	if [[ -n "$guest" ]]; then
		timeout --kill-after=5s 30s limactl shell --workdir=/tmp "$vm_name" rm -rf -- "$guest" || result=1
	fi
	rm -rf "$staging"
	exit "$result"
}
trap 'cleanup' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
variables=()
if [[ "$phase" != backup ]]; then variables=(--vars /reports/goss/vars.json); fi
docker run --rm --user "$(id -u):$(id -g)" \
	--volume "$workspace_dir:/workspace:ro" --volume "$report_dir:/reports:ro" \
	"$tooling_image" goss -g "/workspace/e2e-tests/goss/$phase.yaml" "${variables[@]}" render >"$staging/goss.yaml"
docker run --rm "$tooling_image" cat /usr/local/bin/goss >"$staging/goss"
candidate=$(limactl shell --workdir=/tmp "$vm_name" mktemp -d /tmp/workstation-goss.XXXXXXXX)
[[ "$candidate" =~ ^/tmp/workstation-goss\.[a-zA-Z0-9]+$ ]] || exit 1
guest="$candidate"
limactl copy --backend=scp "$staging/goss" "$vm_name:$guest/goss"
limactl copy --backend=scp "$staging/goss.yaml" "$vm_name:$guest/goss.yaml"
status=0
limactl shell --workdir=/tmp "$vm_name" env GOSS_DIRECTORY="$guest" bash -s <<'GUEST' || status=$?
set -euo pipefail
chmod 700 "$GOSS_DIRECTORY/goss"
timeout --kill-after=5s 10m "$GOSS_DIRECTORY/goss" -g "$GOSS_DIRECTORY/goss.yaml" validate --format junit >"$GOSS_DIRECTORY/goss.xml"
GUEST
limactl copy --backend=scp "$vm_name:$guest/goss.xml" "$report_dir/tests/e2e-$phase.junit.xml"
# Goss accepts an empty suite; the workstation flow requires real assertions.
docker run --rm --volume "$report_dir:/reports:ro" "$tooling_image" \
	python3 -c 'import sys, xml.etree.ElementTree as ET; r=ET.parse(sys.argv[1]).getroot(); assert int(r.attrib["tests"]) > int(r.get("skipped", "0")); assert r.findall("testcase")' \
	"/reports/tests/e2e-$phase.junit.xml"
exit "$status"
