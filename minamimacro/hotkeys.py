from __future__ import annotations

from collections.abc import Callable

from pynput import keyboard


class GlobalHotkey:
    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        self._listener: keyboard.Listener | None = None
        self._hotkey = keyboard.HotKey(keyboard.HotKey.parse(hotkey), on_toggle)

    def start(self) -> None:
        if self._listener is not None:
            return

        def _for_canonical(handler):
            return lambda key: handler(self._listener.canonical(key))

        self._listener = keyboard.Listener(
            on_press=_for_canonical(self._hotkey.press),
            on_release=_for_canonical(self._hotkey.release),
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._listener = None

    def update_hotkey(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        was_running = self._listener is not None
        self.stop()
        self._hotkey = keyboard.HotKey(keyboard.HotKey.parse(hotkey), on_toggle)
        if was_running:
            self.start()
