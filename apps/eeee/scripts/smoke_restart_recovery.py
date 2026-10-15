from __future__ import annotations

import json
import gc
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversations.models import MessageRole, MessageStatus, RequestState
from app.conversations.service import ConversationService
from app.conversations.store import ConversationStore
from app.core.lifecycle import CoreLifecycle
from app.core.lock import ProcessLock
from app.storage.sqlite import SQLiteStore


class NoopProvider:
    def stream(self, messages, *, cancel_event=None):
        yield ""


def main() -> int:
    with TemporaryDirectory(prefix="eeee-recovery-", ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        sqlite_store = SQLiteStore(root / "state.sqlite3")
        sqlite_store.init()
        conversations = ConversationStore(sqlite_store)
        conversation = conversations.create_conversation()
        user = conversations.add_message(
            conversation.id,
            role=MessageRole.USER,
            content="재시작 복구",
            status=MessageStatus.COMPLETED,
            client_message_id="smoke-1",
        )
        request = conversations.create_request(conversation.id, user.id, "smoke-1")
        conversations.transition_request(request.id, RequestState.PERSISTED_USER_MESSAGE)
        conversations.transition_request(request.id, RequestState.CLASSIFIED)
        conversations.transition_request(request.id, RequestState.GENERATING)
        service = ConversationService(conversations, provider=NoopProvider())
        lifecycle = CoreLifecycle(
            sqlite_store,
            service,
            lock=ProcessLock(root / "core.lock"),
        )
        lifecycle.start()
        recovered = list(lifecycle.recovered_request_ids)
        lifecycle.stop()
        result = {
            "requestId": request.id,
            "recovered": recovered,
            "state": conversations.get_request(request.id).state.value,
        }
        lifecycle = None
        conversations = None
        sqlite_store = None
        gc.collect()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["state"] == "interrupted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
