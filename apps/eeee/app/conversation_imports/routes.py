"""Local, explicit preview/confirm endpoints for private transcript imports."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.routes import _plugin_user_id
from app.conversation_imports.candidates import MemoryCandidates
from app.conversation_imports.parser import parse_export
from app.conversation_imports.service import ConversationImportService
from app.conversation_imports.staging import (
    MAX_ARCHIVE_BYTES,
    ImportStaging,
    preview_page,
)


class ExportPayload(BaseModel):
    provider: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1, max_length=8_000_000)


class ReviewPayload(BaseModel):
    decision: str
    content: str | None = Field(default=None, max_length=2000)


class StagedCommitPayload(BaseModel):
    selected_indexes: list[int] = Field(alias="selectedIndexes", min_length=1, max_length=20)
    project_id: str | None = Field(default=None, alias="projectId")


class CommitPayload(ExportPayload):
    selected_indexes: list[int] = Field(alias="selectedIndexes", min_length=1, max_length=20)
    project_id: str | None = Field(default=None, alias="projectId")


def build_import_router(
    service: ConversationImportService, *, staging: ImportStaging | None = None,
) -> APIRouter:
    staging = staging or ImportStaging()
    candidates = MemoryCandidates(service.projects)
    router = APIRouter(prefix="/v1/imports")

    def principal(request: Request) -> str:
        host = request.client.host if request.client is not None else ""
        if host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="Import is available only on the local device")
        origin = request.headers.get("origin")
        if origin and not origin.startswith((
            "http://127.0.0.1:", "http://localhost:", "http://[::1]:",
        )):
            raise HTTPException(status_code=403, detail="Untrusted import origin")
        return _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))

    @router.post("/preview")
    def preview(body: ExportPayload, request: Request) -> dict:
        principal(request)
        try:
            items = parse_export(body.provider, body.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "items": [
                {
                    "index": i, "provider": item.provider, "title": item.title,
                    "messageCount": len(item.messages),
                    "excerpt": next((text[:160] for role, text in item.messages if role == "user"), ""),
                }
                for i, item in enumerate(items)
            ]
        }

    @router.post("/commit")
    def commit(body: CommitPayload, request: Request) -> dict:
        user = principal(request)
        try:
            items = parse_export(body.provider, body.content)
            return service.import_selected(
                items, body.selected_indexes, user_id=user, project_id=body.project_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/upload")
    async def upload(request: Request, provider: str = Query(), filename: str = Query()) -> dict:
        user = principal(request)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_ARCHIVE_BYTES:
                raise HTTPException(status_code=413, detail="Upload must be 64 MB or smaller")
            data.extend(chunk)
        try:
            session = staging.create(
                owner=user, provider=provider, data=bytes(data), filename=filename,
            )
            return preview_page(session)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/sessions/{session_id}")
    def staged_preview(
        session_id: str, request: Request,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=40, ge=1, le=50),
    ) -> dict:
        user = principal(request)
        try:
            return preview_page(staging.get(session_id, owner=user), offset=offset, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/sessions/{session_id}/commit")
    def staged_commit(session_id: str, body: StagedCommitPayload, request: Request) -> dict:
        user = principal(request)
        try:
            session = staging.get(session_id, owner=user)
            return service.import_selected(
                session.chats, body.selected_indexes, user_id=user,
                project_id=body.project_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/sessions/{session_id}")
    def discard_stage(session_id: str, request: Request) -> dict:
        user = principal(request)
        try:
            staging.release(session_id, owner=user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"released": True}

    @router.get("/projects/{project_id}/memory-candidates")
    def memory_candidates(project_id: str, request: Request) -> dict:
        user = principal(request)
        try:
            return {"items": candidates.list(project_id, user_id=user)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/projects/{project_id}/memory-candidates/{message_id}/review")
    def review_candidate(
        project_id: str, message_id: str, body: ReviewPayload, request: Request,
    ) -> dict:
        user = principal(request)
        try:
            return candidates.review(
                project_id, message_id, user_id=user,
                decision=body.decision, content=body.content,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/conversations/{conversation_id}/origin")
    def origin(conversation_id: str, request: Request) -> dict:
        user = principal(request)
        try:
            result = service.origin(conversation_id, user_id=user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"origin": result}

    return router
