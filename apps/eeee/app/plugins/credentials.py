"""Credential adapters that keep provider secrets outside EEEE state records."""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4


class MemoryCredentialStore:
    """Deterministic credential store used by tests and injected providers."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def put(self, user_id: str, plugin_id: str, value: str) -> str:
        if not user_id.strip() or not plugin_id.strip() or not value.strip():
            raise ValueError("credential owner, plugin, and value are required")
        reference = f"memory://{sha256(f'{user_id}:{plugin_id}:{uuid4().hex}'.encode()).hexdigest()}"
        self._values[reference] = value
        return reference

    def get(self, reference: str) -> str | None:
        return self._values.get(reference)

    def delete(self, reference: str) -> None:
        self._values.pop(reference, None)


class KeyringCredentialStore:
    """OS-backed credential adapter; values never enter SQLite or API models."""

    SERVICE = "Gleave/EEEE/plugin"
    # Windows Credential Manager limits the credential blob size. OAuth token
    # payloads can exceed that limit, so keep each keyring item comfortably
    # below it and reconstruct the value on read.
    CHUNK_SIZE = 200
    MANIFEST_SUFFIX = ":manifest"
    CHUNK_SUFFIX = ":chunk:"

    @staticmethod
    def _module():
        try:
            import keyring
        except ModuleNotFoundError as exc:
            raise RuntimeError("OS credential storage is unavailable") from exc
        return keyring

    def put(self, user_id: str, plugin_id: str, value: str) -> str:
        if not user_id.strip() or not plugin_id.strip() or not value.strip():
            raise ValueError("credential owner, plugin, and value are required")
        keyring = self._module()
        reference = f"keyring://{sha256(f'{user_id}:{plugin_id}:{uuid4().hex}'.encode()).hexdigest()}"
        chunks = [value[index:index + self.CHUNK_SIZE] for index in range(0, len(value), self.CHUNK_SIZE)]
        written: list[str] = []
        manifest = f"{reference}{self.MANIFEST_SUFFIX}"
        try:
            keyring.set_password(self.SERVICE, manifest, str(len(chunks)))
            written.append(manifest)
            for index, chunk in enumerate(chunks):
                chunk_reference = f"{reference}{self.CHUNK_SUFFIX}{index}"
                keyring.set_password(self.SERVICE, chunk_reference, chunk)
                written.append(chunk_reference)
        except Exception:
            for item in written:
                self._delete_if_present(keyring, item)
            raise
        return reference

    def get(self, reference: str) -> str | None:
        keyring = self._module()
        manifest = keyring.get_password(self.SERVICE, f"{reference}{self.MANIFEST_SUFFIX}")
        if manifest is None:
            # Keep credentials written by older EEEE builds readable.
            return keyring.get_password(self.SERVICE, reference)
        try:
            chunk_count = int(manifest)
        except ValueError:
            return None
        chunks: list[str] = []
        for index in range(chunk_count):
            chunk = keyring.get_password(self.SERVICE, f"{reference}{self.CHUNK_SUFFIX}{index}")
            if chunk is None:
                return None
            chunks.append(chunk)
        return "".join(chunks)

    def delete(self, reference: str) -> None:
        keyring = self._module()
        manifest_reference = f"{reference}{self.MANIFEST_SUFFIX}"
        manifest = keyring.get_password(self.SERVICE, manifest_reference)
        if manifest is not None:
            try:
                chunk_count = int(manifest)
            except ValueError:
                chunk_count = 0
            for index in range(chunk_count):
                self._delete_if_present(keyring, f"{reference}{self.CHUNK_SUFFIX}{index}")
        self._delete_if_present(keyring, manifest_reference)
        # Also clean up a legacy single-item credential if one exists.
        self._delete_if_present(keyring, reference)

    @staticmethod
    def _delete_if_present(keyring, reference: str) -> None:
        try:
            keyring.delete_password(KeyringCredentialStore.SERVICE, reference)
        except keyring.errors.PasswordDeleteError:
            return
