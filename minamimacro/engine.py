from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .color_detection import find_first_target_color_match
from pynput.mouse import Controller as MouseController

from .input_utils import deserialize_button
from .keyboard_backend import AutoKeyboardBackend
from .models import ActionType, InputAction, MacroSettings


MODIFIER_KEYS = {
    "special:Key.shift",
    "special:Key.shift_l",
    "special:Key.shift_r",
    "special:Key.ctrl",
    "special:Key.ctrl_l",
    "special:Key.ctrl_r",
    "special:Key.alt",
    "special:Key.alt_l",
    "special:Key.alt_r",
    "special:Key.cmd",
    "special:Key.cmd_l",
    "special:Key.cmd_r",
    "special:Key.super",
}


class MacroEngine:
    def __init__(self) -> None:
        self._keyboard_mode = "auto"
        self._keyboard = AutoKeyboardBackend(self._keyboard_mode)
        self._mouse = MouseController()
        self._actions: list[InputAction] = []
        self._settings = MacroSettings()
        self._pressed_keys: set[str] = set()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._status_callback: Callable[[str], None] | None = None
        self._color_match_callback: Callable[[dict], None] | None = None

    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        self._status_callback = callback

    def set_color_match_callback(self, callback: Callable[[dict], None]) -> None:
        self._color_match_callback = callback

    def update(self, actions: list[InputAction], settings: MacroSettings) -> None:
        self._actions = list(actions)
        self._settings = settings

    @property
    def keyboard_backend_name(self) -> str:
        return self._keyboard.name

    @property
    def keyboard_backend_mode(self) -> str:
        return self._keyboard_mode

    def set_keyboard_backend(self, backend_mode: str) -> tuple[bool, str]:
        mode = backend_mode.strip().lower()
        if self._running.is_set():
            return False, "Stop macro before changing keyboard backend"

        old_backend = self._keyboard
        old_mode = self._keyboard_mode
        try:
            self._keyboard = AutoKeyboardBackend(mode)
            self._keyboard_mode = mode
        except Exception as exc:
            self._keyboard = old_backend
            self._keyboard_mode = old_mode
            return False, str(exc)

        try:
            old_backend.close()
        except Exception:
            pass

        warning = self._keyboard.warning or ""
        message = f"Keyboard backend set to {self._keyboard.name}"
        if warning:
            message += f" ({warning})"
        return True, message

    def test_type_text(self, text: str) -> tuple[bool, str]:
        if not text:
            return False, "Text is empty"

        try:
            for ch in text:
                key_value = f"char:{ch}"
                self._keyboard.press_serialized(key_value)
                time.sleep(0.01)
                self._keyboard.release_serialized(key_value)
                time.sleep(0.01)
        except Exception as exc:
            return False, str(exc)

        return True, "Typing test sent"

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._set_status(f"Macro running (keyboard backend: {self._keyboard.name})")
        if self._keyboard.warning:
            self._set_status(self._keyboard.warning)

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        self._set_status("Macro stopped")

    def toggle(self) -> None:
        if self.is_running:
            self.stop()
        else:
            self.start()

    def _set_status(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(message)

    def _run_loop(self) -> None:
        while self._running.is_set():
            self._release_all_pressed_keys()
            for action in self._actions:
                if not self._running.is_set():
                    return
                effective_delay = self._apply_delay_variation(action.delay)
                if effective_delay > 0:
                    time.sleep(effective_delay)
                try:
                    self._execute_action(action)
                except Exception as exc:
                    self._set_status(f"Action error ({action.action_type.value}): {exc}")

            if self._settings.loop_delay > 0:
                time.sleep(self._settings.loop_delay)

    def _apply_delay_variation(self, base_delay_seconds: float) -> float:
        variation_ms = max(0.0, self._settings.action_delay_variation_ms)
        if variation_ms <= 0:
            return max(0.0, base_delay_seconds)

        jitter_seconds = random.uniform(-variation_ms, variation_ms) / 1000.0
        return max(0.0, base_delay_seconds + jitter_seconds)

    def _move_mouse_smooth(self, x: int, y: int) -> None:
        base_speed = self._settings.cursor_speed
        speed_variation = max(0.0, self._settings.cursor_speed_variation)
        speed = random.uniform(max(0.0, base_speed - speed_variation), base_speed + speed_variation)
        start_x, start_y = self._mouse.position
        distance = math.hypot(x - start_x, y - start_y)

        if speed <= 0 or distance == 0:
            self._mouse.position = (x, y)
            return

        duration = distance / speed
        steps = max(1, int(duration * 60))
        step_delay = duration / steps

        for step in range(1, steps + 1):
            if not self._running.is_set():
                return
            t = step / steps
            nx = int(start_x + (x - start_x) * t)
            ny = int(start_y + (y - start_y) * t)
            self._mouse.position = (nx, ny)
            time.sleep(step_delay)

    def _execute_action(self, action: InputAction) -> None:
        if action.action_type == ActionType.KEY_DOWN:
            key_value = str(action.payload["key"])
            self._keyboard.press_serialized(key_value)
            self._pressed_keys.add(key_value)
            return

        if action.action_type == ActionType.KEY_UP:
            key_value = str(action.payload["key"])
            if key_value in self._pressed_keys:
                self._keyboard.release_serialized(key_value)
                self._pressed_keys.discard(key_value)
            else:
                # Some recordings may contain key_up without key_down.
                self._tap_orphan_key(key_value)
            return

        if action.action_type == ActionType.MOUSE_CLICK:
            x = int(action.payload["x"])
            y = int(action.payload["y"])
            self._move_mouse_smooth(x, y)
            button = deserialize_button(action.payload["button"])
            if action.payload["pressed"]:
                self._mouse.press(button)
            else:
                self._mouse.release(button)
            return

        if action.action_type == ActionType.MOUSE_SCROLL:
            self._mouse.scroll(int(action.payload["dx"]), int(action.payload["dy"]))
            return

        if action.action_type == ActionType.TARGET_CLICK:
            point_x = int(action.payload["x"])
            point_y = int(action.payload["y"])
            random_x = random.randint(-self._settings.variation_x, self._settings.variation_x)
            random_y = random.randint(-self._settings.variation_y, self._settings.variation_y)
            target_x = point_x + random_x
            target_y = point_y + random_y

            self._move_mouse_smooth(target_x, target_y)
            self._mouse.click(button=deserialize_button("Button.left"))
            return

        if action.action_type == ActionType.COLOR_TRIGGER:
            self._execute_color_trigger(action)
            return

        if action.action_type == ActionType.SLEEP:
            milliseconds = max(0, int(action.payload.get("milliseconds", 0)))
            self._sleep_with_stop(milliseconds)
            return

    def _sleep_with_stop(self, milliseconds: int) -> None:
        if milliseconds <= 0:
            return
        end_time = time.perf_counter() + (milliseconds / 1000.0)
        while self._running.is_set():
            remaining = end_time - time.perf_counter()
            if remaining <= 0:
                return
            time.sleep(min(0.05, remaining))

    def _release_all_pressed_keys(self) -> None:
        if not self._pressed_keys:
            return
        for key_value in list(self._pressed_keys):
            try:
                self._keyboard.release_serialized(key_value)
            except Exception:
                pass
            self._pressed_keys.discard(key_value)

    def _tap_orphan_key(self, key_value: str) -> None:
        # Orphan key_up events are common on some Wayland setups.
        # For character keys, release held modifiers to avoid turning text into dead shortcuts.
        held_modifiers = [k for k in self._pressed_keys if k in MODIFIER_KEYS]
        is_char_key = key_value.startswith("char:")

        if is_char_key and held_modifiers:
            for modifier in held_modifiers:
                try:
                    self._keyboard.release_serialized(modifier)
                except Exception:
                    pass

        self._keyboard.press_serialized(key_value)
        time.sleep(0.012)
        self._keyboard.release_serialized(key_value)

        if is_char_key and held_modifiers:
            for modifier in held_modifiers:
                try:
                    self._keyboard.press_serialized(modifier)
                except Exception:
                    pass

    def _execute_color_trigger(self, action: InputAction) -> None:
        area_raw = action.payload.get("area", [])
        colors_raw = action.payload.get("colors", [])
        tolerance = int(action.payload.get("tolerance", 15))
        block_until_match = bool(action.payload.get("block_until_match", True))

        if len(area_raw) != 4:
            self._set_status("Color trigger skipped: invalid area")
            return

        if not colors_raw:
            self._set_status("Color trigger skipped: empty color set")
            return

        x1, y1, x2, y2 = [int(v) for v in area_raw]
        area = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        target_colors = [tuple(int(channel) for channel in color[:3]) for color in colors_raw]

        poll_delay = 0.15

        while self._running.is_set():
            try:
                match = find_first_target_color_match(area, target_colors, tolerance)
            except Exception as exc:
                self._set_status(f"Color trigger error: {exc}")
                return

            if match is not None:
                matched_rgb, matched_point = match
                self._emit_color_trigger_match(action, matched_rgb, matched_point)
                self._set_status("Color trigger matched")
                return

            if not block_until_match:
                self._set_status("Color trigger not matched, continuing")
                return

            time.sleep(poll_delay)

    def _emit_color_trigger_match(
        self,
        action: InputAction,
        matched_rgb: tuple[int, int, int],
        matched_point: tuple[int, int],
    ) -> None:
        payload = {
            "rgb": [int(matched_rgb[0]), int(matched_rgb[1]), int(matched_rgb[2])],
            "point": [int(matched_point[0]), int(matched_point[1])],
            "area": list(action.payload.get("area", [])),
            "tolerance": int(action.payload.get("tolerance", 15)),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        self._append_color_trigger_log(payload)
        if self._color_match_callback is not None:
            self._color_match_callback(payload)

    def _append_color_trigger_log(self, payload: dict) -> None:
        logs_dir = Path(__file__).resolve().parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "color_trigger.log"

        rgb = payload.get("rgb", [0, 0, 0])
        point = payload.get("point", [0, 0])
        area = payload.get("area", [])
        timestamp = payload.get("timestamp", "")
        tolerance = payload.get("tolerance", 0)

        line = (
            f"{timestamp} | RGB=({rgb[0]}, {rgb[1]}, {rgb[2]}) | "
            f"point=({point[0]}, {point[1]}) | area={area} | tolerance={tolerance}\n"
        )
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def close(self) -> None:
        self._release_all_pressed_keys()
        self._keyboard.close()
