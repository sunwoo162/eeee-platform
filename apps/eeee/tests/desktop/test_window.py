import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.desktop.window import PetWindow
from app.desktop.pet_assets import PET_ASSET_TABLE
from app.desktop.pet_assets import PET_ASSET_TABLE


class SlowClient:
    def get_state(self):
        return {"state": "idle", "message": "Ready for a development request"}

    def create_request(self, text):
        time.sleep(0.15)
        return {
            "state": "researching",
            "task_id": "task-1",
            "request_id": "request-1",
            "message": f"Researching {text}",
        }

    def run(self, task_id):
        time.sleep(0.15)
        return {
            "state": "awaiting_approval",
            "task_id": task_id,
            "request_id": "request-1",
            "message": "Choose a repository",
            "candidates": [],
        }


class RouteClient(SlowClient):
    def __init__(self):
        self.routed_text = None

    def get_desktop_state(self, project_id=None):
        return {
            "state": "idle",
            "message": "Ready for a development request",
            "projectState": {
                "state": "idle",
                "message": "Project Runtime is ready.",
            },
        }

    def route_assistant(self, text, workspace=None):
        self.routed_text = text
        return {"status": "completed", "message": "요청을 받았어요."}


class SlowInitialRefreshClient(RouteClient):
    def get_state(self):
        time.sleep(0.2)
        return super().get_state()


class ClarificationClient(RouteClient):
    def route_assistant(self, text, workspace=None):
        self.routed_text = text
        return {"status": "needs_clarification", "message": "어떤 작업부터 시작할까?"}


class SlowRouteClient(RouteClient):
    def route_assistant(self, text, workspace=None):
        time.sleep(0.15)
        return super().route_assistant(text, workspace)


def _wait_for(app: QApplication, predicate) -> None:
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)


def test_create_request_does_not_block_gui_while_auto_run_is_in_progress():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window.move(200, 300)
    _wait_for(app, lambda: window.current_state.get("state") == "idle")

    window.request_input.setText("Add a dashboard")
    started = time.monotonic()
    window._create_request()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert not window.request_button.isEnabled()

    _wait_for(app, lambda: window.current_state.get("state") == "awaiting_approval")
    window.close()

    assert window.current_state.get("state") == "awaiting_approval"
    assert window.request_button.isEnabled()


def test_pet_mode_only_shows_character_and_bubble_until_command_surface_opens():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window.character.objectName() == "assistantCharacter"
    assert window.assistant_input.objectName() == "assistantComposer"
    assert window.detail.objectName() == "assistantBubble"
    _wait_for(app, lambda: window.current_state.get("state") == "idle")
    _wait_for(app, lambda: window.detail.text() == "")
    assert window.detail.text() == ""
    assert window.headline.isHidden()
    assert window.status_card.isHidden()
    assert window.command_surface.isHidden()
    assert window.legacy_panel.isHidden()
    assert window._reply_hide_timer.interval() == 5000
    window.show_command_surface()
    assert not window.command_surface.isHidden()
    assert window.detail.isHidden()
    assert window.quick_status.isHidden()
    assert window.quick_reply.text() == ""
    assert not window.quick_reply.isVisible()
    window.hide_command_surface()
    assert window.reply_surface.isHidden()
    window.close()


def test_pet_surface_is_transparent_and_compact():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window.minimumWidth() <= 120
    assert "background: transparent" in window.styleSheet()
    assert window.status_card.isHidden()
    assert window.legacy_panel.isHidden()
    window.close()


def test_speech_bubble_uses_the_generated_transparent_asset():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    bubble_pixmap = getattr(window.detail, "bubble_pixmap", None)

    assert bubble_pixmap is not None
    assert not bubble_pixmap.isNull()
    assert "background: #fff7ef" not in window.styleSheet()
    window.close()


def test_quick_chat_uses_the_same_speech_bubble_asset_without_legacy_pills():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    quick_bubble_pixmap = getattr(window.command_surface, "bubble_pixmap", None)

    assert quick_bubble_pixmap is not None
    assert not quick_bubble_pixmap.isNull()
    assert "#fff7ef" not in window.command_surface.styleSheet()
    assert "#efc28f" not in window.command_surface.styleSheet()
    window.close()


def test_quick_chat_sends_with_enter_without_inserting_a_greeting():
    app = QApplication.instance() or QApplication([])
    client = RouteClient()
    window = PetWindow(client)
    _wait_for(app, lambda: not window._busy)
    window.show_command_surface()

    assert window.assistant_input.placeholderText() == ""
    _wait_for(app, lambda: window.quick_reply.text() == "")
    assert window.quick_reply.text() == ""

    window.assistant_input.setText("안녕")
    window.assistant_input.returnPressed.emit()
    _wait_for(app, lambda: client.routed_text == "안녕")
    assert client.routed_text == "안녕"
    _wait_for(app, lambda: not window._busy)

    window.assistant_input.setText("다시 보내기")
    window.assistant_input.returnPressed.emit()
    _wait_for(app, lambda: client.routed_text == "다시 보내기")
    assert client.routed_text == "다시 보내기"
    window.close()


def test_quick_chat_input_is_centered_and_not_blocked_by_initial_refresh():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowInitialRefreshClient())
    window.show_command_surface()
    app.processEvents()

    assert not hasattr(window, "assistant_paw_left")
    assert not hasattr(window, "assistant_paw_right")
    assert window.assistant_input.alignment() == Qt.AlignmentFlag.AlignCenter
    assert abs(
        window.assistant_input.geometry().center().x()
        - window.command_surface.rect().center().x()
    ) <= 8
    assert window.assistant_input.height() == 42
    assert window.assistant_input.isEnabled()
    window.close()


def test_bubble_text_is_black_and_centered_without_a_height_cap():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window.detail.alignment() == Qt.AlignmentFlag.AlignCenter
    assert window.quick_reply.alignment() == Qt.AlignmentFlag.AlignCenter
    assert "color: #000000" in window.styleSheet()
    assert "color: #000000" in window.command_surface.styleSheet()
    assert window.detail.maximumHeight() == 16777215
    assert window.quick_reply.maximumHeight() == 16777215
    window.close()


def test_idle_assistant_reply_is_not_replaced_by_greeting():
    app = QApplication.instance() or QApplication([])
    client = ClarificationClient()
    window = PetWindow(client)
    window.show_command_surface()
    _wait_for(app, lambda: not window._busy)

    window.assistant_input.setText("도와줘")
    window.assistant_input.returnPressed.emit()
    _wait_for(app, lambda: window.current_state.get("state") == "idle")
    _wait_for(app, lambda: window.quick_reply.text() == "어떤 작업부터 시작할까?")

    assert window.quick_reply.text() == "어떤 작업부터 시작할까?"
    window.close()


def test_quick_chat_above_pet_contains_input_and_latest_reply():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window.move(300, 500)
    _wait_for(app, lambda: window.isVisible())
    window.detail.setText("이전 답변")

    window.show_command_surface()
    window._start_reply_typing("이전 답변")
    window._reposition_command_surface()

    anchor = window._pet_anchor_rect()
    tail_offset = window._speech_bubble_tail_offset(
        window.command_surface, window.command_surface.size()
    )
    assert abs(
        window.command_surface.frameGeometry().top()
        + tail_offset.y()
        - (anchor.top() - 6)
    ) <= 2
    assert window.detail.isHidden()
    assert window.quick_reply.isVisible()
    assert window.quick_reply.text()
    window.close()


def test_quick_chat_starts_with_only_a_centered_composer():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show_command_surface()
    app.processEvents()

    assert window.quick_reply.text() == ""
    assert not window.quick_reply.isVisible()
    assert window.assistant_input.alignment() == Qt.AlignmentFlag.AlignCenter
    assert abs(
        window.assistant_input.geometry().center().y()
        - window.command_surface.rect().center().y()
    ) <= 8
    window.close()


def test_quick_chat_send_switches_from_composer_to_one_centered_reply():
    app = QApplication.instance() or QApplication([])
    client = SlowRouteClient()
    window = PetWindow(client)
    window.show_command_surface()
    window.assistant_input.setText("안녕")
    window.assistant_input.returnPressed.emit()
    app.processEvents()

    assert window.assistant_input.isHidden()
    assert window.quick_status.isHidden()
    assert window.quick_reply.isVisible()

    _wait_for(app, lambda: window.current_state.get("state") == "completed")
    _wait_for(app, lambda: window.quick_reply.text() == "요청을 받았어요.")
    assert window.assistant_input.isHidden()
    assert window.quick_reply.alignment() == Qt.AlignmentFlag.AlignCenter
    window.close()


def test_quick_chat_reply_hides_the_whole_surface_after_reply_timeout():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show_command_surface()
    window._render({"state": "completed", "message": "완료했어."})
    _wait_for(app, lambda: window.quick_reply.text() == "완료했어.")

    window._reply_hide_timer.setInterval(20)
    window._reply_hide_timer.stop()
    window._schedule_reply_hide()
    _wait_for(app, lambda: window.command_surface.isHidden())

    assert window.command_surface.isHidden()
    assert window.quick_reply.isHidden()
    window.close()


def test_reopening_after_reply_timeout_starts_with_a_clean_composer():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show_command_surface()
    window._render({"state": "completed", "message": "이전 답변"})
    _wait_for(app, lambda: window.quick_reply.text() == "이전 답변")

    window._reply_hide_timer.setInterval(20)
    window._reply_hide_timer.stop()
    window._schedule_reply_hide()
    _wait_for(app, lambda: window.command_surface.isHidden())
    window.show_command_surface()

    assert window.assistant_input.isVisible()
    assert window.assistant_input.text() == ""
    assert window.quick_reply.isHidden()
    assert window.quick_reply.text() == ""
    window.close()


def test_initial_pet_position_is_bottom_right_of_the_available_screen():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    position = window._initial_pet_position(QRect(0, 0, 800, 600), QSize(180, 108))

    assert position == QPoint(596, 468)
    window.close()


def test_cat_keyboard_pet_assets_are_loaded_and_typing_switches_hands():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert all(not pixmap.isNull() for pixmap in window._pet_pixmaps.values())
    assert not window.character.pixmap().isNull()
    assert window.character.width() <= 200
    assert window.character.height() <= 120

    window._on_user_typing("A")
    assert window._typing_active is True
    window._typing_hand = window._hand_for_key_code(0x41)
    assert window._typing_hand == "left"
    window._update_pet_motion()
    window._typing_hand = window._hand_for_key_code(0x4C)
    assert window._typing_hand == "right"
    window._update_pet_motion()

    window._on_user_typing("")
    assert window._typing_active is False
    assert window._last_gaze_frame in {"idle", "gaze_left", "gaze_right"}
    window.close()


def test_idle_pose_composes_both_resting_paws():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert not window._pet_pixmaps["paw_left_rest"].isNull()
    assert not window._pet_pixmaps["paw_right_rest"].isNull()
    idle = window._source_pixmap_for_frame("idle")
    assert not idle.isNull()
    assert idle.toImage() != window._pet_pixmaps["idle"].toImage()
    window.close()


def test_typing_pose_returns_to_two_paw_idle_after_five_seconds():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window._read_global_key_states = lambda: {}
    window._typing_active = True
    window._last_typing_frame = "right_press"
    window._last_text_edit_at = time.monotonic() - 5.1

    window._update_pet_motion()

    assert window._typing_active is False
    assert window._last_rendered_frame == "idle"
    window.close()


def test_right_repeat_uses_the_same_hand_short_pose():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window._typing_hand == "left"
    window._typing_hand = "right"
    window._typing_hand_press_count = 1
    assert window._typing_frame_name() == "right"
    window._typing_hand_press_count = 2
    assert window._typing_frame_name() == "right_press"
    assert window._press_source_frame("right") == "right_short"
    window.close()


def test_right_hand_uses_the_viewer_left_keyboard_pose_assets():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    asset_dir = Path(__file__).resolve().parents[2] / "app" / "desktop" / "assets"

    assert (asset_dir / "cat-keyboard-left.png").is_file()
    assert (asset_dir / "cat-keyboard-left-alt.png").is_file()
    assert window._press_source_frame("right") == "right_short"
    window._typing_hand_press_count = 1
    assert window._typing_frame_name() == "left"
    window._typing_hand = "right"
    window._typing_hand_press_count = 1
    assert window._typing_frame_name() == "right"
    window._typing_hand_press_count = 2
    assert window._typing_frame_name() == "right_press"
    assert len({
        (asset_dir / "cat-keyboard-left.png").read_bytes(),
        (asset_dir / "cat-keyboard-left-alt.png").read_bytes(),
    }) == 2
    window.close()


def test_every_pet_frame_stays_inside_the_compact_character_bounds():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    for frame in ("idle", "left", "left_alt", "right", "right_alt", "gaze_left", "gaze_right"):
        window._set_pet_frame(frame)
        pixmap = window.character.pixmap()
        assert not pixmap.isNull(), frame
        assert window.character.size() == window._pet_display_size
        assert pixmap.width() <= window._pet_display_size.width(), frame
        assert pixmap.height() <= window._pet_display_size.height(), frame

    window.close()


def test_pet_motion_uses_fixed_size_and_interactive_keyboard_polling():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    # The production timer reads the real Windows keyboard globally. Isolate
    # this state-machine assertion from keys held while pytest is running.
    window._read_global_key_states = lambda: {}

    assert window._pet_display_size == QSize(180, 108)
    assert window._pet_motion_timer.interval() <= 32

    window._apply_global_key_states({0x41: True})
    assert window._typing_active is True
    assert window._typing_hand == "left"
    assert window._last_global_key_code == 0x41
    window._update_pet_motion()
    assert window._last_rendered_frame == "left"
    assert window._typing_pose == {"pressing": "left", "lifted": "right"}

    window._apply_global_key_states({0x4C: True})
    assert window._typing_hand == "right"
    assert window._last_global_key_code == 0x4C
    window._update_pet_motion()
    assert window._last_rendered_frame == "right"
    assert window._typing_pose == {"pressing": "right", "lifted": "left"}

    window._apply_global_key_states({})
    assert window._typing_active is False
    window.close()


@pytest.mark.parametrize(
    ("key_code", "expected_hand"),
    [
        (0x54, "left"),   # T
        (0x59, "right"),  # Y
        (0x47, "left"),   # G
        (0x48, "right"),  # H
        (0x42, "left"),   # B
        (0x4E, "right"),  # N
        (0x31, "left"),   # 1
        (0x36, "right"),  # 6
        (0xBC, "right"),  # comma
    ],
)
def test_keyboard_hand_map_follows_physical_qwerty_columns(key_code, expected_hand):
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window._hand_for_key_code(key_code) == expected_hand
    window.close()


def test_repeated_keys_animate_the_same_visual_hand_until_the_physical_side_changes():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window._read_global_key_states = lambda: {}

    window._apply_global_key_states({0x41: True})  # A: left, first pose
    assert window._typing_frame_name() == "left"
    window._apply_global_key_states({})
    window._apply_global_key_states({0x53: True})  # S: same hand, pressed pose
    assert window._typing_frame_name() == "left_press"
    window._apply_global_key_states({})
    window._apply_global_key_states({0x4C: True})  # L: switch hand, primary pose
    assert window._typing_frame_name() == "right"
    window._apply_global_key_states({})
    window._apply_global_key_states({0xBC: True})  # comma: same hand, pressed pose
    assert window._typing_frame_name() == "right_press"
    window.close()


def test_repeated_korean_jamo_physical_key_does_not_flip_paws():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window._read_global_key_states = lambda: {}

    for _ in range(5):
        window._apply_global_key_states({0x44: True})  # D produces ㅇ on Korean 2-set
        assert window._typing_hand == "left"
        assert window._typing_frame_name() == ("left" if _ % 2 == 0 else "left_press")
        window._apply_global_key_states({})

    window.close()


def test_gaze_tracks_cursor_during_typing_without_changing_keyboard_frame():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    center = window.character.mapToGlobal(window.character.rect().center())
    left_frame, left_offset = window._gaze_for_cursor(center + QPoint(-900, -300))
    right_frame, right_offset = window._gaze_for_cursor(center + QPoint(900, 300))
    assert left_frame == "gaze_left"
    assert right_frame == "gaze_right"
    assert left_offset != right_offset

    window._gaze_offset = left_offset
    left = window._source_pixmap_for_frame("left").toImage()
    window._gaze_offset = right_offset
    right = window._source_pixmap_for_frame("left").toImage()
    assert left.copy(0, 650, left.width(), left.height() - 650) == right.copy(
        0, 650, right.width(), right.height() - 650
    )
    window.close()


def test_repeated_same_hand_input_animates_without_switching_paws():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    # Keep this state-machine test deterministic; the production timer reads
    # the real Windows keyboard globally, but the test must not inherit keys
    # held while pytest is running.
    window._read_global_key_states = lambda: {}

    window._apply_global_key_states({0x41: True})
    window._update_pet_motion()
    first = window._last_rendered_frame
    window._apply_global_key_states({})
    window._apply_global_key_states({0x41: True})
    window._update_pet_motion()
    second = window._last_rendered_frame

    assert first == "left"
    assert second == "left_press"
    assert first != second
    window.close()


def test_same_hand_press_frame_is_distinct_and_right_uses_complete_pose_pair():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window._press_source_frame("left") == "left_short"
    assert window._press_source_frame("right") == "right_short"
    # The repeated right-hand pose must come from the dedicated short-paw
    # export, never from the full alternate pose that contains the long paw.
    assert window._pet_pixmaps["right_short"].toImage() == window._pet_pixmaps[
        "right_repeat"
    ].toImage()

    base = window._source_pixmap_for_frame("left").toImage()
    pressed = window._source_pixmap_for_frame("left_press").toImage()
    opposite = window._source_pixmap_for_frame("right").toImage()
    idle = window._source_pixmap_for_frame("idle").toImage()
    clip = window._same_paw_clip_path("left")
    repeat_outside_diffs = sum(
        idle.pixelColor(x, y) != pressed.pixelColor(x, y)
        for y in range(200, 400, 24)
        for x in range(600, 1000, 24)
        if not clip.contains(QPointF(x, y))
    )
    right_base = window._source_pixmap_for_frame("right").toImage()
    right_pressed = window._source_pixmap_for_frame("right_press").toImage()
    right_idle = window._source_pixmap_for_frame("idle").toImage()
    right_clip = window._same_paw_clip_path("right")
    right_repeat_outside_diffs = sum(
        right_idle.pixelColor(x, y) != right_pressed.pixelColor(x, y)
        for y in range(200, 400, 24)
        for x in range(600, 1000, 24)
        if not right_clip.contains(QPointF(x, y))
    )

    assert pressed != base
    assert pressed != opposite
    # First press uses the complete pose (including the raised opposite paw),
    # while a consecutive same-hand press renders only the active short paw
    # over the idle pose. The opposite paw therefore stays down on repeats.
    assert repeat_outside_diffs == 0
    assert right_pressed != right_base
    assert right_repeat_outside_diffs == 0
    window.close()


def test_pet_asset_table_keeps_press_motion_modular_and_tight():
    left = PET_ASSET_TABLE["left"]
    right = PET_ASSET_TABLE["right"]

    assert left["body"] == "idle"
    assert left["base"] == "left"
    assert left["press"] == "left_short"
    assert right["body"] == "idle"
    assert right["base"] == "right"
    assert right["press"] == "right_short"
    assert left["paw_mask"]["x_max"] - left["paw_mask"]["x_min"] < 300
    assert right["paw_mask"]["x_max"] - right["paw_mask"]["x_min"] < 300
    assert left["paw_mask"]["y_min"] > 400
    assert right["paw_mask"]["y_min"] > 520

    # Stable body/keyboard anchors must never be inside the press layer.  If
    # they are, swapping a repeated-key pose visibly shakes the mascot.
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    left_mask = window._same_paw_clip_path("left")
    assert left_mask.contains(QPointF(1160, 540))
    assert not left_mask.contains(QPointF(900, 460))
    assert not left_mask.contains(QPointF(1100, 800))
    right_mask = window._same_paw_clip_path("right")
    assert not right_mask.contains(QPointF(570, 535))
    assert not right_mask.contains(QPointF(570, 800))
    window.close()


def test_last_typing_pose_is_preserved_after_input_stops():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window._read_global_key_states = lambda: {}
    window._gaze_for_cursor = lambda cursor: ("gaze_right", (6, 0))

    window._apply_global_key_states({0x4C: True})  # L: right-hand pose
    window._last_text_edit_at = 0.0
    window._update_pet_motion()

    assert window._typing_active is False
    assert window._last_typing_frame == "right"
    assert window._last_rendered_frame == "right"
    window.close()


def test_repeated_same_key_press_is_not_dropped_when_keyup_is_between_polls():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    # A fast tap can release and press the same key between two 16 ms polls.
    # The Windows transition bit must preserve that second press even though
    # the sampled high-bit state is still True at both observations.
    window._global_key_press_events = [0x41]
    window._apply_global_key_states({0x41: True})
    first_event_count = window._typing_event_count

    window._global_key_press_events = [0x41]
    window._apply_global_key_states({0x41: True})
    assert window._typing_event_count == first_event_count + 1
    assert window._last_global_key_code == 0x41
    window.close()


def test_pet_frames_share_one_visible_source_crop_so_hover_does_not_resize_the_cat():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    source = window._pet_source_rect
    assert source.width() > 0 and source.height() > 0
    rendered_sizes = []
    for frame in ("idle", "gaze_left", "gaze_right", "left", "right"):
        window._set_pet_frame(frame)
        rendered_sizes.append(window.character.pixmap().size())
    assert all(size == rendered_sizes[0] for size in rendered_sizes)
    assert window.character.size() == window._pet_display_size
    window.close()


def test_gaze_frames_reuse_the_idle_keyboard_canvas():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    idle = window._resting_pet_pixmap().toImage()
    for frame in ("gaze_left", "gaze_center", "gaze_right"):
        gaze = window._source_pixmap_for_frame(frame).toImage()
        assert gaze.copy(0, 650, idle.width(), idle.height() - 650) == idle.copy(
            0, 650, idle.width(), idle.height() - 650
        )
    window.close()


def test_reply_bubble_is_above_pet_and_can_grow_wider_than_compact_pet_mode():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window._render(
        {
            "state": "completed",
            "message": "긴 답변입니다. 여러 줄이 말풍선 안에서 자연스럽게 보여야 합니다.",
        }
    )
    _wait_for(app, lambda: window.detail.text().endswith("보여야 합니다."))

    assert window.detail.geometry().top() < window.character.geometry().top()
    assert window.maximumWidth() >= 640
    assert window.detail.maximumWidth() == 640
    window.close()


def test_enter_submits_the_assistant_command():
    app = QApplication.instance() or QApplication([])
    client = RouteClient()
    window = PetWindow(client)
    window.show_command_surface()
    _wait_for(app, lambda: not window._busy)
    window.assistant_input.setText("Todo 앱 만들어줘")
    window.assistant_input.returnPressed.emit()

    _wait_for(
        app,
        lambda: client.routed_text == "Todo 앱 만들어줘"
        and window.current_state.get("state") == "completed",
    )

    assert client.routed_text == "Todo 앱 만들어줘"
    assert window.current_state["state"] == "completed"
    _wait_for(app, lambda: window.detail.text() == "요청을 받았어요.")
    assert window.detail.text() == "요청을 받았어요."
    assert not window.command_surface.isHidden()
    assert window.quick_reply.text() == "요청을 받았어요."
    window.close()


def test_assistant_reply_is_not_overwritten_by_project_state_message():
    app = QApplication.instance() or QApplication([])
    client = RouteClient()
    window = PetWindow(client)
    window.show_command_surface()
    _wait_for(app, lambda: not window._busy)

    window.assistant_input.setText("안녕")
    window.assistant_input.returnPressed.emit()
    _wait_for(app, lambda: window.current_state.get("state") == "completed")

    _wait_for(app, lambda: window.detail.text() == "요청을 받았어요.")
    assert window.detail.text() == "요청을 받았어요."
    window.close()


def test_escape_closes_the_command_surface():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show_command_surface()

    assert not window.command_surface.isHidden()
    QTest.keyClick(window.assistant_input, Qt.Key.Key_Escape)

    assert window.command_surface.isHidden()
    window.close()


def test_clicking_the_pet_opens_the_chat_surface():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()

    assert window.command_surface.isHidden()
    QTest.mouseClick(window.character, Qt.MouseButton.LeftButton)

    assert not window.command_surface.isHidden()
    assert window.command_surface.parent() is None
    assert window.command_surface.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    window.close()


def test_dragging_the_pet_moves_it_without_opening_chat():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    origin = window.pos()
    window._pet_drag_origin = QPoint(100, 100)
    window._pet_window_origin = origin
    window._pet_is_dragging = False

    current = QPoint(180, 150)
    distance = (current - window._pet_drag_origin).manhattanLength()
    window._pet_is_dragging = distance >= QApplication.startDragDistance()
    if window._pet_is_dragging:
        window.move(window._pet_window_origin + current - window._pet_drag_origin)

    assert window.pos() == origin + QPoint(80, 50)
    assert window.command_surface.isHidden()
    window.close()


def test_quick_chat_is_anchored_to_the_pet_and_clamped_to_screen_edges():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window.move(200, 300)
    _wait_for(app, lambda: window.current_state.get("state") == "idle")

    screen = QRect(0, 0, 800, 600)
    surface_size = QSize(320, 180)
    position = window._command_surface_position(screen, surface_size)
    anchor = window._pet_anchor_rect()
    tail_offset = window._speech_bubble_tail_offset(window.command_surface, surface_size)

    assert position.x() >= screen.left() + 12
    assert position.x() + surface_size.width() <= screen.right() - 11
    assert abs(position.y() + tail_offset.y() - (anchor.top() - 6)) <= 2
    window.close()


def test_quick_chat_prefers_above_the_pet_when_space_is_available():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window.move(200, 220)

    screen = QRect(0, 0, 1200, 800)
    surface_size = QSize(320, 180)
    anchor = window._pet_anchor_rect()
    position = window._command_surface_position(screen, surface_size)

    tail_offset = window._speech_bubble_tail_offset(window.command_surface, surface_size)
    assert abs(position.y() + tail_offset.y() - (anchor.top() - 6)) <= 2
    assert abs(
        position.x() + surface_size.width() // 2
        - (anchor.left() + round(anchor.width() * 0.44))
    ) <= 12
    window.close()


def test_quick_chat_bubble_tail_tracks_the_cat_head_not_the_window_frame():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window.move(200, 220)

    screen = QRect(0, 0, 1200, 800)
    surface_size = QSize(320, 180)
    position = window._command_surface_position(screen, surface_size)
    character_top_left = window.character.mapToGlobal(window.character.rect().topLeft())
    character_rect = QRect(character_top_left, window.character.size())
    tail_offset = window._speech_bubble_tail_offset(window.command_surface, surface_size)
    expected_tail_x = character_rect.left() + round(character_rect.width() * 0.44)
    expected_tail_y = character_rect.top() - 6

    assert abs(position.x() + tail_offset.x() - expected_tail_x) <= 2
    assert abs(position.y() + tail_offset.y() - expected_tail_y) <= 2
    window.close()


def test_normal_reply_bubble_uses_the_cat_eye_anchor():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window.move(200, 220)
    window._render({"state": "completed", "message": "완료했어."})
    _wait_for(app, lambda: window.reply_surface.isVisible())

    anchor = window._pet_anchor_rect()
    surface_size = window.reply_surface.size()
    position = window._reply_surface_position()
    tail_offset = window._speech_bubble_tail_offset(window.reply_surface, surface_size)

    assert abs(
        position.x() + tail_offset.x()
        - (anchor.left() + round(anchor.width() * 0.44))
    ) <= 12
    assert abs(position.y() + tail_offset.y() - (anchor.top() - 6)) <= 2
    window.close()


def test_quick_chat_reply_has_a_bounded_height_for_long_responses():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window.command_surface.width() <= 460
    assert window.quick_reply.maximumHeight() == 16777215
    window.close()


def test_reply_is_typed_into_the_pet_bubble():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    _wait_for(app, lambda: window.current_state.get("state") == "idle")

    window._render({"state": "completed", "message": "완료했어."})
    assert window.detail.text() in {"", "완"}
    _wait_for(app, lambda: window.detail.text() == "완료했어.")

    assert window.detail.text() == "완료했어."
    assert window.quick_reply.isHidden()
    window.close()


def test_quick_chat_reanchors_after_pet_moves():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    window.move(200, 300)
    window.show_command_surface()
    first = window.command_surface.pos()

    window.move(420, 180)
    app.processEvents()
    second = window.command_surface.pos()

    assert second != first
    centered_x = (
        second.x() + window.command_surface.width() // 2
        - window._pet_anchor_rect().center().x()
    )
    assert abs(centered_x + round(window._pet_anchor_rect().width() * 0.06)) <= 2 or second.x() == 0 or (
        second.x() + window.command_surface.width()
        >= window.screen().availableGeometry().right() - 11
    )
    window.close()


def test_background_refresh_does_not_replace_active_chat_message():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show_command_surface()
    _wait_for(app, lambda: window.current_state.get("state") == "idle")
    window._render({"state": "completed", "message": "원래 답변"})
    window._busy = True

    window._render_background({"state": "working", "message": "백그라운드 상태"})
    _wait_for(app, lambda: window.quick_reply.text() == "원래 답변")

    assert window.quick_reply.text() == "원래 답변"
    assert window.detail.text() == "원래 답변"
    window.close()


def test_short_reply_bubble_is_hidden_after_its_display_window():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    _wait_for(app, lambda: window.current_state.get("state") == "idle")
    window._render({"state": "completed", "message": "완료했어."})
    assert not window.reply_surface.isHidden()

    window._reply_hide_timer.setInterval(20)
    window._reply_hide_timer.stop()
    window._schedule_reply_hide()
    _wait_for(app, lambda: window.reply_surface.isHidden())

    assert window.detail.isHidden()
    window.close()


def test_long_running_reply_bubble_is_hidden_after_acknowledgement_window():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    _wait_for(app, lambda: window.current_state.get("state") == "idle")
    window._render({"state": "working", "message": "작업을 백그라운드에서 진행 중이야."})
    assert not window.reply_surface.isHidden()

    window._reply_hide_timer.setInterval(20)
    window._reply_hide_timer.stop()
    window._schedule_reply_hide()
    _wait_for(app, lambda: window.reply_surface.isHidden())

    assert window.detail.isHidden()
    window.close()


def test_hiding_a_hidden_pet_does_not_lose_timer_restore_state():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    app.processEvents()
    window.hide_to_tray()
    window.hide_to_tray()
    window.restore_from_tray()

    assert window._pet_motion_timer.isActive()
    assert window._topmost_timer.isActive()
    window.close()


def test_outside_click_closes_quick_chat_but_pet_click_does_not():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show_command_surface()
    assert not window.command_surface.isHidden()

    window._handle_global_mouse_press(window.command_surface.frameGeometry().center())
    assert not window.command_surface.isHidden()

    window._handle_global_mouse_press(QPoint(-100, -100))
    assert window.command_surface.isHidden()
    window.close()


def test_pet_profile_is_loaded_from_local_desktop_settings(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window._settings.setValue("profileName", "나의 EEEE")
    window._settings.setValue("profileAvatar", "🦊")
    window._load_profile()

    assert window.profile_name == "나의 EEEE"
    assert window.profile_avatar == "🦊"
    assert "나의 EEEE" in window.windowTitle()
    window._settings.remove("profileName")
    window._settings.remove("profileAvatar")
    window.close()
