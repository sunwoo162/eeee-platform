"""Gleave Desktop client, session, and presentation layer."""

from app.desktop.client import ApiError, DesktopApiClient, PetApiClient
from app.desktop.chat_window import AssistantChatWindow
from app.desktop.presentation import BubbleGeometry, BubbleLayout, ConversationPresentation
from app.desktop.session import ConversationSession, DesktopSession
from app.desktop.window import DesktopWindow, PetWindow

__all__ = [
    "ApiError",
    "DesktopApiClient",
    "DesktopSession",
    "ConversationSession",
    "ConversationPresentation",
    "BubbleGeometry",
    "BubbleLayout",
    "DesktopWindow",
    "PetApiClient",
    "PetWindow",
    "AssistantChatWindow",
]
