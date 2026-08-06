from __future__ import annotations

import os
from dataclasses import dataclass

from evdev import UInput, ecodes
from pynput.keyboard import Controller as KeyboardController

from .input_utils import deserialize_key


SPECIAL_KEY_MAP = {
    "alt": ecodes.KEY_LEFTALT,
    "alt_l": ecodes.KEY_LEFTALT,
    "alt_r": ecodes.KEY_RIGHTALT,
    "ctrl": ecodes.KEY_LEFTCTRL,
    "ctrl_l": ecodes.KEY_LEFTCTRL,
    "ctrl_r": ecodes.KEY_RIGHTCTRL,
    "shift": ecodes.KEY_LEFTSHIFT,
    "shift_l": ecodes.KEY_LEFTSHIFT,
    "shift_r": ecodes.KEY_RIGHTSHIFT,
    "cmd": ecodes.KEY_LEFTMETA,
    "cmd_l": ecodes.KEY_LEFTMETA,
    "cmd_r": ecodes.KEY_RIGHTMETA,
    "super": ecodes.KEY_LEFTMETA,
    "space": ecodes.KEY_SPACE,
    "enter": ecodes.KEY_ENTER,
    "tab": ecodes.KEY_TAB,
    "backspace": ecodes.KEY_BACKSPACE,
    "delete": ecodes.KEY_DELETE,
    "esc": ecodes.KEY_ESC,
    "caps_lock": ecodes.KEY_CAPSLOCK,
    "up": ecodes.KEY_UP,
    "down": ecodes.KEY_DOWN,
    "left": ecodes.KEY_LEFT,
    "right": ecodes.KEY_RIGHT,
    "home": ecodes.KEY_HOME,
    "end": ecodes.KEY_END,
    "page_up": ecodes.KEY_PAGEUP,
    "page_down": ecodes.KEY_PAGEDOWN,
    "insert": ecodes.KEY_INSERT,
    "media_volume_up": ecodes.KEY_VOLUMEUP,
    "media_volume_down": ecodes.KEY_VOLUMEDOWN,
    "media_volume_mute": ecodes.KEY_MUTE,
}

for idx in range(1, 13):
    SPECIAL_KEY_MAP[f"f{idx}"] = getattr(ecodes, f"KEY_F{idx}")


CHAR_KEY_MAP = {
    **{chr(ord("a") + i): getattr(ecodes, f"KEY_{chr(ord('A') + i)}") for i in range(26)},
    **{str(i): getattr(ecodes, f"KEY_{i}") for i in range(10)},
    " ": ecodes.KEY_SPACE,
    "-": ecodes.KEY_MINUS,
    "=": ecodes.KEY_EQUAL,
    "[": ecodes.KEY_LEFTBRACE,
    "]": ecodes.KEY_RIGHTBRACE,
    "\\": ecodes.KEY_BACKSLASH,
    ";": ecodes.KEY_SEMICOLON,
    "'": ecodes.KEY_APOSTROPHE,
    "`": ecodes.KEY_GRAVE,
    ",": ecodes.KEY_COMMA,
    ".": ecodes.KEY_DOT,
    "/": ecodes.KEY_SLASH,
    "\t": ecodes.KEY_TAB,
    "\n": ecodes.KEY_ENTER,
    "\r": ecodes.KEY_ENTER,
}

SHIFTED_TO_BASE_CHAR = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
    "~": "`",
}


class KeyboardBackendBase:
    name: str = "unknown"

    def press_serialized(self, value: str) -> None:
        raise NotImplementedError

    def release_serialized(self, value: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return


class PynputKeyboardBackend(KeyboardBackendBase):
    name = "pynput"

    def __init__(self) -> None:
        self._keyboard = KeyboardController()

    def press_serialized(self, value: str) -> None:
        self._keyboard.press(deserialize_key(value))

    def release_serialized(self, value: str) -> None:
        self._keyboard.release(deserialize_key(value))


class UInputKeyboardBackend(KeyboardBackendBase):
    name = "uinput"

    def __init__(self) -> None:
        self._uinput = UInput(name="minamimacro-uinput")

    def press_serialized(self, value: str) -> None:
        code = _serialized_to_evdev_code(value)
        self._uinput.write(ecodes.EV_KEY, code, 1)
        self._uinput.syn()

    def release_serialized(self, value: str) -> None:
        code = _serialized_to_evdev_code(value)
        self._uinput.write(ecodes.EV_KEY, code, 0)
        self._uinput.syn()

    def close(self) -> None:
        self._uinput.close()


def _serialized_to_evdev_code(value: str) -> int:
    if value.startswith("special:"):
        raw = value.split(":", 1)[1]
        key_name = raw.replace("Key.", "")
        if key_name in SPECIAL_KEY_MAP:
            return SPECIAL_KEY_MAP[key_name]
        raise ValueError(f"Unsupported special key: {raw}")

    if value.startswith("char:"):
        char = value.split(":", 1)[1]
        if char in SHIFTED_TO_BASE_CHAR:
            char = SHIFTED_TO_BASE_CHAR[char]
        if char.lower() in CHAR_KEY_MAP:
            return CHAR_KEY_MAP[char.lower()]
        raise ValueError(f"Unsupported char key: {char}")

    if value.startswith("vk:"):
        vk = int(value.split(":", 1)[1])
        if 1 <= vk <= 767:
            return vk
        raise ValueError(f"Unsupported vk key: {vk}")

    raise ValueError(f"Unsupported key format: {value}")


@dataclass(slots=True)
class AutoKeyboardBackend:
    backend: KeyboardBackendBase
    warning: str | None = None

    def __init__(self) -> None:
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland_display = os.environ.get("WAYLAND_DISPLAY")

        if session_type == "wayland" or wayland_display:
            try:
                self.backend = UInputKeyboardBackend()
                self.warning = None
                return
            except Exception as exc:
                self.backend = PynputKeyboardBackend()
                self.warning = (
                    "Wayland keyboard injection fallback to pynput; "
                    f"uinput unavailable ({exc})."
                )
                return

        self.backend = PynputKeyboardBackend()
        self.warning = None

    @property
    def name(self) -> str:
        return self.backend.name

    def press_serialized(self, value: str) -> None:
        self.backend.press_serialized(value)

    def release_serialized(self, value: str) -> None:
        self.backend.release_serialized(value)

    def close(self) -> None:
        self.backend.close()
