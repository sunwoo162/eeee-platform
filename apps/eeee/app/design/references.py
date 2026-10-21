"""Collect design references without copying unprovenanced assets."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.design.tokens import DesignTokenExtractor
    from app.design.visual_verify import VisualReport, VisualVerifier
    from app.storage.sqlite import SQLiteStore


class DesignReference(BaseModel):
    source_url: str
    source_kind: str
    title: str
    license_name: str | None
    license_url: str | None
    captured_at: datetime
    allowed_uses: list[str]
    notes: str


class ReferencePack(BaseModel):
    references: list[DesignReference] = Field(default_factory=list)
    layout_patterns: list[str] = Field(default_factory=list)
    component_patterns: list[str] = Field(default_factory=list)
    tokens: dict[str, object] = Field(default_factory=dict)
    attribution: list[str] = Field(default_factory=list)


class ReferenceCollector:
    """Record user-provided source metadata and default to reference-only use."""

    def __init__(self, fetcher: Callable[[str], Mapping[str, object]] | None = None) -> None:
        self.fetcher = fetcher

    def collect(
        self, urls: list[str], keywords: list[str], target_type: str
    ) -> ReferencePack:
        references: list[DesignReference] = []
        attribution: list[str] = []
        for url in urls:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Reference URL must be http(s): {url}")
            metadata = dict(self.fetcher(url)) if self.fetcher else {}
            title = _string_or_default(metadata.get("title"), url)
            source_kind = _string_or_default(metadata.get("source_kind"), "user_url")
            license_name = _optional_string(metadata.get("license_name"))
            license_url = _optional_string(metadata.get("license_url"))
            supplied_notes = _optional_string(metadata.get("notes"))
            if license_name:
                allowed_uses = ["reference_only", "derived_tokens"]
                notes = supplied_notes or "Licensed source recorded for inspiration and derived tokens."
                attribution.append(f"{title} — {url} ({license_name})")
            else:
                allowed_uses = ["reference_only"]
                notes = supplied_notes or "License is unknown; direct asset copying is disabled."
                attribution.append(f"{title} — {url} (reference_only; license unknown)")
            references.append(
                DesignReference(
                    source_url=url,
                    source_kind=source_kind,
                    title=title,
                    license_name=license_name,
                    license_url=license_url,
                    captured_at=datetime.now(timezone.utc),
                    allowed_uses=allowed_uses,
                    notes=notes,
                )
            )
        return ReferencePack(
            references=references,
            layout_patterns=[f"{target_type} layout", *[f"{keyword} layout" for keyword in keywords]],
            component_patterns=[f"{keyword} component" for keyword in keywords],
            attribution=attribution,
        )


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


class DesignService:
    """Keep reference packs addressable for the local API process."""

    def __init__(
        self,
        collector: ReferenceCollector | None = None,
        extractor: DesignTokenExtractor | None = None,
        visual_verifier: VisualVerifier | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        if extractor is None:
            from app.design.tokens import DesignTokenExtractor as TokenExtractor

            extractor = TokenExtractor()
        if visual_verifier is None:
            from app.design.visual_verify import VisualVerifier as ScreenshotVerifier

            visual_verifier = ScreenshotVerifier()
        self.collector = collector or ReferenceCollector()
        self.extractor = extractor
        self.visual_verifier = visual_verifier
        self.store = store
        self._packs: dict[str, tuple[str, ReferencePack, dict[str, object]]] = {}
        self._verifications: dict[str, tuple[str, str, str, VisualReport]] = {}

    def create(
        self, urls: list[str], keywords: list[str], target_type: str,
        *, user_id: str = "local-user",
    ) -> tuple[str, ReferencePack, dict[str, object]]:
        pack = self.collector.collect(urls, keywords, target_type)
        tokens = self.extractor.extract(pack)
        pack_id = str(uuid4())
        if self.store is not None:
            self.store.save_design_pack(pack_id, pack, tokens, user_id=user_id)
        else:
            self._packs[pack_id] = (user_id, pack, tokens)
        return pack_id, pack, tokens

    def get(
        self, pack_id: str, *, user_id: str = "local-user"
    ) -> tuple[ReferencePack, dict[str, object]]:
        if self.store is not None:
            return self.store.get_design_pack(pack_id, user_id=user_id)
        try:
            owner, pack, tokens = self._packs[pack_id]
        except KeyError as exc:
            raise KeyError(f"Design reference pack not found: {pack_id}") from exc
        if owner != user_id:
            raise KeyError(f"Design reference pack not found: {pack_id}")
        return pack, tokens

    def verify(
        self, url: str, baseline: str, *, user_id: str = "local-user"
    ) -> tuple[str, VisualReport]:
        report = self.visual_verifier.compare(url, Path(baseline))
        verification_id = str(uuid4())
        if self.store is not None:
            self.store.save_visual_verification(
                verification_id, url, baseline, report, user_id=user_id
            )
        else:
            self._verifications[verification_id] = (user_id, url, baseline, report)
        return verification_id, report

    def get_verification(
        self, verification_id: str, *, user_id: str = "local-user"
    ) -> tuple[str, str, VisualReport]:
        if self.store is not None:
            return self.store.get_visual_verification(verification_id, user_id=user_id)
        try:
            owner, url, baseline, report = self._verifications[verification_id]
        except KeyError as exc:
            raise KeyError(f"Visual verification not found: {verification_id}") from exc
        if owner != user_id:
            raise KeyError(f"Visual verification not found: {verification_id}")
        return url, baseline, report
