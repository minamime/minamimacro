from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .models import ActionType, InputAction, MacroSettings

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "configs"


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def serialize_actions(actions: list[InputAction]) -> list[dict[str, Any]]:
    return [
        {
            "delay": action.delay,
            "action_type": action.action_type.value,
            "payload": action.payload,
        }
        for action in actions
    ]


def deserialize_actions(raw_actions: list[dict[str, Any]]) -> list[InputAction]:
    actions: list[InputAction] = []
    for item in raw_actions:
        action_type = ActionType(item["action_type"])
        actions.append(
            InputAction(
                delay=float(item.get("delay", 0.0)),
                action_type=action_type,
                payload=dict(item.get("payload", {})),
            )
        )
    return actions


def settings_to_dict(settings: MacroSettings) -> dict[str, Any]:
    return {
        "cursor_speed": settings.cursor_speed,
        "cursor_speed_variation": settings.cursor_speed_variation,
        "action_delay_variation_ms": settings.action_delay_variation_ms,
        "variation_x": settings.variation_x,
        "variation_y": settings.variation_y,
        "loop_delay": settings.loop_delay,
    }


def settings_from_dict(data: dict[str, Any]) -> MacroSettings:
    return MacroSettings(
        cursor_speed=float(data.get("cursor_speed", 1200.0)),
        cursor_speed_variation=max(0.0, float(data.get("cursor_speed_variation", 0.0))),
        action_delay_variation_ms=max(0.0, float(data.get("action_delay_variation_ms", 0.0))),
        variation_x=max(0, int(data.get("variation_x", 0))),
        variation_y=max(0, int(data.get("variation_y", 0))),
        loop_delay=max(0.0, float(data.get("loop_delay", 0.1))),
    )


def build_config_payload(actions: list[InputAction], settings: MacroSettings, hotkey: str) -> dict[str, Any]:
    return {
        "version": 1,
        "hotkey": hotkey,
        "settings": settings_to_dict(settings),
        "actions": serialize_actions(actions),
    }


def _resolve_config_file(path: Path) -> Path:
    if path.is_dir():
        return path / "config.json"
    return path


def save_config_bundle(bundle_dir: Path, payload: dict[str, Any], reference_image_path: Path | None = None) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)

    payload_copy = dict(payload)
    if reference_image_path is not None and reference_image_path.exists():
        image_name = f"reference_image{reference_image_path.suffix.lower()}"
        copied_image_path = bundle_dir / image_name
        shutil.copy2(reference_image_path, copied_image_path)
        payload_copy["color_reference_image"] = image_name
    else:
        payload_copy.pop("color_reference_image", None)

    config_path = bundle_dir / "config.json"
    config_path.write_text(json.dumps(payload_copy, indent=2), encoding="utf-8")
    return config_path


def load_config_bundle(path: Path) -> tuple[dict[str, Any], Path | None]:
    config_path = _resolve_config_file(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    image_path: Path | None = None
    image_name = payload.get("color_reference_image")
    if isinstance(image_name, str) and image_name:
        candidate = config_path.parent / image_name
        if candidate.exists():
            image_path = candidate

    return payload, image_path
