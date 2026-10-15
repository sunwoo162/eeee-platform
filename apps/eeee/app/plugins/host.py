"""Isolated local plugin lifecycle and subprocess transport."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from app.contracts import ExecutionEnvelope, ExecutionError, ExecutionStatus
from app.assistant.models import CapabilityDescriptor
from app.plugins.manifest import discover_manifest
from app.plugins.models import PluginHealth, PluginManifest
from app.plugins.protocol import request, validate_response
from app.runtime.store import ExecutionStore, PluginRegistrationStore


class PluginHost:
    def __init__(self, store, *, allowed_scope_ids: set[str] | None = None,
                 execution_store: ExecutionStore | None = None, timeout_seconds: float = 10.0) -> None:
        self.store = store
        self.registrations = PluginRegistrationStore(store)
        self.executions = execution_store or ExecutionStore(store)
        self.allowed_scope_ids = allowed_scope_ids
        self.timeout_seconds = timeout_seconds
        self._manifests: dict[str, PluginManifest] = {}
        self._sources: dict[str, Path | None] = {}

    def discover(self, source) -> PluginManifest:
        manifest = discover_manifest(source)
        self._manifests[manifest.id] = manifest
        self._sources[manifest.id] = Path(source).parent if isinstance(source, (str, Path)) else None
        return manifest

    def register(self, manifest: PluginManifest):
        self._manifests[manifest.id] = manifest
        return self.registrations.register(manifest)

    def connect(self, plugin_id: str, approval: bool):
        registration = self.registrations.get(plugin_id)
        manifest = self._manifest(plugin_id, registration.manifest)
        requested = {scope.id for permission in manifest.permissions for scope in [permission]}
        allowed = requested if self.allowed_scope_ids is None else requested & self.allowed_scope_ids
        if not approval or allowed != requested:
            self.registrations.set_status(plugin_id, "disabled")
            raise PermissionError("plugin permission approval was denied")
        health = self._health_probe(manifest)
        if health.status != "healthy":
            self.registrations.set_status(plugin_id, "failed")
            raise RuntimeError(health.reason)
        return self.registrations.set_status(plugin_id, "connected")

    def invoke(self, plugin_id: str, action: str, value: dict[str, object]) -> ExecutionEnvelope:
        registration = self.registrations.get(plugin_id)
        manifest = self._manifest(plugin_id, registration.manifest)
        envelope = ExecutionEnvelope(
            execution_id=f"plugin-execution-{uuid4().hex}", request_id=f"plugin-request-{uuid4().hex}",
            capability_id=f"plugin:{plugin_id}", tool_id=plugin_id, actor="EEEE",
            input={"action": action, "input": value},
        )
        self.executions.save(envelope)
        running: ExecutionEnvelope | None = None
        try:
            if registration.status == "paused":
                raise PermissionError("plugin is paused")
            if registration.status != "connected":
                raise PermissionError("plugin is not connected")
            selected = next((item for item in manifest.actions if item.id == action), None)
            if selected is None:
                raise ValueError(f"unknown plugin action: {action}")
            running = envelope.transition(ExecutionStatus.RUNNING)
            self.executions.save(running)
            output = self._call(manifest, action, value, plugin_id)
            completed = running.transition(ExecutionStatus.COMPLETED, output=output)
            self.executions.save(completed)
            return completed
        except Exception as exc:
            failed = running or envelope
            error = ExecutionError(code="plugin_failed", message=str(exc) or type(exc).__name__)
            if failed.status == ExecutionStatus.QUEUED:
                failed = failed.transition(ExecutionStatus.BLOCKED, error=error)
            else:
                failed = failed.transition(ExecutionStatus.FAILED, error=error)
            self.executions.save(failed)
            return failed

    def health(self, plugin_id: str) -> PluginHealth:
        registration = self.registrations.get(plugin_id)
        return self._health_probe(self._manifest(plugin_id, registration.manifest))

    def disconnect(self, plugin_id: str):
        return self.registrations.set_status(plugin_id, "available")

    def pause(self, plugin_id: str):
        registration = self.registrations.get(plugin_id)
        if registration.status != "connected":
            raise PermissionError("only a connected plugin can be paused")
        return self.registrations.set_status(plugin_id, "paused")

    def resume(self, plugin_id: str):
        registration = self.registrations.get(plugin_id)
        if registration.status != "paused":
            raise PermissionError("only a paused plugin can be resumed")
        health = self._health_probe(self._manifest(plugin_id, registration.manifest))
        if health.status != "healthy":
            self.registrations.set_status(plugin_id, "failed")
            raise RuntimeError(health.reason)
        return self.registrations.set_status(plugin_id, "connected")

    def remove(self, plugin_id: str) -> None:
        self.registrations.remove(plugin_id)
        self._manifests.pop(plugin_id, None)
        self._sources.pop(plugin_id, None)

    def list(self):
        return self.registrations.list()

    def routing_capabilities(self) -> list[CapabilityDescriptor]:
        """Return only capabilities safe for automatic EEEE routing right now."""
        projected: list[CapabilityDescriptor] = []
        for registration in self.registrations.list(status="connected"):
            manifest = self._manifest(registration.plugin_id, registration.manifest)
            health = self._health_probe(manifest)
            if health.status != "healthy":
                if registration.status == "connected":
                    self.registrations.set_status(registration.plugin_id, "failed")
                continue
            for capability in manifest.capabilities:
                projected.append(CapabilityDescriptor(
                    id=f"plugin:{manifest.id}:{capability.id}",
                    version=capability.version,
                    display_name=capability.display_name,
                    intents=capability.intents,
                    trigger_phrases=capability.trigger_phrases,
                    required_connectors=[f"plugin:{manifest.id}"],
                    side_effect_level=capability.side_effect_level,
                    approval_level=capability.approval_level,
                    claim_latch_policy="claimlatch-v0.2.0",
                    memory_writable=False,
                ))
        return projected

    def invoke_capability(self, capability_id: str, value: dict[str, object]) -> tuple[str, ExecutionEnvelope]:
        """Resolve a projected capability and invoke its declared plugin action."""
        prefix = "plugin:"
        if not capability_id.startswith(prefix):
            raise KeyError(f"Not a plugin capability: {capability_id}")
        _, plugin_id, manifest_capability_id = capability_id.split(":", 2)
        registration = self.registrations.get(plugin_id)
        manifest = self._manifest(plugin_id, registration.manifest)
        capability = next((item for item in manifest.capabilities if item.id == manifest_capability_id), None)
        if capability is None:
            raise KeyError(f"Plugin capability not found: {capability_id}")
        if not any(item.id == capability_id for item in self.routing_capabilities()):
            raise PermissionError("plugin capability is not connected and healthy")
        return plugin_id, self.invoke(plugin_id, capability.action_id, value)

    def _manifest(self, plugin_id: str, data: dict) -> PluginManifest:
        return self._manifests.get(plugin_id) or PluginManifest.model_validate(data)

    def _health_probe(self, manifest: PluginManifest) -> PluginHealth:
        try:
            self._call(manifest, manifest.health.action, {}, manifest.id)
        except Exception as exc:
            return PluginHealth(plugin_id=manifest.id, status="unhealthy", reason=str(exc))
        return PluginHealth(plugin_id=manifest.id, status="healthy", reason="health check passed")

    def _call(self, manifest: PluginManifest, action: str, value: dict[str, object], plugin_id: str) -> dict[str, object]:
        command = list(manifest.command)
        if command and command[0].casefold() in {"python", "python.exe"}:
            command[0] = sys.executable
        source_dir = self._sources.get(plugin_id)
        if source_dir is not None:
            command = [str(source_dir / item) if index > 0 and not Path(item).is_absolute() else item
                       for index, item in enumerate(command)]
        correlation_id = uuid4().hex
        completed = subprocess.run(
            command, input=json.dumps(request(correlation_id, action, value)) + "\n",
            text=True, capture_output=True, timeout=self.timeout_seconds, cwd=source_dir,
            shell=False, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"plugin process exited with code {completed.returncode}")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("plugin returned no response")
        response = validate_response(json.loads(lines[-1]), correlation_id)
        if response["status"] == "failed":
            raise RuntimeError(str(response["output"].get("error", "plugin reported failure")))
        return dict(response["output"])
