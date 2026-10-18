import json
from pathlib import Path


PACKAGE = Path(__file__).parents[2] / "plugins" / "eeee_chat_history"


def test_bundled_chat_history_package_has_a_strict_manifest_and_entrypoint() -> None:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))

    assert manifest == {
        "id": "eeee-chat-history",
        "name": "EEEE 채팅 기록",
        "version": "1.0.0",
        "entrypoint": "main.py",
        "permissions": ["conversation.read", "conversation.write"],
    }
    assert (PACKAGE / "main.py").is_file()
    assert (PACKAGE / "window.py").is_file()
