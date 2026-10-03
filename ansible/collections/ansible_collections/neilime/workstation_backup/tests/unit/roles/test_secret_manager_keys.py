"""Parse dynamic key-sync tasks without contacting a secret manager."""

import base64
import json
from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.task import Task
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
from ansible.utils.collection_loader._collection_config import AnsibleCollectionConfig


@pytest.mark.parametrize("filename", ["fixture", "fixture.pub"])
@pytest.mark.parametrize("public_is_regular", [False, True])
def test_missing_public_key_reports_misnamed_private_key(filename: str, public_is_regular: bool) -> None:
    """Missing companions must fail with actionable diagnostics for misnamed private keys."""

    if AnsibleCollectionConfig.collection_finder is None:
        init_plugin_loader()
    loader = DataLoader()
    task_file = Path(__file__).resolve().parents[3] / "roles/secret_manager_keys/tasks/collect_ssh_key.yml"
    task = next(
        Task.load(value, loader=loader)
        for value in loader.load_from_file(str(task_file), trusted_as_template=True)
        if value["name"] == "Require a public key for each local SSH private key"
    )
    templar = Templar(
        loader=loader,
        variables={
            "item": {"path": f"/home/fixture/.ssh/{filename}"},
            "workstation_backup_secret_manager_public_key_stat": {"stat": {"isreg": public_is_regular}},
        },
    )
    assert all(templar.evaluate_conditional(condition) for condition in task.args["that"]) is public_is_regular
    message = templar.template(task.args["fail_msg"])
    if filename.endswith(".pub"):
        assert "contains SSH private-key material despite its .pub filename" in message
        assert "Bitwarden private_key/public_key fields" in message
        assert ".pub.pub" not in message
    else:
        assert f"without its public key /home/fixture/.ssh/{filename}.pub" in message


@pytest.mark.parametrize(
    "action, command", [("add", ["bw", "create", "item"]), ("update", ["bw", "edit", "item", "fixture-id"])]
)
def test_key_writes_receive_base64_json_on_stdin(action: str, command: list[str]) -> None:
    """Create and update preserve multiline and Unicode payloads without exposing argv secrets."""

    if AnsibleCollectionConfig.collection_finder is None:
        init_plugin_loader()
    task_file = Path(__file__).resolve().parents[3] / "roles/secret_manager_keys/tasks/apply_action.yml"
    loader = DataLoader()
    tasks = [Task.load(task, loader=loader) for task in loader.load_from_file(str(task_file), trusted_as_template=True)]

    save_task = next(task for task in tasks if task.name == "Save the synchronized Bitwarden key item")
    payload = {"name": "fixture-é", "fields": [{"name": "private_key", "value": "synthetic\nkey material"}]}
    templar = Templar(
        loader=loader,
        variables={
            "item": {"action": action, "bitwarden_item_id": "fixture-id"},
            "workstation_backup_secret_manager_item_payload": payload,
        },
    )
    assert templar.template(save_task.args["argv"]) == command
    assert json.loads(base64.b64decode(templar.template(save_task.args["stdin"]))) == payload


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
    task_file = Path(__file__).resolve().parents[3] / "roles/secret_manager_keys/tasks/apply_action.yml"
    task = next(
        Task.load(value, loader=loader)
        for value in loader.load_from_file(str(task_file), trusted_as_template=True)
        if value["name"] == "Require the saved key to match before backup continues"
    )
    variables = {
        "item": {"collection_id": "ssh-collection", "fields": [{"name": "private_key", "value": "fixture-private"}]},
        "workstation_backup_secret_manager_verified_item": {
            "fields": [{"name": "private_key", "value": stored_value}],
            "collectionIds": collections,
        },
    }
    templar = Templar(loader=loader, variables=variables)
    assert all(templar.evaluate_conditional(condition) for condition in task.args["that"]) is expected
