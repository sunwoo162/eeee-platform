from app.mobile.bridge import MobileBridge, MobileBridgeError


def test_mobile_pairing_persists_only_authorized_device_state(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    bridge = MobileBridge(path)
    bridge.init()
    pairing = bridge.issue_pairing_code()

    device = bridge.pair(pairing["code"], "Pixel test")

    assert device["deviceId"].startswith("mobile-")
    assert bridge.authorize(device["accessToken"])["deviceName"] == "Pixel test"
    assert bridge.status()["pairedDevices"] == 1

    reopened = MobileBridge(path)
    reopened.init()
    assert reopened.authorize(device["accessToken"])["deviceId"] == device["deviceId"]

    reopened.revoke(device["deviceId"])
    try:
        reopened.authorize(device["accessToken"])
    except MobileBridgeError as exc:
        assert "invalid or revoked" in str(exc)
    else:  # pragma: no cover - protects the authorization boundary
        raise AssertionError("revoked mobile tokens must not authorize")


def test_events_survive_desktop_restart_and_resume_from_cursor(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    bridge = MobileBridge(path)
    bridge.init()
    first = bridge.publish("project.started", {"projectId": "project-1"})
    bridge.publish("project.completed", {"projectId": "project-1"})

    reopened = MobileBridge(path)
    reopened.init()

    resumed = reopened.events_after(first["cursor"])
    assert [event["kind"] for event in resumed["events"]] == ["project.completed"]


def test_events_report_when_requested_cursor_fell_outside_retained_window(tmp_path) -> None:
    bridge = MobileBridge(tmp_path / "state.sqlite3", event_limit=2)
    bridge.init()
    bridge.publish("project.started", {"projectId": "project-1"})
    bridge.publish("project.progress", {"projectId": "project-1"})
    bridge.publish("project.completed", {"projectId": "project-1"})
    bridge.publish("project.reviewed", {"projectId": "project-1"})

    batch = bridge.events_after(1)

    assert batch["hasGap"] is True
    assert batch["oldestCursor"] == 3
    assert [event["cursor"] for event in batch["events"]] == [3, 4]


def test_events_keep_gap_metadata_stable_for_initial_sync_and_empty_store(tmp_path) -> None:
    empty = MobileBridge(tmp_path / "empty.sqlite3", event_limit=2)
    empty.init()

    assert empty.events_after(0) == {
        "cursor": 0,
        "events": [],
        "hasGap": False,
        "oldestCursor": None,
    }

    bridge = MobileBridge(tmp_path / "initial.sqlite3", event_limit=2)
    bridge.init()
    bridge.publish("project.started", {"projectId": "project-1"})

    batch = bridge.events_after(0)

    assert batch["hasGap"] is False
    assert batch["oldestCursor"] == 1
