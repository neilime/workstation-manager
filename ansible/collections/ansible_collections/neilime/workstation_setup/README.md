# neilime.workstation_setup

Owns configuration normalization, system and application setup, secrets retrieval,
home-environment setup (including Oh My Zsh and Chezmoi), developer tooling,
and browser adapters. Developer tool
installation uses the GitHub credentials described in the
[configuration guide](../../../../../docs/usage/configuration.md#automated-runs).
SSH restoration rejects private-key material in a Bitwarden `public_key` field
before writing the key pair.

See the [development guide](../../../../../docs/development/README.md) for
structure and checks, and the
[browser adapter contract](../../../../../docs/development/browser-adapters.md)
for adding a browser. User workflows live in the
[documentation index](../../../../../docs/README.md).
