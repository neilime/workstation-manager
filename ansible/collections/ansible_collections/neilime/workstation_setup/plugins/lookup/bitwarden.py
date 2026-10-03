# Copyright: (c) 2026, workstation-manager contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Use the community Bitwarden lookup with scoped cache access and safe failures."""

from __future__ import annotations

DOCUMENTATION = r"""
name: bitwarden
short_description: Read Bitwarden records using the community lookup without exposing CLI errors
author:
  - workstation-manager contributors (@neilime)
description:
  - Delegates record retrieval to C(community.general.bitwarden).
  - Selects the managed user's CLI cache for the duration of the lookup.
  - Sanitizes exceptions because lookup errors can be displayed before task C(no_log) takes effect.
requirements:
  - community.general >= 10.4.0
  - An installed Bitwarden CLI with an authenticated and unlocked cache.
options:
  _terms:
    description: Record selectors. An empty string selects all collection records.
    type: list
    elements: str
    required: true
  appdata_dir:
    description: Absolute path to the managed user's Bitwarden CLI cache on the controller.
    type: str
    required: true
  bw_session:
    description: The current unlocked vault session.
    type: str
    required: true
  collection_id:
    description: Restrict collection enumeration to this collection ID.
    type: str
  search:
    description: Record selector field. Use C(id) for a single record.
    type: str
    default: name
    choices: [name, id]
  result_count:
    description: Fail unless each selector returns this number of records.
    type: int
"""

EXAMPLES = r"""
- name: Read every record in the recovery collection
  ansible.builtin.set_fact:
    recovery_records: >-
      {{ query('neilime.workstation_setup.bitwarden', '',
               appdata_dir=bitwarden_collection_appdata_dir,
               collection_id=bitwarden_collection_id,
               bw_session=bitwarden_collection_session) | first }}
  no_log: true
"""

RETURN = r"""
_raw:
  description: One list of complete records per selector, preserving empty collections.
  type: list
  elements: list
"""


# Ansible requires plugin documentation before runtime imports.
# pylint: disable=wrong-import-position
import os  # noqa: E402
from typing import Any  # noqa: E402

from ansible.errors import AnsibleError  # noqa: E402
from ansible.plugins.loader import lookup_loader  # noqa: E402
from ansible.plugins.lookup import LookupBase  # noqa: E402

# pylint: enable=wrong-import-position


# Ansible lookup plugins expose a single run entrypoint.
# pylint: disable-next=too-few-public-methods
class LookupModule(LookupBase):
    """Adapt controller context and error reporting, leaving all reads to upstream."""

    def run(self, terms: list[str], variables: dict | None = None, **kwargs: Any) -> list:
        """Read records with the managed cache and restore the controller environment."""

        self.set_options(var_options=variables, direct=kwargs)
        appdata_dir = self.get_option("appdata_dir")
        if not os.path.isabs(appdata_dir):
            raise AnsibleError("Bitwarden appdata_dir must be an absolute path")
        options = {key: self.get_option(key) for key in ("bw_session", "collection_id", "search", "result_count")}
        environment = {"BITWARDENCLI_APPDATA_DIR": appdata_dir, "BW_NOINTERACTION": "true"}
        previous = {key: os.environ.get(key) for key in environment}
        try:
            os.environ.update(environment)
            lookup = lookup_loader.get("community.general.bitwarden", loader=self._loader, templar=self._templar)
            return lookup.run(terms, variables=variables, **options)
        except Exception:
            # Upstream exceptions can contain vault data in CLI stderr. Never chain them.
            raise AnsibleError(
                "Bitwarden record lookup failed; check the unlocked session, CLI installation, "
                "and access to the requested records. Missing or unexpected records also stop recovery."
            ) from None
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
