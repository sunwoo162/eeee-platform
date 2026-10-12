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
            # The logical right hand is the paw on the viewer's right.  The
            # previous mask targeted the opposite paw and included a large
            # section of the keyboard, which exposed the full-canvas repeat
            # asset as a broken polygon on consecutive right-hand presses.
            "x_min": 1020,
            "x_max": 1275,
            "y_min": 500,
            "y_max": 750,
            "points": (
                # Follow just outside the short-paw silhouette so its black
                # outline is not cut by the clip. Keep the lower edge tight
                # enough that keyboard rows remain owned by the stable base.
                (1030, 675),
                (1035, 615),
                (1055, 575),
                (1095, 535),
                (1140, 510),
                (1200, 515),
                (1250, 540),
                (1270, 580),
                (1265, 630),
                (1235, 670),
                (1200, 710),
                (1160, 730),
                (1115, 735),
                (1070, 720),
                (1035, 690),
            ),
        },
    },
}

# The split resting paw exports are cropped from the same 1672x941 canvas as
# the body. These anchors put both paws back onto the common body/keyboard
# layer without moving the keyboard or changing the mascot footprint.
REST_PAW_LAYER_PLACEMENTS = {
    "paw_left_rest": (972, 442),
    "paw_right_rest": (414, 562),
}
