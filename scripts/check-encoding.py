"""Validate tracked text files against the repository UTF-8 policy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


TEXT_EXTENSIONS = {
    ".c", ".cpp", ".css", ".html", ".ini", ".js", ".json", ".md", ".mjs",
    ".ps1", ".psm1", ".py", ".pyi", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".txt", ".xml", ".yml", ".yaml",
}
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
MOJIBAKE_MARKERS = (
    "\u00c3", "\u00c2", "\u00e2\u20ac", "\u00f0\u0178", "\u00ef\u00bf\u00bd",
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True,
    )
    return [Path(item) for item in result.stdout.decode().split("\0") if item]


def main() -> int:
    failures: list[str] = []
    checked = 0
    for path in tracked_files():
        if path.suffix.lower() not in TEXT_EXTENSIONS or any(part in SKIP_PARTS for part in path.parts):
            continue
        checked += 1
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"{path}: UTF-8 decode failed: {exc}")
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            failures.append(f"{path}: UTF-8 BOM found")
        markers = [marker for marker in MOJIBAKE_MARKERS if marker in text]
        replacement_character = chr(0xFFFD)
        if replacement_character in text or markers:
            failures.append(
                f"{path}: replacement/mojibake marker found: {markers or ['U+FFFD']}"
            )

    print(f"Encoding check: {checked} tracked text files inspected")
    if failures:
        print("\n".join(failures))
        return 1
    print("Encoding check: PASS (strict UTF-8, no BOM, replacement, or mojibake markers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
