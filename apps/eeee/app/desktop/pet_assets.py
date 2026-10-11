"""Table-driven composition rules for the desktop pet.

The source PNGs are full exports for compatibility with the existing bundle,
but typing frames are composed from a stable base plus one tightly bounded paw
layer.  Keeping the mapping here makes new poses additive instead of requiring
another full-canvas image swap.
"""

PET_ASSET_TABLE = {
    # ``left`` and ``right`` are physical keyboard hands.  The artwork is
    # mirrored from the user's point of view, hence the intentionally crossed
    # legacy names in the source files.
    "left": {
        "body": "idle",
        "base": "left",
        "press": "right_alt",
        "paw_mask": {
            "x_min": 980,
            "x_max": 1275,
            "y_min": 450,
            "y_max": 790,
            "points": (
                (1040, 470),
                (1130, 450),
                (1215, 475),
                (1265, 535),
                (1275, 630),
                (1250, 720),
                (1200, 780),
                (1110, 790),
                (1025, 760),
                (980, 700),
                (980, 600),
                (1000, 520),
            ),
        },
    },
    "right": {
        "body": "idle",
        "base": "right",
        "press": "left_alt",
        "paw_mask": {
            "x_min": 417,
            "x_max": 637,
            "y_min": 570,
            "y_max": 765,
            "points": (
                (512, 570),
                (457, 595),
                (422, 650),
                (437, 705),
                (477, 750),
                (527, 765),
                (582, 755),
                (617, 725),
                (632, 685),
                (614, 640),
                (572, 600),
            ),
        },
    },
}
