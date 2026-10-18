from pathlib import Path

import pytest

from app.core.lock import CoreAlreadyRunningError, ProcessLock


def test_process_lock_rejects_a_second_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "core.lock"

    first = ProcessLock(lock_path)
    first.acquire()
    try:
        second = ProcessLock(lock_path)
        with pytest.raises(CoreAlreadyRunningError):
            second.acquire()
    finally:
        first.release()


def test_process_lock_reclaims_a_stale_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "core.lock"
    lock_path.write_text("999999\n", encoding="utf-8")

    lock = ProcessLock(lock_path)
    lock.acquire()
    lock.release()
    assert lock_path.exists()


def test_process_lock_release_is_idempotent(tmp_path: Path) -> None:
    lock_path = tmp_path / "core.lock"
    lock = ProcessLock(lock_path)
    lock.acquire()
    lock.release()
    lock.release()

    second = ProcessLock(lock_path)
    second.acquire()
    second.release()

    assert lock_path.exists()
