"""Verify repository downloads and cleanup without network or workstation changes."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).parents[2]


@pytest.mark.parametrize("downloader", ["wget", "curl"])
@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("exit_code", [0, 23])
def test_github_download_preserves_arguments_and_status(
    tmp_path: pathlib.Path, downloader: str, authenticated: bool, exit_code: int
) -> None:
    """Either downloader must preserve literal paths, optional headers, and failures."""
    command = tmp_path / downloader
    command.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        'pathlib.Path(os.environ["TEST_ARGUMENTS"]).write_text(json.dumps(sys.argv[1:]))\n'
        'sys.exit(int(os.environ["TEST_EXIT_CODE"]))\n'
    )
    command.chmod(0o700)
    arguments_file = tmp_path / "arguments.json"
    destination = tmp_path / "download's file.yml"
    token = "fixture'token $HOME $(false)" if authenticated else ""
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    result = subprocess.run(
        ["/bin/sh", "-s"],
        input=definitions + '\ndownload_github_file example/project feature/test "path/file.yml" "$TEST_DESTINATION"\n',
        env={
            "PATH": str(tmp_path),
            "WORKSTATION_MANAGER_GITHUB_TOKEN": token,
            "TEST_ARGUMENTS": str(arguments_file),
            "TEST_DESTINATION": str(destination),
            "TEST_EXIT_CODE": str(exit_code),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    arguments = json.loads(arguments_file.read_text())
    output_option = "-O" if downloader == "wget" else "-o"
    assert arguments[arguments.index(output_option) + 1] == str(destination)
    if authenticated:
        assert f"Authorization: Bearer {token}" in arguments
        assert "Accept: application/vnd.github.raw" in arguments
        assert arguments[-1] == "https://api.github.com/repos/example/project/contents/path/file.yml?ref=feature/test"
    else:
        assert "--header" not in arguments
        assert arguments[-1] == "https://raw.githubusercontent.com/example/project/feature/test/path/file.yml"
    assert "fixture'token" not in result.stdout + result.stderr


@pytest.mark.parametrize("installer", ["install_ansible_packages", "install_collection_requirements"])
def test_failed_manifest_download_is_cleaned_up(tmp_path: pathlib.Path, installer: str) -> None:
    """A failed download must stop even in a conditional and remove partial files."""
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    result = subprocess.run(
        ["/bin/sh", "-s"],
        input=definitions
        + '\ndownload_repository_file() { printf partial >"$2"; return 23; }\n'
        + 'install_collection_requirements_file() { printf "unexpected collection install\\n"; }\n'
        + f"if {installer}; then exit 0; else exit $?; fi\n",
        env={"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "unexpected collection install" not in result.stdout
    assert not list(tmp_path.iterdir())
