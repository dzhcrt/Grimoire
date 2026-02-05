import os

from PyQt6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QMenu,
    QInputDialog,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, QPoint, QObject, pyqtSignal

from fb2_utils import extract_fb2_title


class BookTreeWidget(QTreeWidget):
    """
    QTreeWidget с:
    - drag'n'drop для книг (.fb2) с реальным перемещением файлов;
    - контекстным меню (создать/удалить папку);
    - полем root_path для понимания, где корень на диске.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.root_path: str | None = None
        self.language = "ru"
        self.translations = {
            "ru": {
                "move_error_title": "Ошибка перемещения",
                "move_error_body": "Не удалось переместить файл:\n{old}\n→ {new}\n\n{error}",
                "create_folder": "Создать папку",
                "delete_folder": "Удалить папку",
                "create_folder_title": "Создать папку",
                "create_folder_prompt": "Имя новой папки:",
                "folder_exists_title": "Ошибка",
                "folder_exists_body": "Такая папка уже существует.",
                "create_folder_error_title": "Ошибка создания папки",
                "delete_not_allowed_title": "Нельзя удалить",
                "delete_not_allowed_body": "Папка не пуста. Сначала удалите или перенесите файлы/папки.",
                "folder_access_error_title": "Ошибка доступа к папке",
                "delete_folder_title": "Удаление папки",
                "delete_folder_body": "Удалить папку?\n{path}",
                "delete_folder_error_title": "Ошибка удаления папки",
            },
            "en": {
                "move_error_title": "Move error",
                "move_error_body": "Failed to move file:\n{old}\n→ {new}\n\n{error}",
                "create_folder": "Create folder",
                "delete_folder": "Delete folder",
                "create_folder_title": "Create folder",
                "create_folder_prompt": "New folder name:",
                "folder_exists_title": "Error",
                "folder_exists_body": "That folder already exists.",
                "create_folder_error_title": "Create folder error",
                "delete_not_allowed_title": "Cannot delete",
                "delete_not_allowed_body": "The folder is not empty. Delete or move files/folders first.",
                "folder_access_error_title": "Folder access error",
                "delete_folder_title": "Delete folder",
                "delete_folder_body": "Delete folder?\n{path}",
                "delete_folder_error_title": "Delete folder error",
            },
        }

        # Drag'n'drop настройки
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        # Контекстное меню по ПКМ
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def set_language(self, language: str):
        if language in self.translations:
            self.language = language

    def t(self, key: str) -> str:
        return self.translations.get(self.language, self.translations["ru"]).get(key, key)

    # --- drag'n'drop: переопределяем dropEvent для перемещения файлов ---

    def dropEvent(self, event):
        """
        Перед тем, как дать QTreeWidget всё перетащить внутри дерева,
        запоминаем, какие элементы и с какими путями мы двигали.
        После super().dropEvent(...) дерево уже обновлено, и мы можем
        на основе нового родителя понять, куда двигать файлы на диске.
        """
        moved_items = []

        for item in self.selectedItems():
            old_path = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(old_path, str) and os.path.isfile(old_path) and old_path.lower().endswith(".fb2"):
                moved_items.append((item, old_path))

        super().dropEvent(event)

        self._move_books_on_disk_after_drop(moved_items)

    def _move_books_on_disk_after_drop(self, moved_items):
        if not self.root_path:
            return

        for item, old_path in moved_items:
            parent = item.parent()
            if parent is None:
                base_dir = self.root_path
            else:
                parent_path = parent.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(parent_path, str) and os.path.isdir(parent_path):
                    base_dir = parent_path
                elif isinstance(parent_path, str) and os.path.isfile(parent_path):
                    base_dir = os.path.dirname(parent_path)
                else:
                    base_dir = self.root_path

            new_path = os.path.join(base_dir, os.path.basename(old_path))

            if new_path == old_path:
                item.setData(0, Qt.ItemDataRole.UserRole, new_path)
                continue

            try:
                os.replace(old_path, new_path)
                item.setData(0, Qt.ItemDataRole.UserRole, new_path)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    self.t("move_error_title"),
                    self.t("move_error_body").format(old=old_path, new=new_path, error=e),
                )

    # --- контекстное меню (создать / удалить папку) ---

    def _on_context_menu(self, pos: QPoint):
        item = self.itemAt(pos)
        global_pos = self.viewport().mapToGlobal(pos)

        menu = QMenu(self)

        create_action = menu.addAction(self.t("create_folder"))
        delete_action = None

        item_path = None
        is_folder = False
        is_root = False

        if item is not None:
            item_path = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(item_path, str) and os.path.isdir(item_path):
                is_folder = True
                if self.root_path and os.path.abspath(item_path) == os.path.abspath(self.root_path):
                    is_root = True

        if is_folder and not is_root:
            delete_action = menu.addAction(self.t("delete_folder"))

        action = menu.exec(global_pos)
        if action is None:
            return

        if action == create_action:
            self._create_folder(item, item_path, is_folder)
        elif delete_action is not None and action == delete_action:
            self._delete_folder(item, item_path)

    def _create_folder(self, item, item_path, is_folder):
        if not self.root_path:
            return

        name, ok = QInputDialog.getText(
            self,
            self.t("create_folder_title"),
            self.t("create_folder_prompt"),
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        if item is None:
            base_dir = self.root_path
            parent_item = self.topLevelItem(0)
        else:
            if is_folder and isinstance(item_path, str) and os.path.isdir(item_path):
                base_dir = item_path
                parent_item = item
            else:
                base_dir = os.path.dirname(item_path)
                parent_item = item.parent() or self.topLevelItem(0)

        new_path = os.path.join(base_dir, name)
        if os.path.exists(new_path):
            QMessageBox.warning(
                self,
                self.t("folder_exists_title"),
                self.t("folder_exists_body"),
            )
            return

        try:
            os.makedirs(new_path)
        except Exception as e:
            QMessageBox.warning(self, self.t("create_folder_error_title"), str(e))
            return

        new_item = QTreeWidgetItem([name])
        new_item.setData(0, Qt.ItemDataRole.UserRole, new_path)
        parent_item.addChild(new_item)

    def _delete_folder(self, item, item_path):
        if not isinstance(item_path, str) or not os.path.isdir(item_path):
            return

        try:
            if os.listdir(item_path):
                QMessageBox.information(
                    self,
                    self.t("delete_not_allowed_title"),
                    self.t("delete_not_allowed_body"),
                )
                return
        except Exception as e:
            QMessageBox.warning(self, self.t("folder_access_error_title"), str(e))
            return

        reply = QMessageBox.question(
            self,
            self.t("delete_folder_title"),
            self.t("delete_folder_body").format(path=item_path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            os.rmdir(item_path)
        except Exception as e:
            QMessageBox.warning(self, self.t("delete_folder_error_title"), str(e))
            return

        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self.indexOfTopLevelItem(item)
            self.takeTopLevelItem(idx)


class MetadataWorker(QObject):
    """В отдельном потоке: читает короткое название для дерева (title из fb2)."""
    titleReady = pyqtSignal(QTreeWidgetItem, str)
    finished = pyqtSignal()

    def __init__(self, tasks: list[tuple[str, QTreeWidgetItem]]):
        super().__init__()
        self.tasks = tasks
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        for path, item in self.tasks:
            if self._stopped:
                break
            title = extract_fb2_title(path)
            self.titleReady.emit(item, title)
        self.finished.emit()
