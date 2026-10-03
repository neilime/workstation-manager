"""Verify the community lookup adapter restores context and hides upstream errors."""

from __future__ import annotations

import os
from unittest.mock import Mock

import pytest
from ansible.errors import AnsibleError
from ansible_collections.neilime.workstation_setup.plugins.lookup import bitwarden


@pytest.mark.parametrize("previous", [None, "/controller/cache"])
@pytest.mark.parametrize("failure", [False, True])
def test_scopes_cache_and_restores_environment(monkeypatch, previous, failure) -> None:
    """Both successful and failed reads leave the controller environment intact."""

    keys = ("BITWARDENCLI_APPDATA_DIR", "BW_NOINTERACTION")
    for key in keys:
        if previous is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, previous)
    options = {
        "appdata_dir": "/managed/home/.config/Bitwarden CLI",
        "bw_session": "synthetic-session",
        "collection_id": "fixture-collection",
        "search": "name",
        "result_count": None,
    }
    adapter = bitwarden.LookupModule()
    monkeypatch.setattr(adapter, "set_options", Mock())
    monkeypatch.setattr(adapter, "get_option", options.__getitem__)
    upstream = Mock()

    def read(terms, variables, **kwargs):
        assert terms == [""]
        assert variables == {"fixture": True}
        assert kwargs == {key: value for key, value in options.items() if key != "appdata_dir"}
        assert os.environ["BITWARDENCLI_APPDATA_DIR"] == options["appdata_dir"]
        assert os.environ["BW_NOINTERACTION"] == "true"
        if failure:
            raise AnsibleError("synthetic-secret-in-stderr")
        return [[]]

    upstream.run.side_effect = read
    load = Mock(return_value=upstream)
    monkeypatch.setattr(bitwarden.lookup_loader, "get", load)
    if failure:
        with pytest.raises(AnsibleError, match="Bitwarden record lookup failed") as error:
            adapter.run([""], variables={"fixture": True})
        assert "synthetic-secret" not in str(error.value)
        assert error.value.__suppress_context__
    else:
        assert adapter.run([""], variables={"fixture": True}) == [[]]
    assert load.call_count == 1
    assert load.call_args.args == ("community.general.bitwarden",)
    assert {key: os.environ.get(key) for key in keys} == dict.fromkeys(keys, previous)
