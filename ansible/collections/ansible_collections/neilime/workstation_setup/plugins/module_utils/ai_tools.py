"""Resolve provisioned AI resources and secret references for provider adapters."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


class AiToolsRuntime:
    """Convert validated declarations and private vault records into local launches."""

    @staticmethod
    def credential_ids(declarations: list[dict]) -> list[str]:
        """Collect record selectors without resolving them or retaining literal values."""
        return sorted(
            {
                value["bitwarden_item_id"]
                for server in declarations
                for value in server["env"].values()
                if isinstance(value, dict)
            }
        )

    @staticmethod
    def credential(reference: dict, records: list[dict]) -> str:
        """Select exactly one record and field without exposing rejected values."""
        matches = [record for record in records if record.get("id") == reference["bitwarden_item_id"]]
        if len(matches) != 1:
            raise ValueError("An AI credential requires exactly one accessible Bitwarden item")
        record = matches[0]
        collection = reference.get("bitwarden_collection_id")
        if collection and collection not in record.get("collectionIds", []):
            raise ValueError("An AI credential item is outside the configured Bitwarden collection")
        field = reference["field"]
        if field.startswith("fields."):
            values = [item.get("value") for item in record.get("fields") or [] if item.get("name") == field[7:]]
            value = values[0] if len(values) == 1 else None
        elif field.startswith("login."):
            value = (record.get("login") or {}).get(field[6:])
        else:
            value = record.get(field)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("An AI credential field is missing, empty, duplicated or invalid")
        return value

    def servers(self, declarations: list[dict], home: str, records: list[dict]) -> dict:
        """Build native stdio fields with explicit executables and a stable Node PATH."""
        root = Path(home) / ".local/share/workstation-manager/ai-tools"
        result = {}
        for server in declarations:
            npm = server["npm"]
            args = list(server["args"])
            if npm:
                package_dir = root / "npm" / server["name"] / npm["version"]
                command = str(package_dir / "node_modules/.bin" / npm["binary"])
            else:
                command = server["command"]
            environment = {
                "HOME": home,
                "XDG_CONFIG_HOME": str(Path(home) / ".config"),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
            }
            environment.update(
                {
                    key: self.credential(value, records) if isinstance(value, dict) else value
                    for key, value in server["env"].items()
                }
            )
            if server["playwright"]:
                args += ["--browser", server["playwright"]["browser"]]
                environment["PLAYWRIGHT_BROWSERS_PATH"] = str(root / "browsers" / server["name"] / npm["version"])
            result[server["name"]] = {"command": command, "args": args, "env": environment}
        return result

    @staticmethod
    def skills(declarations: list[dict], home: str) -> list[dict]:
        """Resolve local content and isolate remote installations by their pinned source."""
        root = Path(home) / ".local/share/workstation-manager/ai-tools/skillshare"
        result = []
        for skill in declarations:
            if skill["kind"] == "local":
                source_root, relative = Path(home), skill["path"]
            else:
                source_root = root / sha256(skill["source"].encode()).hexdigest() / "skills"
                relative = skill["name"]
            result.append({"name": skill["name"], "root": str(source_root), "subdirectory": relative})
        return result
