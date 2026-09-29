#!/usr/bin/env bash

set -euo pipefail

tooling_uid="$1"
tooling_gid="$2"
shift 2

tooling_accounts_dir="$(mktemp -d)"
trap 'rm -rf "$tooling_accounts_dir"' EXIT
chmod 0755 "$tooling_accounts_dir"

# Numeric Docker users need an account whose home also exists inside the image.
# Keep host identities, but give the tooling account a writable container home.
awk -F: -v OFS=: -v uid="$tooling_uid" -v gid="$tooling_gid" '
	$3 == uid { $4 = gid; $6 = "/tmp"; $7 = "/bin/bash"; found = 1 }
	{ print }
	END { if (!found) print "workstation-tooling-" uid, "x", uid, gid, "", "/tmp", "/bin/bash" }
' /etc/passwd >"$tooling_accounts_dir/passwd"
awk -F: -v OFS=: -v gid="$tooling_gid" '
	$3 == gid { found = 1 }
	{ print }
	END { if (!found) print "workstation-tooling-" gid, "x", gid, "" }
' /etc/group >"$tooling_accounts_dir/group"
chmod 0644 "$tooling_accounts_dir/passwd" "$tooling_accounts_dir/group"

docker run \
	--user "$tooling_uid:$tooling_gid" \
	--volume "$tooling_accounts_dir/passwd:/etc/passwd:ro" \
	--volume "$tooling_accounts_dir/group:/etc/group:ro" \
	"$@"
