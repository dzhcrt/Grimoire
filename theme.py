import json
import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor


ROLE_MAP = {
    "Window": QPalette.ColorRole.Window,
    "WindowText": QPalette.ColorRole.WindowText,
    "Base": QPalette.ColorRole.Base,
    "AlternateBase": QPalette.ColorRole.AlternateBase,
    "ToolTipBase": QPalette.ColorRole.ToolTipBase,
    "ToolTipText": QPalette.ColorRole.ToolTipText,
    "Text": QPalette.ColorRole.Text,
    "Button": QPalette.ColorRole.Button,
    "ButtonText": QPalette.ColorRole.ButtonText,
    "BrightText": QPalette.ColorRole.BrightText,
    "Highlight": QPalette.ColorRole.Highlight,
    "HighlightedText": QPalette.ColorRole.HighlightedText,
}


def apply_theme(app: QApplication, theme: dict) -> None:
    if not theme:
        return

    palette = QPalette()
    palette_data = theme.get("palette", {})
    for role_name, color_value in palette_data.items():
        role = ROLE_MAP.get(role_name)
        if role is None:
            continue
        palette.setColor(role, QColor(color_value))

    app.setPalette(palette)
    app.setStyleSheet(theme.get("stylesheet", ""))


def load_themes(theme_dir: str) -> list[dict]:
    themes: list[dict] = []
    if not os.path.isdir(theme_dir):
        return themes

    for entry in sorted(os.listdir(theme_dir)):
        if not entry.lower().endswith(".json"):
            continue
        path = os.path.join(theme_dir, entry)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        theme_key = os.path.splitext(entry)[0]
        data["key"] = theme_key
        data.setdefault("name", theme_key)
        themes.append(data)

    return themes
