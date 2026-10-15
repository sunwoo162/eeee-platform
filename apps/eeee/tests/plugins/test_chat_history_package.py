import json
from pathlib import Path


def test_chat_history_plugin_is_a_separate_installable_package() -> None:
    package = Path(__file__).parents[2] / "plugins" / "eeee_chat_history"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "eeee-chat-history"
    assert manifest["entrypoint"] == "main.py"
    assert (package / manifest["entrypoint"]).is_file()
    assert (package / "window.py").is_file()
