"""End-to-end checks for Bitwarden-backed secret restoration."""

from __future__ import annotations


def _has_gpg_record(output: str, record_type: str) -> bool:
    """Return whether `gpg --with-colons` output includes the given record."""

    return any(line.startswith(f"{record_type}:") for line in output.splitlines())


def test_secret_restore_permissions(host) -> None:
    """Bitwarden-backed SSH restore should write at least one keypair securely."""

    # Arrange
    public_key_listing = host.check_output(
        "find \"$HOME/.ssh\" -maxdepth 1 -type f -name '*.pub' | sort"
    )
    public_key_paths = [line for line in public_key_listing.splitlines() if line]

    # Assert
    assert public_key_paths

    for public_key_path in public_key_paths:
        public_key = host.file(public_key_path)
        private_key = host.file(public_key_path.removesuffix(".pub"))
        assert private_key.exists
        assert private_key.mode == 0o600
        assert public_key.exists
        assert public_key.mode == 0o644


def test_gpg_secret_restore(host) -> None:
    """Bitwarden-backed GPG restore should import secret and public keys."""

    # Arrange
    user_home = host.check_output("printf '%s' \"$HOME\"")
    gnupg_home = host.file(f"{user_home}/.gnupg")

    # Act
    secret_key_result = host.run("gpg --batch --with-colons --list-secret-keys")
    public_key_result = host.run("gpg --batch --with-colons --list-keys")

    # Assert
    assert gnupg_home.exists
    assert gnupg_home.is_directory
    assert gnupg_home.mode == 0o700
    assert secret_key_result.succeeded
    assert _has_gpg_record(secret_key_result.stdout, "sec")
    assert public_key_result.succeeded
    assert _has_gpg_record(public_key_result.stdout, "pub")


def test_git_gpg_signing_configuration(host) -> None:
    """Git signing should be configured from the restored GPG key."""

    # Act
    signing_key_result = host.run("git config --global --get user.signingkey")
    commit_sign_result = host.run("git config --global --get commit.gpgsign")
    tag_sign_result = host.run("git config --global --get tag.gpgsign")
    gpg_format_result = host.run("git config --global --get gpg.format")
    secret_key_result = host.run(
        "gpg --batch --with-colons --list-secret-keys "
        '"$(git config --global --get user.signingkey)"'
    )

    # Assert
    assert signing_key_result.succeeded
    assert signing_key_result.stdout.strip()
    assert commit_sign_result.succeeded
    assert commit_sign_result.stdout.strip() == "true"
    assert tag_sign_result.succeeded
    assert tag_sign_result.stdout.strip() == "true"
    assert gpg_format_result.succeeded
    assert gpg_format_result.stdout.strip() == "openpgp"
    assert secret_key_result.succeeded
    assert _has_gpg_record(secret_key_result.stdout, "sec")
