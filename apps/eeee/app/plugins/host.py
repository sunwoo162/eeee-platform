"""Isolated local plugin lifecycle and subprocess transport."""

import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from app.contracts import ApprovalState, ExecutionEnvelope, ExecutionError, ExecutionStatus, SideEffectLevel
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

    def invoke(
        self, plugin_id: str, action: str, value: dict[str, object], *, approved: bool = False,
        execution_id: str | None = None,
    ) -> ExecutionEnvelope:
        registration = self.registrations.get(plugin_id)
        manifest = self._manifest(plugin_id, registration.manifest)
        selected = next((item for item in manifest.actions if item.id == action), None)
        side_effect_level = selected.side_effect_level if selected is not None else SideEffectLevel.NONE
        requires_approval = side_effect_level == SideEffectLevel.EXTERNAL
        expected_input = {"action": action, "input": value}
        running: ExecutionEnvelope | None = None
        if approved and requires_approval:
            if not execution_id:
                raise ValueError("execution_id is required to approve an external plugin action")
            envelope = self.executions.get(execution_id)
            if envelope.capability_id != f"plugin:{plugin_id}" or dict(envelope.input) != expected_input:
                raise ValueError("approval target does not match the requested plugin action")
            if envelope.status != ExecutionStatus.AWAITING_APPROVAL:
                if envelope.status in {ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED}:
                    return envelope
                raise ValueError("plugin execution is not awaiting approval")
        else:
            if execution_id:
                raise ValueError("execution_id can only be used to approve an external plugin action")
            envelope = ExecutionEnvelope(
                execution_id=f"plugin-execution-{uuid4().hex}", request_id=f"plugin-request-{uuid4().hex}",
                capability_id=f"plugin:{plugin_id}", tool_id=plugin_id, actor="EEEE",
                input=expected_input,
                side_effect_level=side_effect_level,
                required_approval=requires_approval,
                approval_state=(
                    ApprovalState.APPROVED if approved else ApprovalState.AWAITING_APPROVAL
                ) if requires_approval else ApprovalState.NOT_REQUIRED,
            )
            self.executions.save(envelope)
        try:
            if registration.status == "paused":
                raise PermissionError("plugin is paused")
            if registration.status != "connected":
                raise PermissionError("plugin is not connected")
            if selected is None:
                raise ValueError(f"unknown plugin action: {action}")
            if requires_approval and not approved:
                awaiting = envelope.transition(
                    ExecutionStatus.AWAITING_APPROVAL,
                    approval_state=ApprovalState.AWAITING_APPROVAL,
                )
                self.executions.save(awaiting)
                return awaiting
            if requires_approval:
                running = self.executions.claim_approval(envelope.execution_id)
            else:
                running = envelope.transition(
                    ExecutionStatus.RUNNING,
                    approval_state=ApprovalState.NOT_REQUIRED,
                )
            self.executions.save(running)
            output = self._call(manifest, action, value, plugin_id)
            completed = running.transition(ExecutionStatus.COMPLETED, output=output)
            self.executions.save(completed)
            return completed
        except Exception as exc:
            failed = running or envelope
            error = ExecutionError(code="plugin_failed", message=str(exc) or type(exc).__name__)
            if approved and requires_approval and running is None:
                latest = self.executions.get(envelope.execution_id)
                if latest.status != ExecutionStatus.AWAITING_APPROVAL:
                    return latest
            if failed.status in {ExecutionStatus.QUEUED, ExecutionStatus.AWAITING_APPROVAL}:
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

    def _manifest(self, plugin_id: str, data: dict) -> PluginManifest:
        return self._manifests.get(plugin_id) or PluginManifest.model_validate(data)

    def _health_probe(self, manifest: PluginManifest) -> PluginHealth:
        try:
            self._call(manifest, "__health__", {}, manifest.id)
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
