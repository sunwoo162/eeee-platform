from app.desktop.instance import DesktopInstanceLock


def test_only_one_desktop_instance_can_hold_the_lock(tmp_path):
    path = tmp_path / "eeee-desktop.lock"
    first = DesktopInstanceLock(path)
    second = DesktopInstanceLock(path)

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()
    assert second.acquire() is True
    second.release()


def test_releasing_an_unheld_lock_is_safe(tmp_path):
    lock = DesktopInstanceLock(tmp_path / "eeee-desktop.lock")

    lock.release()
    assert lock.acquire() is True
    lock.release()
    lock.release()
