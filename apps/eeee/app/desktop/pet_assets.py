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
        "press": "left_short",
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
        "press": "right_short",
        "paw_mask": {
            # The dedicated short-right export is a rounded paw above the
            # keyboard, not the old long paw that reached down into it.
            "x_min": 250,
            "x_max": 620,
            "y_min": 410,
            "y_max": 685,
            "points": (
                (340, 405),
                (430, 410),
                (520, 430),
                (595, 475),
                (620, 540),
                (610, 610),
                (570, 660),
                (500, 685),
                (410, 680),
                (330, 650),
                (270, 600),
                (245, 530),
                (275, 460),
            ),
        },
    },
}
