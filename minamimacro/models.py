from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    MOUSE_CLICK = "mouse_click"
    MOUSE_SCROLL = "mouse_scroll"
    TARGET_CLICK = "target_click"
    COLOR_TRIGGER = "color_trigger"
    SLEEP = "sleep"


@dataclass(slots=True)
class InputAction:
    delay: float
    action_type: ActionType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MacroSettings:
    cursor_speed: float = 1200.0
    cursor_speed_variation: float = 0.0
    variation_x: int = 0
    variation_y: int = 0
    loop_delay: float = 0.1
