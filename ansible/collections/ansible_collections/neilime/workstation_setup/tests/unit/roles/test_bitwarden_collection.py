"""Parse Bitwarden collection tasks without contacting Bitwarden."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from ansible.parsing.dataloader import DataLoader

TaskDefinition = dict[str, Any]


def _load_tasks() -> list[TaskDefinition]:
    """Load the Bitwarden collection role task file."""

    task_file = Path(__file__).resolve().parents[3] / "roles/bitwarden_collection/tasks/main.yml"
    loader = DataLoader()
    return cast(list[TaskDefinition], loader.load_from_file(str(task_file), trusted_as_template=True))


def test_collection_role_reads_items_with_lookup_plugin() -> None:
    """Collection item reads should use the supported Bitwarden lookup plugin."""

    tasks = _load_tasks()
    read_task = next(task for task in tasks if task["name"] == "Read Bitwarden collection items")

    assert "ansible.builtin.set_fact" in read_task
    expression = cast(str, read_task["ansible.builtin.set_fact"]["bitwarden_collection_items"])
    assert "query(" in expression
    assert "community.general.bitwarden" in expression
    assert "''," in expression
    assert "default([[]])" in expression
    assert "default([], true)" in expression
    assert "collection_id=bitwarden_collection_id" in expression
    assert "bw_session=bitwarden_collection_session" in expression


def test_collection_role_no_longer_lists_items_via_bw_command() -> None:
    """The role should no longer shell out to `bw list items` directly."""

    tasks = _load_tasks()

    assert not any(task["name"] == "Collect the Bitwarden collection records" for task in tasks)
    assert not any(_lists_bitwarden_items(task) for task in tasks)


def _lists_bitwarden_items(task: dict[str, object]) -> bool:
    """Return whether a task still shells out to `bw list items`."""

    command = task.get("ansible.builtin.command")
    if isinstance(command, dict):
        return command.get("argv", [])[:3] == ["bw", "list", "items"]

    return command == "bw list items"
