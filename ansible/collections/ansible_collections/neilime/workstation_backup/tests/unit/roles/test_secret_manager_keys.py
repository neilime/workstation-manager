"""Parse dynamic key-sync tasks without contacting a secret manager."""

import json
from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.task import Task
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
from ansible.utils.collection_loader._collection_config import AnsibleCollectionConfig


def test_dynamic_key_actions_parse_and_pass_payload_to_encoder() -> None:
    """Dynamic includes must parse and send the item payload on command stdin."""

    if AnsibleCollectionConfig.collection_finder is None:
        init_plugin_loader()
    task_file = Path(__file__).resolve().parents[3] / "roles/secret_manager_keys/tasks/prompt_and_apply_action.yml"
    loader = DataLoader()
    tasks = [Task.load(task, loader=loader) for task in loader.load_from_file(str(task_file), trusted_as_template=True)]

    encode_task = next(task for task in tasks if task.args.get("argv") == ["bw", "encode"])
    assert "workstation_backup_secret_manager_item_payload" in encode_task.args["stdin"]


@pytest.mark.parametrize(
    "stored_value, collections, expected",
    [
        ("fixture-private", ["ssh-collection"], True),
        ("wrong-private", ["ssh-collection"], False),
        ("fixture-private", [], False),
        ("fixture-private", ["another-collection"], False),
    ],
)
def test_saved_key_readback_must_match_content_and_collection(
    stored_value: str,
    collections: list[str],
    expected: bool,
) -> None:
    """A successful CLI exit cannot let mismatched or misplaced key material pass verification."""

    if AnsibleCollectionConfig.collection_finder is None:
        init_plugin_loader()
    loader = DataLoader()
    task_file = Path(__file__).resolve().parents[3] / "roles/secret_manager_keys/tasks/prompt_and_apply_action.yml"
    task = next(
        Task.load(value, loader=loader)
        for value in loader.load_from_file(str(task_file), trusted_as_template=True)
        if value["name"] == "Require the saved key to match before backup continues"
    )
    variables = {
        "item": {"collection_id": "ssh-collection", "fields": [{"name": "private_key", "value": "fixture-private"}]},
        "workstation_backup_secret_manager_verified_item": {
            "stdout": json.dumps(
                {
                    "fields": [{"name": "private_key", "value": stored_value}],
                    "collectionIds": collections,
                }
            )
        },
    }
    templar = Templar(loader=loader, variables=variables)
    assert all(templar.evaluate_conditional(condition) for condition in task.args["that"]) is expected
