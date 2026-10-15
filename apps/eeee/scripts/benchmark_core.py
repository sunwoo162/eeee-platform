from __future__ import annotations

import argparse
import gc
import json
import time
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("iterations must be positive")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark warm EEEE Core routes")
    parser.add_argument("--iterations", type=_positive_int, default=100)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="eeee-benchmark-", ignore_cleanup_errors=True) as directory:
        root = __import__("pathlib").Path(directory)
        app = create_app(Settings(data_dir=root / "data", workspace_root=root / "workspaces"))
        with TestClient(app) as client:
            client.get("/health")
            started = time.perf_counter()
            for _ in range(args.iterations):
                response = client.get("/health")
                response.raise_for_status()
            elapsed = time.perf_counter() - started
        client = None
        app = None
        gc.collect()
    result = {
        "route": "/health",
        "iterations": args.iterations,
        "elapsedSeconds": round(elapsed, 6),
        "averageMilliseconds": round(elapsed * 1000 / args.iterations, 4),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
