"""
Schematic "typical layout" floor plans for each HDB flat type, drawn by
partials/floor_plan.html as an SVG. Our own drawings, not HDB's plans (those are
copyrighted): the room mix and sizes follow the common layout of each type, and the page
says actual units vary.

Each room is (label, kind, x, y, width, height) on a 400 x 270 canvas whose outer wall runs
from (10, 10) to (390, 250); `kind` picks the fill (see .ff-plan in app.css). `door` is the
x of the entrance on the bottom wall.
"""

PLANS = {
    "1 ROOM": {
        "summary": "Studio · 1 bathroom", "typical": "about 33 m²", "door": 135,
        "rooms": [
            ("Living / sleeping", "living", 10, 10, 250, 240),
            ("Kitchen", "kitchen", 260, 10, 130, 120),
            ("Bath", "wet", 260, 130, 130, 120),
        ],
    },
    "2 ROOM": {
        "summary": "1 bedroom · 1 bathroom", "typical": "about 45 m²", "door": 300,
        "rooms": [
            ("Bedroom", "bed", 10, 10, 170, 130),
            ("Bath", "wet", 180, 10, 80, 80),
            ("Shelter", "other", 180, 90, 80, 50),
            ("Kitchen", "kitchen", 260, 10, 130, 130),
            ("Living / dining", "living", 10, 140, 380, 110),
        ],
    },
    "3 ROOM": {
        "summary": "2 bedrooms · 2 bathrooms", "typical": "60–70 m²", "door": 140,
        "rooms": [
            ("Master bedroom", "bed", 10, 10, 150, 120),
            ("Bath", "wet", 160, 10, 60, 60),
            ("Bath", "wet", 160, 70, 60, 60),
            ("Bedroom 2", "bed", 220, 10, 110, 120),
            ("Shelter", "other", 330, 10, 60, 60),
            ("Yard", "other", 330, 70, 60, 60),
            ("Living / dining", "living", 10, 130, 260, 120),
            ("Kitchen", "kitchen", 270, 130, 120, 120),
        ],
    },
    "4 ROOM": {
        "summary": "3 bedrooms · 2 bathrooms", "typical": "85–95 m²", "door": 135,
        "rooms": [
            ("Master bedroom", "bed", 10, 10, 130, 120),
            ("Bath", "wet", 140, 10, 55, 60),
            ("Bath", "wet", 140, 70, 55, 60),
            ("Bedroom 2", "bed", 195, 10, 100, 120),
            ("Bedroom 3", "bed", 295, 10, 95, 120),
            ("Living / dining", "living", 10, 130, 250, 120),
            ("Shelter", "other", 260, 130, 50, 60),
            ("Yard", "other", 260, 190, 50, 60),
            ("Kitchen", "kitchen", 310, 130, 80, 120),
        ],
    },
    "5 ROOM": {
        "summary": "3 bedrooms + study · 2 bathrooms", "typical": "105–115 m²", "door": 120,
        "rooms": [
            ("Master bedroom", "bed", 10, 10, 130, 115),
            ("Bath", "wet", 140, 10, 50, 57),
            ("Bath", "wet", 140, 67, 50, 58),
            ("Bedroom 2", "bed", 190, 10, 100, 115),
            ("Bedroom 3", "bed", 290, 10, 100, 115),
            ("Living / dining", "living", 10, 125, 220, 125),
            ("Study", "other", 230, 125, 70, 70),
            ("Shelter", "other", 230, 195, 70, 55),
            ("Kitchen", "kitchen", 300, 125, 90, 85),
            ("Service yard", "other", 300, 210, 90, 40),
        ],
    },
    "EXECUTIVE": {
        "summary": "3 bedrooms + study · 2 bathrooms · balcony", "typical": "130–145 m²", "door": 128,
        "rooms": [
            ("Master bedroom", "bed", 10, 10, 120, 110),
            ("Bath", "wet", 130, 10, 50, 55),
            ("Bath", "wet", 130, 65, 50, 55),
            ("Bedroom 2", "bed", 180, 10, 100, 110),
            ("Bedroom 3", "bed", 280, 10, 110, 110),
            ("Balcony", "other", 10, 120, 35, 130),
            ("Living / dining", "living", 45, 120, 165, 130),
            ("Study", "other", 210, 120, 90, 80),
            ("Shelter", "other", 210, 200, 90, 50),
            ("Kitchen", "kitchen", 300, 120, 90, 90),
            ("Yard", "other", 300, 210, 90, 40),
        ],
    },
    "MULTI-GENERATION": {
        "summary": "4 bedrooms · 3 bathrooms", "typical": "115–120 m²", "door": 110,
        "rooms": [
            ("Master bedroom", "bed", 10, 10, 120, 115),
            ("Bath", "wet", 130, 10, 50, 57),
            ("Bath", "wet", 130, 67, 50, 58),
            ("Bedroom 2", "bed", 180, 10, 105, 115),
            ("Bedroom 3", "bed", 285, 10, 105, 115),
            ("Living / dining", "living", 10, 125, 200, 125),
            ("Kitchen", "kitchen", 210, 125, 80, 70),
            ("Shelter", "other", 210, 195, 80, 55),
            ("Bedroom 4", "bed", 290, 125, 100, 85),
            ("Bath", "wet", 290, 210, 100, 40),
        ],
    },
}


def floor_plan(flat_type):
    """The drawable plan for a flat type (rooms with label positions), or None if there's none."""
    plan = PLANS.get(flat_type)
    if plan is None:
        return None
    return {
        "slug": flat_type.lower().replace(" ", "-"),
        "summary": plan["summary"],
        "typical": plan["typical"],
        "door": plan["door"],
        "rooms": [
            {"label": label, "kind": kind, "x": x, "y": y, "w": w, "h": h,
             "cx": x + w / 2, "cy": y + h / 2, "small": w < 70 or h < 45}
            for label, kind, x, y, w, h in plan["rooms"]
        ],
        "aria": ", ".join(sorted({label for label, *_ in plan["rooms"]})),
    }
