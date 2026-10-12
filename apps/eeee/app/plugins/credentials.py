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
        keyring.set_password(self.SERVICE, reference, value)
        return reference

    def get(self, reference: str) -> str | None:
        keyring = self._module()
        return keyring.get_password(self.SERVICE, reference)

    def delete(self, reference: str) -> None:
        keyring = self._module()

        try:
            keyring.delete_password(self.SERVICE, reference)
        except keyring.errors.PasswordDeleteError:
            return
