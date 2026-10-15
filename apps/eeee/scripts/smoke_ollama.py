from __future__ import annotations

import json
import sys
from dataclasses import asdict

from app.agent.ollama_runtime import OllamaRuntime
from app.config import Settings


def main() -> int:
    settings = Settings()
    runtime = OllamaRuntime(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        connect_timeout_seconds=settings.ollama_connect_timeout_seconds,
        generation_timeout_seconds=settings.ollama_generation_timeout_seconds,
        context_tokens=settings.ollama_context_tokens,
    )
    status = runtime.status()
    print(json.dumps(asdict(status), ensure_ascii=False))
    if status.status == "ready":
        return 0
    print(f"blocked: Ollama status is {status.status}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
