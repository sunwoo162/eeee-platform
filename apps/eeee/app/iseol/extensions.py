"""Lazy, metadata-only extension registry for the native ISEOL runtime."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ExtensionKind = Literal["domain", "connector", "provisioner", "worker", "validator"]
SideEffectLevel = Literal["none", "local_write", "external_write"]


class ExtensionManifest(BaseModel):
    """Serializable description of an extension, without loading its code."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    kind: ExtensionKind
    capabilities: list[str] = Field(default_factory=list)
    required_connectors: list[str] = Field(default_factory=list, alias="requiredConnectors")
    side_effect_level: SideEffectLevel = Field(default="none", alias="sideEffectLevel")
    enabled: bool = True


class ExtensionRegistry:
    """Capability-scoped registry; registration never imports or runs an extension."""

    def __init__(self) -> None:
        self._manifests: dict[tuple[str, str], ExtensionManifest] = {}

    def register(self, manifest: ExtensionManifest) -> None:
        key = (manifest.id, manifest.version)
        previous = self._manifests.get(key)
        if previous is None:
            self._manifests[key] = manifest
            return
        if previous != manifest:
            raise ValueError(
                f"conflicting extension definition for {manifest.id}@{manifest.version}"
            )

    def select(self, capability_ids: list[str] | tuple[str, ...] | set[str]) -> list[ExtensionManifest]:
        requested = set(capability_ids)
        if not requested:
            return []
        selected: list[ExtensionManifest] = []
        seen_ids: set[str] = set()
        for manifest in self._manifests.values():
            if not manifest.enabled or not requested.intersection(manifest.capabilities):
                continue
            if manifest.id in seen_ids:
                continue
            selected.append(manifest)
            seen_ids.add(manifest.id)
        return selected

    def missing(self, required_ids: list[str] | tuple[str, ...] | set[str]) -> list[str]:
        available = {
            capability
            for manifest in self._manifests.values()
            if manifest.enabled
            for capability in manifest.capabilities
        }
        return [capability for capability in required_ids if capability not in available]
