"""Pure geometry helpers for the scalable EEEE speech bubble."""

from __future__ import annotations

from collections.abc import Callable, Iterable


def choose_bubble_width(
    measure_text_height: Callable[[int], float],
    *,
    line_height: float,
    horizontal_padding: int,
    presets: Iterable[int],
    comfortable_lines: int,
) -> int:
    """Choose the smallest surface width that keeps a reply comfortable."""
    widths = tuple(int(width) for width in presets)
    if not widths:
        raise ValueError("at least one bubble width preset is required")
    threshold = max(1.0, float(line_height) * max(1, comfortable_lines))
    for width in widths:
        content_width = max(1, width - horizontal_padding)
        if measure_text_height(content_width) <= threshold:
            return width
    return widths[-1]


def bubble_height_for_text(
    *,
    text_height: float,
    top_padding: int,
    bottom_padding: int,
    tail_y_ratio: float,
    glyph_breathing_room: int = 0,
) -> int:
    """Return a surface height whose body can contain every glyph and tail."""
    if not 0 < tail_y_ratio <= 1:
        raise ValueError("tail_y_ratio must be between 0 and 1")
    body_height = (
        max(0.0, float(text_height))
        + max(0, top_padding)
        + max(0, bottom_padding)
        + max(0, glyph_breathing_room)
    )
    return max(1, int(body_height / tail_y_ratio + 0.9999))


def bubble_text_area_height(
    *,
    surface_height: int,
    tail_y_ratio: float,
    top_padding: int,
    bottom_padding: int,
) -> int:
    """Return the drawable text height, clamped so short surfaces stay valid."""
    body_height = round(max(0, surface_height) * tail_y_ratio)
    return max(1, body_height - max(0, top_padding) - max(0, bottom_padding))
