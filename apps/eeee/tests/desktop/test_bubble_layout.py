from app.desktop.bubble_layout import (
    bubble_height_for_text,
    bubble_text_area_height,
    choose_bubble_width,
)


def test_choose_bubble_width_uses_the_smallest_preset_that_fits_three_lines():
    measured = {220: 56.0, 300: 42.0, 380: 56.0}

    width = choose_bubble_width(
        lambda text_width: measured[text_width],
        line_height=14.0,
        horizontal_padding=60,
        presets=(280, 360, 440),
        comfortable_lines=3,
    )

    assert width == 360


def test_bubble_height_reserves_the_tail_and_all_text_lines():
    height = bubble_height_for_text(
        text_height=140.0,
        top_padding=26,
        bottom_padding=26,
        tail_y_ratio=764 / 887,
        glyph_breathing_room=4,
    )

    body_height = round(height * (764 / 887)) - 26 - 26
    assert body_height >= 140


def test_text_area_height_is_never_negative_for_a_short_bubble():
    assert bubble_text_area_height(
        surface_height=40,
        tail_y_ratio=764 / 887,
        top_padding=26,
        bottom_padding=26,
    ) == 1
