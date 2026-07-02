"""Set-of-Marks screenshot annotator.

Draws numbered colored bounding boxes over interactive elements so a vision
model can identify them by number rather than estimating pixel coordinates.

Two-phase draw: borders first, labels on top.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

# Elements whose label would overlap the very top of the page are repositioned
# to the bottom edge of their bounding box instead.
TOP_NO_LABEL_ZONE = 20  # pixels


def _color(identifier: int) -> Tuple[int, int, int, int]:
    """Deterministic RGBA color seeded by sequential element ID."""
    rnd = random.Random(identifier)
    color = [rnd.randint(0, 255), rnd.randint(125, 255), rnd.randint(0, 50)]
    rnd.shuffle(color)
    return (color[0], color[1], color[2], 255)


def annotate_som(
    screenshot_path: str,
    elements: List[Dict],
    output_path: str,
) -> Tuple[Dict[int, Dict], List[str]]:
    """Draw numbered bounding boxes on a screenshot using the two-phase approach.

    Args:
        screenshot_path: Path to the input PNG screenshot.
        elements: List of element dicts from _SessionState.all_visible.
                  Each must have: left, top, right, bottom, inViewport, occluded,
                  label (str), tag (str).
        output_path: Where to save the annotated PNG.

    Returns:
        som_map: {sequential_id: element_dict} for click resolution.
        ac_tree_lines: ["id: 1, text: Search, tag: button", ...] for LLM text context.
    """
    img = Image.open(screenshot_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fnt = ImageFont.load_default(14)

    screen_w, screen_h = img.size
    screen_area = screen_w * screen_h

    # Filter to visible, non-occluded elements that aren't full-screen (>90% area)
    visible = [
        el
        for el in elements
        if el.get("inViewport")
        and not el.get("occluded")
        and (el.get("right", 0) - el.get("left", 0))
        * (el.get("bottom", 0) - el.get("top", 0))
        < screen_area * 0.9
        and el.get("right", 0) > el.get("left", 0)
        and el.get("bottom", 0) > el.get("top", 0)
    ]

    som_map: Dict[int, Dict] = {}
    ac_tree_lines: List[str] = []

    # Phase 1: Draw all rectangle borders first
    for seq_id, el in enumerate(visible, 1):
        color = _color(seq_id)
        roi = [(el["left"], el["top"]), (el["right"], el["bottom"])]
        draw.rectangle(
            roi,
            outline=color,
            fill=(color[0], color[1], color[2], 48),
            width=2,
        )

    # Phase 2: Draw all labels on top (ensures label visibility over borders)
    for seq_id, el in enumerate(visible, 1):
        color = _color(seq_id)
        luminance = color[0] * 0.3 + color[1] * 0.59 + color[2] * 0.11
        text_color = (0, 0, 0, 255) if luminance > 90 else (255, 255, 255, 255)

        # Place label at upper-right corner; move to lower-right if near page top
        if el["top"] <= TOP_NO_LABEL_ZONE:
            loc = (el["right"], el["bottom"])
            anchor = "rt"
        else:
            loc = (el["right"], el["top"])
            anchor = "rb"

        label_str = str(seq_id)
        bbox = draw.textbbox(loc, label_str, font=fnt, anchor=anchor)
        padded = (bbox[0] - 3, bbox[1] - 3, bbox[2] + 3, bbox[3] + 3)
        draw.rectangle(padded, fill=color)
        draw.text(loc, label_str, fill=text_color, font=fnt, anchor=anchor)

        som_map[seq_id] = el
        ac_tree_lines.append(
            f"id: {seq_id}, text: {el.get('label', '')}, tag: {el.get('tag', '')}"
        )

    composite = Image.alpha_composite(img, overlay).convert("RGB")
    composite.save(output_path, format="PNG")
    return som_map, ac_tree_lines
