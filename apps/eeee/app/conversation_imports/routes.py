"""Local, explicit preview/confirm endpoints for private transcript imports."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes import _plugin_user_id
from app.conversation_imports.parser import parse_export
from app.conversation_imports.service import ConversationImportService


class ExportPayload(BaseModel):
    provider: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1, max_length=8_000_000)


class CommitPayload(ExportPayload):
    selected_indexes: list[int] = Field(alias="selectedIndexes", min_length=1, max_length=20)
    project_id: str | None = Field(default=None, alias="projectId")


def build_import_router(service: ConversationImportService) -> APIRouter:
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

    @router.get("/conversations/{conversation_id}/origin")
    def origin(conversation_id: str, request: Request) -> dict:
        user = principal(request)
        try:
            result = service.origin(conversation_id, user_id=user)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"origin": result}

    return router
