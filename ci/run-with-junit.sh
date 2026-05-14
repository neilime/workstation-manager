#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 4 ]]; then
	printf '%s\n' "usage: $0 <report-file> <suite-name> <test-name> <command> [args...]" >&2
	exit 2
fi

report_file="$1"
suite_name="$2"
test_name="$3"
shift 3

mkdir -p "$(dirname "$report_file")"

command_output_file="$(mktemp)"

if "$@" >"$command_output_file" 2>&1; then
	exit_code=0
else
	exit_code=$?
fi

command_output="$(cat "$command_output_file")"
rm -f "$command_output_file"

if [[ "$exit_code" -eq 0 ]]; then
	failures=0
else
	failures=1
fi

{
	printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>'
	printf '<testsuite name="%s" tests="1" failures="%s" errors="0" skipped="0">\n' "$suite_name" "$failures"
	printf '  <testcase classname="%s" name="%s">\n' "$suite_name" "$test_name"
	if [[ "$exit_code" -eq 0 ]]; then
		printf '    <system-out><![CDATA[\n%s\n]]></system-out>\n' "$command_output"
	else
		printf '    <failure message="command failed with exit code %s"><![CDATA[\n%s\n]]></failure>\n' "$exit_code" "$command_output"
	fi
	printf '%s\n' '  </testcase>'
	printf '%s\n' '</testsuite>'
} >"$report_file"

exit "$exit_code"
