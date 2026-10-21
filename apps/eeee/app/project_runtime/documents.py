from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Protocol

from app.integrations.notion_client import NotionPageRef
from app.project_runtime.models import (
    ConnectorBinding,
    ProjectDocumentRecord,
    ProjectDocumentSyncResult,
    ProjectProfile,
)
from app.storage.sqlite import SQLiteStore
from app.trust.models import TrustCheck


class NotionDocumentAdapter(Protocol):
    def create_project_page(self, profile: ProjectProfile, lines: list[str]) -> NotionPageRef: ...

    def append_revision(self, page_id: str, revision: str, lines: list[str]) -> None: ...


class PluginPlatformNotionAdapter:
    """Use the connected Notion plugin for trusted project-document writes."""

    def __init__(self, platform: object, user_id: str = "local-user") -> None:
        self.platform = platform
        self.user_id = user_id

    def for_user(self, user_id: str) -> "PluginPlatformNotionAdapter":
        return PluginPlatformNotionAdapter(self.platform, user_id=user_id)

    def is_available(self) -> bool:
        connected = self.platform.connected_connector_ids(
            self.user_id,
            required_permissions={"notion": {"pages.write"}},
        )
        return "notion" in connected

    def create_project_page(self, profile: ProjectProfile, lines: list[str]) -> NotionPageRef:
        result = self.platform.invoke_connector_action(
            self.user_id,
            "notion",
            "create_project_page",
            {"profile": profile.model_dump(mode="json", by_alias=True), "lines": lines},
        )
        return _page_ref(result)

    def append_revision(self, page_id: str, revision: str, lines: list[str]) -> None:
        self.platform.invoke_connector_action(
            self.user_id,
            "notion",
            "append_revision",
            {"pageId": page_id, "revision": revision, "lines": lines},
        )


class ProjectDocumentService:
    """Synchronize a Project Runtime profile into Notion after trust verification."""

    def __init__(
        self,
        store: SQLiteStore,
        notion: NotionDocumentAdapter | None,
        trust_gate: object,
        event_publisher: Callable[[str, dict[str, object]], object] | None = None,
    ) -> None:
        self.store = store
        self.notion = notion
        self.trust_gate = trust_gate
        self.event_publisher = event_publisher

    def sync(self, profile: ProjectProfile, *, user_id: str = "local-user") -> ProjectDocumentSyncResult:
        notion = _adapter_for_user(self.notion, user_id)
        if notion is None or not _is_available(notion):
            result = ProjectDocumentSyncResult(
                status="awaiting_configuration",
                project_id=profile.project_id,
                provider="notion",
                revision=profile.project_revision,
                reason="Notion token and parent page are not configured",
            )
            self._publish(
                "project.document.awaiting_configuration", profile, result, user_id=user_id
            )
            return result

        lines = _document_lines(profile)
        content_hash = _content_hash(lines)
        existing = self._existing(profile.project_id)
        if existing is not None and existing.content_hash == content_hash:
            self._mark_connector_completed(profile, existing)
            result = ProjectDocumentSyncResult(
                status="unchanged",
                project_id=profile.project_id,
                provider="notion",
                revision=profile.project_revision,
                document=existing,
                reason="The same project revision is already synchronized",
            )
            self._publish("project.document.unchanged", profile, result, user_id=user_id)
            return result

        trust = self.trust_gate.verify_action(
            subject_id=f"{profile.project_id}:notion",
            project_id=profile.project_id,
            project_revision=profile.project_revision,
            action="notion.project_document.write",
            payload={"provider": "notion", "contentHash": content_hash},
        )
        if trust.decision != "PASS":
            result = ProjectDocumentSyncResult(
                status="blocked",
                project_id=profile.project_id,
                provider="notion",
                revision=profile.project_revision,
                document=existing,
                trust=trust,
                reason=trust.reason,
            )
            self._publish("project.document.blocked", profile, result, user_id=user_id)
            return result

        if existing is None:
            page = notion.create_project_page(profile, lines)
            document = _document_record(profile, page, content_hash)
        else:
            notion.append_revision(existing.external_id, profile.project_revision, lines)
            document = existing.model_copy(
                update={
                    "project_revision": profile.project_revision,
                    "content_hash": content_hash,
                    "synced_at": datetime.now(timezone.utc),
                }
            )
        self.store.save_project_document(document)
        self._mark_connector_completed(profile, document)
        result = ProjectDocumentSyncResult(
            status="synced",
            project_id=profile.project_id,
            provider="notion",
            revision=profile.project_revision,
            document=document,
            trust=trust,
        )
        self._publish("project.document.synced", profile, result, user_id=user_id)
        return result

    def _existing(self, project_id: str) -> ProjectDocumentRecord | None:
        try:
            return self.store.get_project_document(project_id, "notion")
        except KeyError:
            return None

    def _publish(
        self,
        kind: str,
        profile: ProjectProfile,
        result: ProjectDocumentSyncResult,
        *,
        user_id: str = "local-user",
    ) -> None:
        if self.event_publisher is not None:
            self.event_publisher(
                kind,
                {
                    "projectId": profile.project_id,
                    "projectRevision": profile.project_revision,
                    "provider": "notion",
                    "status": result.status,
                    "reason": result.reason,
                    "userId": user_id,
                },
            )

    def _mark_connector_completed(
        self, profile: ProjectProfile, document: ProjectDocumentRecord
    ) -> None:
        connectors = [
            binding.model_copy(
                update={
                    "state": "completed",
                    "external_ref": document.external_url or document.external_id,
                    "reason": None,
                }
            )
            if binding.connector_id == "notion"
            else binding
            for binding in profile.connectors
        ]
        if connectors != profile.connectors:
            self.store.save_project_profile(profile.model_copy(update={"connectors": connectors}))


def _document_record(
    profile: ProjectProfile, page: NotionPageRef, content_hash: str
) -> ProjectDocumentRecord:
    return ProjectDocumentRecord(
        project_id=profile.project_id,
        provider="notion",
        project_revision=profile.project_revision,
        external_id=page.id,
        external_url=page.url,
        content_hash=content_hash,
        synced_at=datetime.now(timezone.utc),
    )


def _page_ref(value: object) -> NotionPageRef:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"].strip():
        raise RuntimeError("Notion connector returned an invalid page reference")
    url = value.get("url")
    return NotionPageRef(id=value["id"], url=url if isinstance(url, str) else None)


def _is_available(adapter: object) -> bool:
    checker = getattr(adapter, "is_available", None)
    return bool(checker()) if callable(checker) else True


def _adapter_for_user(adapter: object | None, user_id: str) -> object | None:
    if adapter is None:
        return None
    factory = getattr(adapter, "for_user", None)
    return factory(user_id) if callable(factory) else adapter


def _document_lines(profile: ProjectProfile) -> list[str]:
    return [
        f"Goal: {profile.goal}",
        f"Project ID: {profile.project_id}",
        f"Revision: {profile.project_revision}",
        f"Workspace: {profile.workspace}",
        f"Scope: {', '.join(profile.scope) or 'not specified'}",
        f"Constraints: {', '.join(profile.constraints) or 'none'}",
        f"Acceptance criteria: {', '.join(profile.acceptance_criteria) or 'not specified'}",
        f"QA baselines: {', '.join(profile.qa_baseline_ids) or 'none'}",
    ]


def _content_hash(lines: list[str]) -> str:
    encoded = json.dumps(lines, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
