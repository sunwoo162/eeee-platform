"""Workspace folders: local-only, owner-scoped MVP API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.routes import _plugin_user_id
from app.chat_scopes.store import WorkspaceStore
from app.conversations.store import ConversationStore


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "personal"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ProjectConversationCreate(BaseModel):
    title: str = Field(default="New chat", max_length=120)


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    source_message_id: str | None = None


class MemoryUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(alias="expectedVersion", ge=1)


def build_workspace_router(
    workspaces: WorkspaceStore, conversations: ConversationStore,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def principal(request: Request) -> str:
        # This is the existing LOCAL desktop identity contract, not OAuth.
        # Do NOT expose team membership editing until authenticated principals exist.
        return _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))

    def call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/workspaces", status_code=status.HTTP_201_CREATED)
    def create_workspace(body: WorkspaceCreate, request: Request) -> dict:
        return call(workspaces.create_workspace, body.name, body.kind, user_id=principal(request))

    @router.get("/workspaces")
    def list_workspaces(request: Request) -> dict:
        return {"items": workspaces.list_workspaces(user_id=principal(request))}

    @router.post("/workspaces/{workspace_id}/projects", status_code=status.HTTP_201_CREATED)
    def create_project(workspace_id: str, body: ProjectCreate, request: Request) -> dict:
        return call(workspaces.create_project, workspace_id, body.name, user_id=principal(request))

    @router.get("/workspaces/{workspace_id}/projects")
    def list_projects(workspace_id: str, request: Request) -> dict:
        return {"items": call(workspaces.list_projects, workspace_id, user_id=principal(request))}

    @router.post("/projects/{project_id}/conversations", status_code=status.HTTP_201_CREATED)
    def new_project_chat(project_id: str, body: ProjectConversationCreate, request: Request) -> dict:
        user_id = principal(request)
        # Check write permission before creating the conversation.
        call(workspaces.require_project_editor, project_id, user_id=user_id)
        chat = conversations.create_conversation(body.title, user_id=user_id)
        call(workspaces.link_conversation, project_id, chat.id, user_id=user_id)
        return chat.model_dump(mode="json") | {"projectId": project_id}

    @router.put("/projects/{project_id}/conversations/{conversation_id}")
    def move_chat(project_id: str, conversation_id: str, request: Request) -> dict:
        call(workspaces.link_conversation, project_id, conversation_id, user_id=principal(request))
        return {"conversationId": conversation_id, "projectId": project_id}

    @router.delete("/conversations/{conversation_id}/project")
    def unassign_chat(conversation_id: str, request: Request) -> dict:
        call(workspaces.unlink_conversation, conversation_id, user_id=principal(request))
        return {"conversationId": conversation_id, "projectId": None}

    @router.get("/projects/{project_id}/conversations")
    def list_chats(project_id: str, request: Request) -> dict:
        return {"items": call(workspaces.list_conversations, project_id, user_id=principal(request))}

    @router.get("/conversations/{conversation_id}/project")
    def conversation_project(conversation_id: str, request: Request) -> dict:
        user_id = principal(request)
        call(conversations.get_conversation, conversation_id, user_id=user_id)
        return {"project": workspaces.project_for_conversation(conversation_id, user_id=user_id)}

    @router.post("/projects/{project_id}/memories", status_code=status.HTTP_201_CREATED)
    def add_project_memory(project_id: str, body: MemoryCreate, request: Request) -> dict:
        return call(
            workspaces.add_memory, project_id, body.content,
            user_id=principal(request), source_message_id=body.source_message_id,
        )

    @router.get("/projects/{project_id}/memories")
    def list_project_memories(project_id: str, request: Request) -> dict:
        return {"items": call(workspaces.list_memories, project_id, user_id=principal(request))}

    @router.get("/projects/{project_id}/memories/{memory_id}/history")
    def memory_history(project_id: str, memory_id: str, request: Request) -> dict:
        return call(workspaces.memory_history, project_id, memory_id, user_id=principal(request))

    @router.put("/projects/{project_id}/memories/{memory_id}")
    def update_memory(project_id: str, memory_id: str, body: MemoryUpdate, request: Request) -> dict:
        return call(
            workspaces.update_memory, project_id, memory_id, body.content,
            expected_version=body.expected_version, user_id=principal(request),
        )

    @router.delete("/projects/{project_id}/memories/{memory_id}")
    def revoke_project_memory(project_id: str, memory_id: str, request: Request) -> dict:
        call(workspaces.revoke_memory, project_id, memory_id, user_id=principal(request))
        return {"revoked": True}

    return router
