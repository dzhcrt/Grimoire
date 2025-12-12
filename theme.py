from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor


def apply_dark_theme(app: QApplication) -> None:
    palette = QPalette()

    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(64, 128, 255))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))

    app.setPalette(palette)

    app.setStyleSheet(
        """
        QMainWindow {
            background-color: #1e1e1e;
        }
        QTreeWidget {
            background-color: #252525;
            alternate-background-color: #2f2f2f;
            color: #e0e0e0;
            border: 1px solid #444;
        }
        QTreeWidget::item:selected {
            background-color: #3c6cff;
            color: #000000;
        }
        QGroupBox {
            border: 1px solid #555;
            border-radius: 6px;
            margin-top: 10px;
            padding: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 3px 0 3px;
        }
        QTextEdit {
            background-color: #252525;
            color: #e0e0e0;
            border: 1px solid #555;
        }
        QPushButton {
            background-color: #3a3a3a;
            color: #e0e0e0;
            border-radius: 4px;
            padding: 4px 10px;
        }
        QPushButton:hover {
            background-color: #505050;
        }
        QPushButton:pressed {
            background-color: #606060;
        }
        QLabel {
            color: #e0e0e0;
        }
        QMenu {
            background-color: #252525;
            color: #e0e0e0;
            border: 1px solid #444;
        }
        QMenu::item {
            padding: 4px 20px 4px 24px;
            background-color: transparent;
        }
        QMenu::item:selected {
            background-color: #3c6cff;
            color: #000000;
        }
        QMenu::separator {
            height: 1px;
            background: #444;
            margin-left: 4px;
            margin-right: 4px;
        }
        """
    )
