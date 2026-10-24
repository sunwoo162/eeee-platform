from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.agent.ollama_runtime import OllamaRuntime
from app.agent.personal_llm_runtime import PersonalLlmRuntime
from app.api.routes import _plugin_user_id
from app.conversations.models import RequestState
from app.conversations.providers import ConversationProviderSelection
from app.conversations.service import ConversationService, CoreShuttingDownError


class ConversationCreatePayload(BaseModel):
    title: str = "새 대화"


class TurnPayload(BaseModel):
    client_message_id: str = Field(alias="clientMessageId", min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50_000)

    model_config = {"populate_by_name": True}


class TurnResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    state: str

    model_config = {"populate_by_name": True}


def _conversation_payload(conversation: Any) -> dict[str, object]:
    return conversation.model_dump(mode="json")


def _message_payload(message: Any) -> dict[str, object]:
    return message.model_dump(mode="json", by_alias=True)


def _event_payload(event: Any) -> dict[str, object]:
    return {
        "eventId": event.event_id,
        "requestId": event.request_id,
        "sequence": event.sequence,
        "eventType": event.event_type,
        "payload": event.payload,
        "createdAt": event.created_at.isoformat(),
    }


def build_conversation_router(
    service: ConversationService,
    *,
    ollama: OllamaRuntime,
    personal_llm: PersonalLlmRuntime | None = None,
    provider_selection: ConversationProviderSelection | None = None,
    web_configured: bool = False,
    web_status: str | None = None,
    web_status_provider: Callable[[], Any] | None = None,
    lifecycle: Any | None = None,
    capabilities: Any | None = None,
    core_version: str = "0.1.0",
    schema_version: int = 1,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/runtime")
    def runtime_status() -> dict[str, object]:
        provider_status = ollama.status()
        personal_status = personal_llm.status() if personal_llm is not None else None
        current_web_status = _current_web_status(web_status, web_status_provider)
        lifecycle_status = lifecycle.state.value if lifecycle is not None else "ready"
        # Test clients created without a lifespan context retain the historical
        # ready response; production servers enter the lifespan and report the
        # concrete running/draining state.
        if lifecycle_status == "stopped":
            lifecycle_status = "ready"
        core_status = {
            "status": lifecycle_status,
            "version": core_version,
            "schemaVersion": schema_version,
        }
        selected = provider_selection or ConversationProviderSelection(
            provider=service.provider,
            provider_name="injected",
            status="configured",
            reason="conversation_provider_injected",
        )
        selected_status = selected.status
        if selected.provider_name == "chatgpt_web":
            selected_status = "configured" if current_web_status == "ready" else "unavailable"
        elif selected.provider_name == "ollama":
            selected_status = (
                "configured" if provider_status.status == "ready" else provider_status.status
            )
        elif selected.provider_name == "personal_llm":
            selected_status = (
                "configured"
                if personal_status is not None and personal_status.status == "ready"
                else personal_status.status if personal_status is not None else "unavailable"
            )
        selected_model = selected.model
        if selected.provider_name == "personal_llm" and personal_status is not None:
            selected_model = personal_status.model or selected.model
        fallback = selected.fallback
        if fallback is not None:
            fallback = {
                **fallback,
                "active": selected_status != "configured",
            }
        return {
            "core": core_status,
            "ollama": {
                "status": provider_status.status,
                "model": provider_status.model,
                "errorCode": provider_status.error_code,
                "message": provider_status.message,
            },
            "conversationProvider": {
                "name": selected.provider_name,
                "status": selected_status,
                "model": selected_model,
                "reason": selected.reason,
                "fallback": fallback,
            },
            "providers": {
                "ollama": {
                    "status": provider_status.status,
                    "model": provider_status.model,
                },
                "chatgpt_web": {
                    "status": current_web_status or ("configured" if web_configured else "not_configured"),
                },
                "personal_llm": {
                    "status": personal_status.status if personal_status is not None else "not_configured",
                    "model": personal_status.model if personal_status is not None else None,
                },
            },
            "capabilities": capabilities.snapshot() if capabilities is not None else {},
        }

    @router.post("/conversations", status_code=status.HTTP_201_CREATED)
    def create_conversation(
        payload: ConversationCreatePayload, request: Request
    ) -> dict[str, object]:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return _conversation_payload(
            service.store.create_conversation(payload.title, user_id=user_id)
        )

    @router.get("/conversations")
    def list_conversations(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, object]:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        conversations = service.store.list_conversations(limit=limit, user_id=user_id)
        return {
            "items": [
                {
                    **_conversation_payload(item),
                    "messageCount": service.store.message_count(item.id),
                }
                for item in conversations
            ],
            "nextCursor": None,
        }

    @router.get("/conversations/{conversation_id}/messages")
    def get_messages(
        conversation_id: str,
        request: Request,
        after_sequence: int = Query(default=0, alias="afterSequence", ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, object]:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            service.store.get_conversation(conversation_id, user_id=user_id)
            messages = service.store.get_messages(
                conversation_id,
                after_sequence=after_sequence,
                limit=limit,
                user_id=user_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "items": [_message_payload(item) for item in messages],
            "nextCursor": messages[-1].sequence if len(messages) == limit else None,
        }

    @router.post("/conversations/{conversation_id}/turns")
    def submit_turn(
        conversation_id: str, payload: TurnPayload, request: Request
    ) -> JSONResponse:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            service.store.get_conversation(conversation_id, user_id=user_id)
            request, created = service.prepare_turn(
                conversation_id,
                content=payload.content,
                client_message_id=payload.client_message_id,
                user_id=user_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CoreShuttingDownError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if created:
            threading.Thread(
                target=service.consume_request,
                args=(request.id,),
                name=f"eeee-conversation-{request.id}",
                daemon=True,
            ).start()
        response = TurnResponse(requestId=request.id, state=request.state.value)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
            content=response.model_dump(mode="json", by_alias=True),
        )

    @router.get("/requests/{request_id}/events")
    def request_events(
        request_id: str,
        request: Request,
        after_sequence: int = Query(default=0, alias="afterSequence", ge=0),
        timeout_seconds: float = Query(default=30.0, ge=0.1, le=60.0, alias="timeoutSeconds"),
    ) -> StreamingResponse:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            service.store.get_request_for_user(request_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        def stream() -> Iterator[str]:
            cursor = after_sequence
            deadline = time.monotonic() + timeout_seconds
            terminal = {
                RequestState.COMPLETED,
                RequestState.FAILED,
                RequestState.CANCELLED,
                RequestState.INTERRUPTED,
            }
            while time.monotonic() < deadline:
                events = service.store.events_after(request_id, after_sequence=cursor)
                for event in events:
                    cursor = event.sequence
                    yield f"data: {json.dumps(_event_payload(event), ensure_ascii=False)}\n\n"
                current_request = service.store.get_request_for_user(
                    request_id, user_id=user_id
                )
                if current_request.state in terminal and not events:
                    break
                time.sleep(0.02)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/requests/{request_id}/cancel")
    def cancel_request(request_id: str, request: Request) -> TurnResponse:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            service.store.get_request_for_user(request_id, user_id=user_id)
            request = service.cancel_request(request_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return TurnResponse(requestId=request.id, state=request.state.value)

    @router.post("/requests/{request_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    def retry_request(request_id: str, request: Request) -> TurnResponse:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            service.store.get_request_for_user(request_id, user_id=user_id)
            request = service.retry_request(request_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        threading.Thread(
            target=service.consume_request,
            args=(request.id,),
            name=f"eeee-conversation-retry-{request.id}",
            daemon=True,
        ).start()
        return TurnResponse(requestId=request.id, state=request.state.value)

    return router


def _current_web_status(
    configured_status: str | None,
    status_provider: Callable[[], Any] | None,
) -> str | None:
    if status_provider is None:
        return configured_status
    try:
        status = status_provider()
    except Exception:
        return "unavailable"
    return getattr(status, "status", status) or "unavailable"
