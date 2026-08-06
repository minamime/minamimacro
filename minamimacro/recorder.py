from __future__ import annotations

import threading
import time
from typing import Callable

from pynput import keyboard, mouse

from .input_utils import serialize_button, serialize_key
from .models import ActionType, InputAction


class InputRecorder:
    def __init__(self, should_record_event: Callable[[ActionType, dict], bool] | None = None) -> None:
        self.actions: list[InputAction] = []
        self._running = False
        self._lock = threading.Lock()
        self._keyboard_listener: keyboard.Listener | None = None
        self._mouse_listener: mouse.Listener | None = None
        self._last_time = 0.0
        self._should_record_event = should_record_event

    @property
    def is_running(self) -> bool:
        return self._running

    def clear(self) -> None:
        with self._lock:
            self.actions.clear()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._last_time = time.perf_counter()
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener.start()
        self._mouse_listener.start()

    def stop(self) -> list[InputAction]:
        if not self._running:
            return self.actions
        self._running = False
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
            self._keyboard_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        return self.actions

    def _append_action(self, action_type: ActionType, payload: dict) -> None:
        if not self._running:
            return
        if self._should_record_event is not None and not self._should_record_event(action_type, payload):
            return
        now = time.perf_counter()
        delay = max(0.0, now - self._last_time)
        self._last_time = now
        with self._lock:
            self.actions.append(InputAction(delay=delay, action_type=action_type, payload=payload))

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._append_action(ActionType.KEY_DOWN, {"key": serialize_key(key)})

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._append_action(ActionType.KEY_UP, {"key": serialize_key(key)})

    def _on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        self._append_action(
            ActionType.MOUSE_CLICK,
            {
                "x": x,
                "y": y,
                "button": serialize_button(button),
                "pressed": pressed,
            },
        )

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._append_action(ActionType.MOUSE_SCROLL, {"x": x, "y": y, "dx": dx, "dy": dy})


def capture_next_left_click(on_capture: Callable[[int, int], None]) -> mouse.Listener:
    def _on_click(x: int, y: int, button: mouse.Button, pressed: bool) -> bool | None:
        if button == mouse.Button.left and pressed:
            on_capture(x, y)
            return False
        return None

    listener = mouse.Listener(on_click=_on_click)
    listener.start()
    return listener


def capture_left_clicks(on_capture: Callable[[int, int], None]) -> mouse.Listener:
    def _on_click(x: int, y: int, button: mouse.Button, pressed: bool) -> bool | None:
        if button == mouse.Button.left and pressed:
            on_capture(x, y)
        return None

    listener = mouse.Listener(on_click=_on_click)
    listener.start()
    return listener
