from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Callable

from .color_detection import area_contains_any_target_color
from pynput.mouse import Controller as MouseController

from .input_utils import deserialize_button
from .keyboard_backend import AutoKeyboardBackend
from .models import ActionType, InputAction, MacroSettings


class MacroEngine:
    def __init__(self) -> None:
        self._keyboard = AutoKeyboardBackend()
        self._mouse = MouseController()
        self._actions: list[InputAction] = []
        self._settings = MacroSettings()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._status_callback: Callable[[str], None] | None = None

    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        self._status_callback = callback

    def update(self, actions: list[InputAction], settings: MacroSettings) -> None:
        self._actions = list(actions)
        self._settings = settings

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
            for action in self._actions:
                if not self._running.is_set():
                    return
                if action.delay > 0:
                    time.sleep(action.delay)
                try:
                    self._execute_action(action)
                except Exception as exc:
                    self._set_status(f"Action error ({action.action_type.value}): {exc}")

            if self._settings.loop_delay > 0:
                time.sleep(self._settings.loop_delay)

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
            self._keyboard.press_serialized(str(action.payload["key"]))
            return

        if action.action_type == ActionType.KEY_UP:
            self._keyboard.release_serialized(str(action.payload["key"]))
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
                matched = area_contains_any_target_color(area, target_colors, tolerance)
            except Exception as exc:
                self._set_status(f"Color trigger error: {exc}")
                return

            if matched:
                self._set_status("Color trigger matched")
                return

            if not block_until_match:
                self._set_status("Color trigger not matched, continuing")
                return

            time.sleep(poll_delay)

    def close(self) -> None:
        self._keyboard.close()
