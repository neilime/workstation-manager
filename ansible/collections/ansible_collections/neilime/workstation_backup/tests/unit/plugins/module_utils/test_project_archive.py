"""Verify backup selection, pruning, and failure handling with disposable projects."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils import (
    project_archive,
)


def run_command(arguments, *, environ_update):
    """Run the same read-only Git probe used by the Ansible module."""

    result = subprocess.run(
        arguments, env={**os.environ, **environ_update}, capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout, result.stderr


def git(repository: Path, *arguments: str) -> None:
    """Prepare Git fixtures without contacting remotes."""

    subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, check=True)


def initialize_repository(path: Path) -> Path:
    """Create an empty project whose files do not require a commit to back up."""

    path.mkdir(parents=True)
    git(path, "init", "--initial-branch=main")
    return path


@pytest.fixture(name="projects")
def projects_fixture(tmp_path, monkeypatch):
    """Isolate all global ignore settings from the developer's workstation."""

    for name, value in {"HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(name, value)
    projects = tmp_path / "projects with spaces"
    projects.mkdir()
    return projects


def create_archive(projects, *, paths=None, patterns=None):
    """Return actual archived entry names and the writer's result."""

    destination = projects.parent / "backup.tar.gz"
    result = project_archive.ProjectArchiveWriter(run_command).create(
        paths or [str(projects)], str(destination), patterns or []
    )
    with tarfile.open(destination, "r:gz") as archive:
        return archive.getnames(), result


@pytest.mark.parametrize("ignore_source", [".gitignore", "tools/.gitignore", ".git/info/exclude", "global"])
def test_standard_git_ignores_prune_dependency_trees(projects, monkeypatch, ignore_source):
    """Ignored dependency trees must never reach the archive writer or directory walker."""

    project = initialize_repository(projects / "client")
    ignored = initialize_repository(project / "tools/vendor/dependency")
    (ignored / "private.txt").write_text("synthetic-excluded-marker")
    ignore_file = project / ignore_source
    if ignore_source == "global":
        ignore_file = projects.parent / "global-ignore"
        git(project, "config", "core.excludesFile", str(ignore_file))
    ignore_file.parent.mkdir(parents=True, exist_ok=True)
    ignore_file.write_text("vendor/\n" if ignore_source == "tools/.gitignore" else "tools/vendor/\n")
    (project / "local-note.txt").write_text("untracked source")
    original_scandir = project_archive.os.scandir
    calls = []

    def guarded_scandir(path):
        assert not Path(path).is_relative_to(project / "tools/vendor")
        assert ".git" not in Path(path).parts
        return original_scandir(path)

    def counted_command(arguments, **options):
        calls.append(arguments)
        return run_command(arguments, **options)

    monkeypatch.setattr(project_archive.os, "scandir", guarded_scandir)
    destination = projects.parent / "backup.tar.gz"
    project_archive.ProjectArchiveWriter(counted_command).create([str(projects)], str(destination), [])
    with tarfile.open(destination, "r:gz") as archive:
        names = archive.getnames()
    assert "projects with spaces/client/local-note.txt" in names
    assert not any("vendor" in name or "/.git/" in name for name in names)
    assert len([command for command in calls if command[0] == "git"]) == 1


def test_negations_tracked_edits_and_unusual_names_are_preserved(projects):
    """Ignore rules must preserve exceptions and tracked files in ignored directories."""

    project = initialize_repository(projects / "client")
    (project / "cache").mkdir()
    tracked = project / "cache/tracked.txt"
    tracked.write_text("initial")
    git(project, "add", "cache/tracked.txt")
    index = (project / ".git/index").read_bytes()
    tracked.write_text("local changes")
    (project / ".gitignore").write_text("cache/\n*.log\n!keep.log\n")
    (project / "cache/ignored.txt").write_text("ignored")
    (project / "skip.log").write_text("ignored")
    (project / "keep.log").write_text("keep")
    (project / "ignored\nname.log").write_text("ignored unusual name")
    (project / "keep\nname.txt").write_text("untracked unusual name")
    names, _result = create_archive(projects)
    prefix = "projects with spaces/client/"
    assert prefix + "cache/tracked.txt" in names
    assert prefix + "keep.log" in names
    assert prefix + "keep\nname.txt" in names
    assert not any(name.endswith(("ignored.txt", "skip.log", "ignored\nname.log")) for name in names)
    with tarfile.open(projects.parent / "backup.tar.gz", "r:gz") as archive:
        assert archive.extractfile(prefix + "cache/tracked.txt").read() == b"local changes"
    assert (project / ".git/index").read_bytes() == index


def test_nested_repositories_and_gitfiles_apply_their_own_ignores(projects):
    """Visible nested projects and linked worktrees must apply their Git configuration."""

    project = initialize_repository(projects / "client")
    (project / ".gitignore").write_text("nested/*\n!nested/keep/\n")
    child = initialize_repository(project / "nested/keep")
    (child / ".gitignore").write_text("private.txt\n")
    (child / "private.txt").write_text("ignored")
    (child / "source.txt").write_text("keep")
    (project / "seed.txt").write_text("seed")
    git(project, "add", "seed.txt")
    git(project, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Seed")
    worktree = projects / "linked worktree"
    git(project, "worktree", "add", "-b", "fixture", str(worktree))
    (worktree / ".gitignore").write_text("private.txt\n")
    (worktree / "private.txt").write_text("ignored")
    (worktree / "source.txt").write_text("keep")
    names, _result = create_archive(projects)
    assert "projects with spaces/client/nested/keep/source.txt" in names
    assert "projects with spaces/linked worktree/source.txt" in names
    assert not any(name.endswith(("private.txt", "/.git")) for name in names)


def test_non_git_files_fixed_exclusions_symlinks_and_overlapping_sources(projects, monkeypatch):
    """Archive each path once, preserve links, and skip build trees even outside Git."""

    (projects / "source.txt").write_text("keep")
    (projects / "empty").mkdir()
    (projects / "node_modules").mkdir()
    (projects / "node_modules/excluded.txt").write_text("ignored")
    outside = projects.parent / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("outside source scope")
    (projects / "linked").symlink_to(outside, target_is_directory=True)
    (projects / "broken").symlink_to("missing")
    original_scandir = project_archive.os.scandir

    def guarded_scandir(path):
        assert Path(path).name not in ("node_modules", "linked")
        return original_scandir(path)

    monkeypatch.setattr(project_archive.os, "scandir", guarded_scandir)
    names, _result = create_archive(
        projects, paths=[str(projects), str(projects / "source.txt")], patterns=["*/node_modules/*"]
    )
    assert len(names) == len(set(names))
    assert "projects with spaces/source.txt" in names
    assert "projects with spaces/empty" in names
    assert not any(name.endswith(("excluded.txt", "private.txt")) for name in names)
    with tarfile.open(projects.parent / "backup.tar.gz", "r:gz") as archive:
        assert archive.getmember("projects with spaces/linked").issym()
        assert archive.getmember("projects with spaces/broken").linkname == "missing"


def test_explicit_sources_inside_a_repository_still_apply_ignores(projects):
    """Additional paths cannot bypass the enclosing project's ignore rules."""

    project = initialize_repository(projects / "client")
    (project / ".gitignore").write_text("ignored/\n*.log\n")
    (project / "ignored").mkdir()
    (project / "ignored/private.txt").write_text("ignored")
    (project / "source").mkdir()
    (project / "source/keep.txt").write_text("keep")
    (project / "source/private.log").write_text("ignored")
    names, _result = create_archive(projects, paths=[str(project / "source"), str(project / "ignored")])
    assert "source/keep.txt" in names
    assert not any("ignored" in name or name.endswith(".log") for name in names)


def test_preview_idempotence_and_private_permissions(projects):
    """Preview must not write, and repeat output must retain accurate change reporting."""

    (projects / "source.txt").write_text("keep")
    destination = projects.parent / "backup.tar.gz"
    writer = project_archive.ProjectArchiveWriter(run_command)
    result = writer.create([str(projects)], str(destination), [], check_mode=True)
    assert result["changed"] and result["archived_count"] == 2
    assert not destination.exists()
    assert not project_archive.archive_staging_path(str(destination)).exists()
    assert writer.create([str(projects)], str(destination), [])["changed"]
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not writer.create([str(projects)], str(destination), [])["changed"]
    destination.chmod(0o644)
    assert writer.create([str(projects)], str(destination), [])["changed"]
    assert destination.stat().st_mode & 0o777 == 0o600


def test_explicit_archive_root_preserves_the_home_relative_project_path(tmp_path):
    """Selecting one present source must not shorten a root chosen from all requested paths."""

    home = tmp_path / "home"
    projects = home / "Documents/dev-projects"
    projects.mkdir(parents=True)
    (projects / "local-note.txt").write_text("untracked source")
    destination = tmp_path / "backup.tar.gz"
    result = project_archive.ProjectArchiveWriter(run_command).create(
        [str(projects)], str(destination), [], root=str(home)
    )
    assert result["arcroot"] == str(home)
    with tarfile.open(destination, "r:gz") as archive:
        assert archive.getnames() == ["Documents/dev-projects", "Documents/dev-projects/local-note.txt"]


def test_explicit_archive_root_rejects_sources_outside_it(projects):
    """Invalid roots must fail before writing or replacing an archive."""

    destination = projects.parent / "backup.tar.gz"
    outside = projects.parent / "outside.txt"
    outside.write_text("outside root")
    with pytest.raises(ValueError, match="inside the archive root"):
        project_archive.ProjectArchiveWriter(run_command).create(
            [str(outside)], str(destination), [], root=str(projects)
        )
    assert not destination.exists()


def test_native_tar_treats_filenames_as_data_and_ignores_inherited_options(projects, monkeypatch):
    """Leading dashes and newlines must not become tar options or split the selection list."""

    source = projects / "--checkpoint-action=echo=unexpected\nname.txt"
    source.write_text("keep")
    monkeypatch.setenv("TAR_OPTIONS", "--exclude=*")
    monkeypatch.setenv("GZIP", "-9")
    names, _result = create_archive(projects, paths=[str(source)])
    assert names == [source.name]


@pytest.mark.parametrize("exit_status", [1, 2])
def test_failed_creation_preserves_the_previous_archive_and_removes_partial_output(projects, exit_status):
    """Unreadable inputs must fail without replacing an existing completed backup."""

    (projects / "source.txt").write_text("keep")
    destination = projects.parent / "backup.tar.gz"
    destination.write_bytes(b"previous completed archive")

    def failed_archive(arguments, **options):
        if arguments[0] == "tar":
            return exit_status, "synthetic-private-output", "synthetic-private-diagnostics"
        return run_command(arguments, **options)

    with pytest.raises(ValueError, match="Backup archive creation failed") as failure:
        project_archive.ProjectArchiveWriter(failed_archive).create([str(projects)], str(destination), [])
    assert "synthetic-private" not in str(failure.value)
    assert destination.read_bytes() == b"previous completed archive"
    assert not project_archive.archive_staging_path(str(destination)).exists()


def test_directory_read_failures_are_fatal(projects, monkeypatch):
    """An unreadable source must never produce a successful but incomplete archive."""

    def unreadable_directory(_path):
        raise PermissionError("Cannot read fixture directory")

    monkeypatch.setattr(project_archive.os, "scandir", unreadable_directory)
    with pytest.raises(PermissionError, match="Cannot read fixture directory"):
        create_archive(projects)
    assert not (projects.parent / "backup.tar.gz").exists()


def test_special_files_are_rejected_before_publication(projects):
    """Recovery rejects special files, so backup must not report them as recoverable."""

    os.mkfifo(projects / "pipe")
    with pytest.raises(ValueError, match="Unsupported backup source type"):
        create_archive(projects)
    assert not (projects.parent / "backup.tar.gz").exists()


def test_git_inspection_failures_are_fatal_without_exposing_diagnostics(projects):
    """A broken repository must never cause ignored files to be included silently."""

    initialize_repository(projects / "client")

    def rejected_command(*_args, **_kwargs):
        return 128, "synthetic-private-output", "synthetic-private-diagnostics"

    with pytest.raises(ValueError, match="Git ignore inspection failed") as failure:
        project_archive.ProjectArchiveWriter(rejected_command).create(
            [str(projects)], str(projects.parent / "backup.tar.gz"), []
        )
    assert "synthetic-private" not in str(failure.value)
    assert not (projects.parent / "backup.tar.gz").exists()


def test_destinations_inside_sources_and_existing_staging_files_are_rejected(projects):
    """Avoid recursive self-backups and never overwrite another operation's staging data."""

    writer = project_archive.ProjectArchiveWriter(run_command)
    source = projects / "source.txt"
    source.write_text("keep")
    with pytest.raises(ValueError, match="must not overwrite a source"):
        writer.create([str(source)], str(source), [])
    assert source.read_text() == "keep"
    with pytest.raises(ValueError, match="outside every source"):
        writer.create([str(projects)], str(projects / "backup.tar.gz"), [])
    destination = projects.parent / "backup.tar.gz"
    staging = project_archive.archive_staging_path(str(destination))
    staging.write_bytes(b"other operation")
    with pytest.raises(ValueError, match="Incomplete backup already exists"):
        writer.create([str(projects)], str(destination), [])
    assert staging.read_bytes() == b"other operation"
