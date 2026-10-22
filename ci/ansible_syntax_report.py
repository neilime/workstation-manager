#!/usr/bin/env python3

"""Run Ansible syntax checks and emit a SARIF report."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass

ERROR_LINE_PATTERN = re.compile(r"^\[(?P<level>[A-Z]+)\]:\s*(?P<message>.*)$", re.MULTILINE)
ORIGIN_PATTERN = re.compile(
    r"^Origin:\s+(?P<path>.+?):(?P<line>\d+):(?P<column>\d+)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SyntaxIssue:
    """A single syntax-check failure normalized for reporting."""

    playbook: str
    level: str
    message: str
    output: str
    path: str
    line: int
    column: int


def parse_args() -> argparse.Namespace:
    """Parse the CLI used by the CI syntax-check wrapper."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Inventory file passed to ansible-playbook")
    parser.add_argument("--report-file", help="Optional SARIF output file")
    parser.add_argument("playbooks", nargs="+", help="Playbook files to syntax-check")
    return parser.parse_args()


def stream_command(command: list[str]) -> tuple[int, str]:
    """Run a command, stream its combined output, and return the exit code and output."""
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:
        if process.stdout is None:
            raise RuntimeError("could not capture ansible output")

        output_lines: list[str] = []
        for line in process.stdout:
            sys.stdout.write(line)
            output_lines.append(line)

        exit_code = process.wait()

    return exit_code, "".join(output_lines)


def parse_issue(playbook: str, output: str) -> SyntaxIssue:
    """Extract the primary diagnostic location and message from Ansible output."""
    error_match = ERROR_LINE_PATTERN.search(output)
    origin_match = ORIGIN_PATTERN.search(output)

    if error_match is None:
        message = f"Syntax check failed for {playbook}"
        level = "ERROR"
    else:
        message = error_match.group("message").strip() or f"Syntax check failed for {playbook}"
        level = error_match.group("level")

    if origin_match is None:
        path = playbook
        line = 1
        column = 1
    else:
        path = origin_match.group("path")
        line = int(origin_match.group("line"))
        column = int(origin_match.group("column"))

    return SyntaxIssue(
        playbook=playbook,
        level=level,
        message=message,
        output=output.strip(),
        path=path,
        line=line,
        column=column,
    )


def workspace_relative_path(path: str) -> str:
    """Convert absolute workspace paths into SARIF source-root relative URIs."""
    workspace_root = pathlib.Path.cwd()
    resolved_path = pathlib.Path(path)
    if not resolved_path.is_absolute():
        return resolved_path.as_posix()

    try:
        return resolved_path.relative_to(workspace_root).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def build_sarif(issues: list[SyntaxIssue]) -> dict[str, object]:
    """Build a SARIF payload for the collected syntax-check issues."""
    results: list[dict[str, object]] = []
    for issue in issues:
        results.append(
            {
                "ruleId": "ansible-playbook-syntax-check",
                "level": "error" if issue.level == "ERROR" else "warning",
                "message": {
                    "text": issue.message,
                    "markdown": f"```text\n{issue.output}\n```",
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": workspace_relative_path(issue.path),
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {
                                "startLine": issue.line,
                                "startColumn": issue.column,
                            },
                        }
                    }
                ],
                "properties": {
                    "playbook": issue.playbook,
                },
            }
        )

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ansible-playbook",
                        "informationUri": "https://docs.ansible.com/",
                        "rules": [
                            {
                                "id": "ansible-playbook-syntax-check",
                                "name": "Ansible playbook syntax check",
                                "shortDescription": {
                                    "text": "Ansible reported a playbook syntax error during CI validation.",
                                },
                            }
                        ],
                    }
                },
                "automationDetails": {
                    "id": "ansible/syntax-check",
                },
                "results": results,
            }
        ],
    }


def write_sarif(report_file: str, issues: list[SyntaxIssue]) -> None:
    """Write the SARIF payload to disk."""
    report_path = pathlib.Path(report_file)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(build_sarif(issues), indent=2) + "\n", encoding="utf-8")


def run() -> int:
    """Run syntax checks for all requested playbooks and optionally emit SARIF."""
    args = parse_args()
    issues: list[SyntaxIssue] = []
    highest_exit_code = 0

    for playbook in args.playbooks:
        command = [
            "ansible-playbook",
            "--syntax-check",
            "-i",
            args.inventory,
            playbook,
        ]
        exit_code, output = stream_command(command)
        if exit_code != 0:
            issues.append(parse_issue(playbook, output))
            highest_exit_code = max(highest_exit_code, exit_code)

    if args.report_file is not None:
        write_sarif(args.report_file, issues)

    return highest_exit_code


if __name__ == "__main__":
    raise SystemExit(run())
