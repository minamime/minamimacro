from __future__ import annotations

from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button


def serialize_key(key: Key | KeyCode) -> str:
    if isinstance(key, KeyCode) and key.char is not None:
        return f"char:{key.char}"
    if isinstance(key, KeyCode) and getattr(key, "vk", None) is not None:
        return f"vk:{int(key.vk)}"
    return f"special:{str(key)}"


def deserialize_key(value: str) -> Key | KeyCode:
    if value.startswith("char:"):
        char = value.split(":", 1)[1]
        return KeyCode.from_char(char)
    if value.startswith("vk:"):
        raw = value.split(":", 1)[1]
        return KeyCode.from_vk(int(raw))
    if value.startswith("special:"):
        raw = value.split(":", 1)[1]
        key_name = raw.replace("Key.", "")
        if hasattr(Key, key_name):
            return getattr(Key, key_name)
    raise ValueError(f"Unsupported key format: {value}")


def serialize_button(button: Button) -> str:
    return str(button)


def deserialize_button(value: str) -> Button:
    name = value.replace("Button.", "")
    if hasattr(Button, name):
        return getattr(Button, name)
    raise ValueError(f"Unsupported button format: {value}")
