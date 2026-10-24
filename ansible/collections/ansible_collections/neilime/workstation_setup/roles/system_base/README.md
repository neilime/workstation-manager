# system_base

Checks the supported Ubuntu release and Snap boot dependencies, prevents Snap
reinstallation, applies locale, timezone, prerequisite packages, and managed
kernel `sysctl` settings (IPv6 is disabled system-wide by default), and creates
the root-owned state directory from `workstation_manager_resolved.system`.

See [configuration](../../../../../../../docs/usage/configuration.md) for inputs
and the [development guide](../../../../../../../docs/development/README.md) for
structure and checks.
