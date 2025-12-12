import sys
import os
import json
import math  # пока не используется, но пусть будет — вдруг пригодится

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QTreeWidgetItem,
    QMessageBox,
    QSplitter,
    QLabel,
    QTextEdit,
    QStackedWidget,
    QLineEdit,
    QSizePolicy,
    QScrollArea,
)
from PyQt6.QtCore import (
    Qt,
    QThread,
    QUrl,
    QTimer,
    pyqtSignal,
    QEvent,
)
from PyQt6.QtGui import QPixmap, QFont, QDesktopServices, QIcon

from fb2_utils import BookInfo, parse_fb2_book_info
from theme import apply_dark_theme
from tree_view import BookTreeWidget, MetadataWorker


# ------------ базовые пути: работают и в скрипте, и в собранном exe ------------

def get_base_dir() -> str:
    """
    Папка, где лежит exe (если собрано PyInstaller'ом)
    или сам main.py (при обычном запуске).
    """
    if getattr(sys, "frozen", False):
        # Запущено из собранного exe
        return os.path.dirname(sys.executable)
    else:
        # Обычный запуск скрипта
        return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
ICON_PATH = os.path.join(BASE_DIR, "grimoire.ico")
CACHE_PATH = os.path.join(BASE_DIR, "fb2_tree_cache.json")


# ---------- Текстовое поле для чтения: без прокрутки + сигнал ресайза ----------

class ReaderTextEdit(QTextEdit):
    """
    QTextEdit, который:
    - шлёт сигнал при изменении размера viewport'а (для пересчёта страниц);
    - умеет отключать прокрутку колёсиком.
    """
    viewportResized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scroll_enabled: bool = True

        # убираем скроллбары по умолчанию
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewportResized.emit()

    def wheelEvent(self, event):
        # если прокрутка запрещена — глушим
        if not self.scroll_enabled:
            event.accept()
            return
        super().wheelEvent(event)


# ---------- Grimoire ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Явно разрешаем менять размер окна по обоим направлениям
        self.setMinimumSize(600, 400)
        self.setMaximumSize(16777215, 16777215)

        self.setWindowTitle("Grimoire")
        self.resize(1000, 600)

        # Кеш подробной инфы по книгам
        self.book_info_cache: dict[str, BookInfo] = {}
        self.current_book_path: str | None = None

        # Прогресс чтения: путь -> ratio (0..1)
        self.book_progress: dict[str, float] = {}

        # Флаг: в режиме чтения или на странице инфо
        self.is_reading: bool = False

        # Текст текущей книги и страницы
        self.current_full_text: str | None = None
        self.pages: list[str] = []
        self.current_page_index: int = 0

        # Кеш дерева / UI
        self.app_dir = BASE_DIR
        self.cache_path = CACHE_PATH
        self.current_root_path: str | None = None

        # Флаг для восстановления максимизации после show()
        self._restore_maximized = False

        # ---------- UI ----------

        central = QWidget()
        central.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Expanding)
        )
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # Кнопки сверху
        btn_layout = QHBoxLayout()
        root_layout.addLayout(btn_layout)

        self.btn_choose = QPushButton("Выбрать папку")
        self.btn_choose.clicked.connect(self.choose_folder)
        btn_layout.addWidget(self.btn_choose)

        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.clicked.connect(self.refresh_current_folder)
        btn_layout.addWidget(self.btn_refresh)

        btn_layout.addStretch()

        # Splitter: слева дерево, справа стэк (инфо/ридер)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(self.splitter)

        # Лево: дерево
        self.book_tree = BookTreeWidget()
        self.book_tree.setHeaderLabels(["Название"])
        self.splitter.addWidget(self.book_tree)

        # Право: стэк (без лишних QScrollArea выше)
        self.stack = QStackedWidget()
        self.splitter.addWidget(self.stack)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)

        # ---------- Страница ИНФО (единый прокручиваемый блок) ----------

        self.info_page = QWidget()
        info_layout = QVBoxLayout(self.info_page)

        # ScrollArea, в котором ВСЯ информация о книге скроллится как единый блок
        self.info_scroll = QScrollArea()
        self.info_scroll.setWidgetResizable(True)
        info_layout.addWidget(self.info_scroll)

        self.info_content = QWidget()
        content_layout = QVBoxLayout(self.info_content)
        self.info_scroll.setWidget(self.info_content)

        # Заголовок
        self.detail_title = QLabel("Выберите книгу")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        self.detail_title.setFont(title_font)
        self.detail_title.setWordWrap(True)
        content_layout.addWidget(self.detail_title)

        # Метаданные
        self.detail_meta = QLabel("")
        meta_font = QFont()
        meta_font.setPointSize(10)
        self.detail_meta.setFont(meta_font)
        self.detail_meta.setWordWrap(True)
        content_layout.addWidget(self.detail_meta)

        # Блок: обложка + кнопка открыть + прогресс + описание
        self.book_block = QWidget()
        block_layout = QVBoxLayout(self.book_block)

        # Обложка
        self.detail_cover = QLabel()
        self.detail_cover.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.detail_cover.setMaximumWidth(300)
        self.detail_cover.setScaledContents(False)
        self.detail_cover.setStyleSheet(
            """
            QLabel {
                border: 1px solid #555;
                border-radius: 6px;
                background-color: #202020;
                padding: 6px;
            }
            """
        )
        block_layout.addWidget(self.detail_cover, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Панель: открыть + прогресс
        open_layout = QHBoxLayout()

        self.btn_open_book = QPushButton("Открыть книгу")
        self.btn_open_book.clicked.connect(self.open_current_book)
        self.btn_open_book.setEnabled(False)
        open_layout.addWidget(self.btn_open_book)

        self.lbl_progress_info = QLabel("0%")
        open_layout.addWidget(self.lbl_progress_info)

        open_layout.addStretch()
        block_layout.addLayout(open_layout)

        # Описание (краткое) из fb2
        self.info_desc = QTextEdit()
        self.info_desc.setReadOnly(True)
        # убираем собственные скроллбары, чтобы скроллился только общий блок
        self.info_desc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.info_desc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        block_layout.addWidget(self.info_desc)

        content_layout.addWidget(self.book_block)
        self.book_block.setVisible(False)

        self.stack.addWidget(self.info_page)

        # ---------- Страница РИДЕРА ----------

        self.reader_page = QWidget()
        reader_layout = QVBoxLayout(self.reader_page)

        controls_layout = QHBoxLayout()

        # Кнопка назад к инфо
        self.btn_back_info = QPushButton("К информации")
        self.btn_back_info.clicked.connect(self.back_to_info)
        controls_layout.addWidget(self.btn_back_info)

        # Прогресс (%)
        self.lbl_progress_read = QLabel("0%")
        controls_layout.addWidget(self.lbl_progress_read)

        controls_layout.addStretch()

        # Навигация по страницам: ⟨ [page_edit] / [total] ⟩
        self.btn_prev_page = QPushButton("⟨")
        self.btn_prev_page.clicked.connect(self.go_prev_page)
        self.btn_prev_page.setEnabled(False)
        controls_layout.addWidget(self.btn_prev_page)

        self.page_edit = QLineEdit("0")
        self.page_edit.setFixedWidth(50)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.setEnabled(False)
        self.page_edit.returnPressed.connect(self.on_page_edit_return)
        controls_layout.addWidget(self.page_edit)

        self.lbl_page_total = QLabel("/0")
        controls_layout.addWidget(self.lbl_page_total)

        self.btn_next_page = QPushButton("⟩")
        self.btn_next_page.clicked.connect(self.go_next_page)
        self.btn_next_page.setEnabled(False)
        controls_layout.addWidget(self.btn_next_page)

        reader_layout.addLayout(controls_layout)

        # Текст книги (одна страница за раз, без скролла)
        self.reader_edit = ReaderTextEdit()
        self.reader_edit.setReadOnly(True)
        self.reader_edit.scroll_enabled = False  # отключаем прокрутку колёсиком
        reader_layout.addWidget(self.reader_edit)

        self.stack.addWidget(self.reader_page)

        # Начально показываем страницу инфо
        self.stack.setCurrentWidget(self.info_page)

        # Сигнал выбора в дереве
        self.book_tree.itemSelectionChanged.connect(self.on_tree_selection_changed)

        # Ресайз области чтения -> перепагинация
        self.reader_edit.viewportResized.connect(self.on_reader_resized)

        # Фильтр событий для стрелок влево/вправо и блокировки scroll-клавиш
        self.reader_edit.installEventFilter(self)

        # Асинхронные метаданные для дерева
        self.metadata_tasks: list[tuple[str, QTreeWidgetItem]] = []
        self.metadata_thread: QThread | None = None
        self.metadata_worker: MetadataWorker | None = None

        # При старте пробуем кеш
        if not self.load_cache():
            self.ask_initial_folder()
        else:
            root_item = self.book_tree.topLevelItem(0)
            if root_item:
                self.book_tree.expandItem(root_item)
            self.select_first_book()

    # ---------- Event filter для клавиш в ридере ----------

    def eventFilter(self, obj, event):
        if obj is self.reader_edit and self.is_reading:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                # Блокируем scroll-клавиши
                if key in (
                    Qt.Key.Key_Up,
                    Qt.Key.Key_Down,
                    Qt.Key.Key_PageUp,
                    Qt.Key.Key_PageDown,
                    Qt.Key.Key_Home,
                    Qt.Key.Key_End,
                ):
                    return True
                # Стрелки влево/вправо — листание страниц
                if key == Qt.Key.Key_Left:
                    self.go_prev_page()
                    return True
                if key == Qt.Key.Key_Right:
                    self.go_next_page()
                    return True

        return super().eventFilter(obj, event)

    # ---------- Сохранение состояния при закрытии ----------

    def closeEvent(self, event):
        self.save_cache()
        super().closeEvent(event)

    # ---------- Асинхронный воркер для заголовков в дереве ----------

    def cancel_metadata_worker(self):
        if self.metadata_worker is not None:
            self.metadata_worker.stop()

        if self.metadata_thread is not None:
            self.metadata_thread.quit()
            self.metadata_thread.wait()

        self.metadata_worker = None
        self.metadata_thread = None

    def start_metadata_worker(self):
        if not self.metadata_tasks:
            self.save_cache()
            return

        self.cancel_metadata_worker()

        self.metadata_thread = QThread(self)
        self.metadata_worker = MetadataWorker(self.metadata_tasks)
        self.metadata_worker.moveToThread(self.metadata_thread)

        self.metadata_thread.started.connect(self.metadata_worker.run)
        self.metadata_worker.titleReady.connect(self.on_title_ready)
        self.metadata_worker.finished.connect(self.on_metadata_finished)
        self.metadata_worker.finished.connect(self.metadata_thread.quit)
        self.metadata_worker.finished.connect(self.metadata_worker.deleteLater)
        self.metadata_thread.finished.connect(self.on_metadata_thread_finished)

        self.metadata_thread.start()

    def on_title_ready(self, item: QTreeWidgetItem, title: str):
        item.setText(0, title)

    def on_metadata_finished(self):
        self.save_cache()

    def on_metadata_thread_finished(self):
        self.metadata_thread = None
        self.metadata_worker = None

    # ---------- Кеш дерева + состояния UI + прогресса чтения ----------

    def save_cache(self):
        if not self.current_root_path:
            return

        root_item = self.book_tree.topLevelItem(0)
        if root_item is None:
            return

        books = []

        def traverse(item: QTreeWidgetItem):
            path = item.data(0, Qt.ItemDataRole.UserRole)

            if isinstance(path, str) and os.path.isfile(path):
                rel = os.path.relpath(path, self.current_root_path)
                title = item.text(0)
                abs_path = os.path.abspath(path)
                ratio = float(self.book_progress.get(abs_path, 0.0))
                books.append({"rel_path": rel, "title": title, "progress": ratio})

            for i in range(item.childCount()):
                traverse(item.child(i))

        traverse(root_item)

        ui_state = {
            "is_maximized": self.isMaximized(),
            "splitter_sizes": self.splitter.sizes(),
        }

        data = {
            "root_path": self.current_root_path,
            "books": books,
            "ui": ui_state,
        }

        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка сохранения кеша дерева", str(e))

    def load_cache(self) -> bool:
        if not os.path.exists(self.cache_path):
            return False

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
           	 data = json.load(f)
        except Exception:
            return False

        root_path = data.get("root_path")
        books = data.get("books")

        if not root_path or not isinstance(books, list):
            return False
        if not os.path.isdir(root_path):
            return False

        self.current_root_path = root_path
        self.book_tree.clear()
        self.book_tree.root_path = self.current_root_path
        self.book_progress.clear()

        root_item = QTreeWidgetItem([os.path.basename(root_path)])
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)

        item_map: dict[tuple, QTreeWidgetItem] = {(): root_item}

        for entry in books:
            rel_path = entry.get("rel_path")
            title = entry.get("title") or os.path.basename(rel_path or "")
            progress = float(entry.get("progress", 0.0))
            if not rel_path:
                continue

            parts = rel_path.split(os.sep)
            if not parts:
                continue

            folders, filename = parts[:-1], parts[-1]
            current_key = ()
            current_item = root_item
            full_dir_path = root_path

            for folder in folders:
                current_key = current_key + (folder,)
                if current_key in item_map:
                    current_item = item_map[current_key]
                    full_dir_path = os.path.join(full_dir_path, folder)
                    continue

                folder_item = QTreeWidgetItem([folder])
                full_dir_path = os.path.join(full_dir_path, folder)
                folder_item.setData(0, Qt.ItemDataRole.UserRole, full_dir_path)
                current_item.addChild(folder_item)
                item_map[current_key] = folder_item
                current_item = folder_item

            full_file_path = os.path.join(root_path, *folders, filename)
            book_item = QTreeWidgetItem([title])
            book_item.setData(0, Qt.ItemDataRole.UserRole, full_file_path)
            current_item.addChild(book_item)

            # восстановим прогресс
            self.book_progress[os.path.abspath(full_file_path)] = float(progress)

        self.book_tree.addTopLevelItem(root_item)
        self.book_tree.expandItem(root_item)

        ui_state = data.get("ui")
        self.apply_ui_state(ui_state)

        return True

    def apply_ui_state(self, ui_state: dict | None):
        if not ui_state:
            return

        sizes = ui_state.get("splitter_sizes")
        if isinstance(sizes, list) and len(sizes) == 2:
            try:
                self.splitter.setSizes([int(sizes[0]), int(sizes[1])])
            except Exception:
                pass

        is_maximized = ui_state.get("is_maximized", False)
        self._restore_maximized = bool(is_maximized)

    # ---------- Выбор первой книги ----------

    def select_first_book(self):
        root = self.book_tree.topLevelItem(0)
        if root is None:
            return

        item = self._find_first_book_item(root)
        if item is not None:
            self.book_tree.setCurrentItem(item)
            self.book_tree.scrollToItem(item)

    def _find_first_book_item(self, parent: QTreeWidgetItem) -> QTreeWidgetItem | None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            path = child.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(path, str) and os.path.isfile(path) and path.lower().endswith(".fb2"):
                return child
            res = self._find_first_book_item(child)
            if res is not None:
                return res
        return None

    # ---------- Основная логика ----------

    def ask_initial_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку с FB2 книгами (первый запуск)",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return
        self.build_tree_from_scan(folder)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку с FB2 книгами",
            self.current_root_path or "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return
        self.build_tree_from_scan(folder)

    def refresh_current_folder(self):
        if not self.current_root_path or not os.path.isdir(self.current_root_path):
            QMessageBox.information(
                self,
                "Обновление",
                "Текущая папка не задана или недоступна. Выберите папку заново.",
            )
            self.choose_folder()
            return

        self.build_tree_from_scan(self.current_root_path)

    def build_tree_from_scan(self, root_path: str):
        if not root_path:
            return

        self.current_root_path = root_path
        self.book_tree.root_path = self.current_root_path

        self.cancel_metadata_worker()
        self.book_tree.clear()
        self.metadata_tasks = []
        self.book_info_cache.clear()
        self.current_book_path = None
        self.is_reading = False
        self.current_full_text = None
        self.pages = []
        self.current_page_index = 0
        self.show_book_info(None, None)

        root_item = QTreeWidgetItem([os.path.basename(root_path)])
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
        has_books = self._add_dir_items(root_item, root_path)

        self.book_tree.addTopLevelItem(root_item)
        self.book_tree.expandItem(root_item)

        if not has_books:
            QMessageBox.information(self, "Результат", "FB2 файлы не найдены.")
            self.save_cache()
            return

        self.start_metadata_worker()
        self.select_first_book()

    def _add_dir_items(self, parent_item: QTreeWidgetItem, path: str) -> bool:
        has_books = False

        try:
            entries = list(os.scandir(path))
        except PermissionError:
            return False

        dirs = [
            e for e in entries
            if e.is_dir() and not e.name.startswith(".cal")
        ]
        files = [e for e in entries if e.is_file()]

        # Папки — всегда добавляем
        for d in sorted(dirs, key=lambda e: e.name.lower()):
            dir_item = QTreeWidgetItem([d.name])
            dir_item.setData(0, Qt.ItemDataRole.UserRole, d.path)

            child_has_books = self._add_dir_items(dir_item, d.path)

            parent_item.addChild(dir_item)

            if child_has_books:
                has_books = True

        # Файлы .fb2
        for f in sorted(files, key=lambda e: e.name.lower()):
            if not f.name.lower().endswith(".fb2"):
                continue
            book_item = QTreeWidgetItem([f.name])
            book_item.setData(0, Qt.ItemDataRole.UserRole, f.path)
            parent_item.addChild(book_item)
            has_books = True
            self.metadata_tasks.append((f.path, book_item))

        return has_books

    # ---------- Обработка выбора в дереве ----------

    def on_tree_selection_changed(self):
        items = self.book_tree.selectedItems()
        if not items:
            self.show_book_info(None, None)
            return

        item = items[0]
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not os.path.isfile(path) or not path.lower().endswith(".fb2"):
            self.show_book_info(None, None)
            return

        self.current_book_path = path

        if path in self.book_info_cache:
            info = self.book_info_cache[path]
        else:
            info = parse_fb2_book_info(path)
            self.book_info_cache[path] = info

        # При выборе книги показываем страницу инфо
        self.is_reading = False
        self.stack.setCurrentWidget(self.info_page)
        self.show_book_info(info, path)

    def show_book_info(self, info: BookInfo | None, path: str | None):
        if info is None:
            self.detail_title.setText("Выберите книгу")
            self.detail_meta.setText("")
            self.info_desc.setPlainText("")
            self.detail_cover.clear()
            self.btn_open_book.setEnabled(False)
            self.book_block.setVisible(False)
            self.lbl_progress_info.setText("0%")
            self.lbl_progress_read.setText("0%")
            self.page_edit.setText("0")
            self.lbl_page_total.setText("/0")
            self.page_edit.setEnabled(False)
            self.btn_prev_page.setEnabled(False)
            self.btn_next_page.setEnabled(False)
            return

        self.book_block.setVisible(True)
        self.btn_open_book.setEnabled(path is not None)

        # Заголовок
        if info.title:
            self.detail_title.setText(info.title)
        elif path:
            self.detail_title.setText(os.path.basename(path))
        else:
            self.detail_title.setText("Информация о книге")

        # Метаданные
        meta_parts = []
        if info.authors:
            meta_parts.append("Автор(ы): " + ", ".join(info.authors))
        if info.genres:
            meta_parts.append("Жанр(ы): " + ", ".join(info.genres))
        if info.publisher:
            meta_parts.append("Издательство: " + info.publisher)
        if info.date:
            meta_parts.append("Дата: " + info.date)
        if info.lang:
            meta_parts.append("Язык: " + info.lang)

        self.detail_meta.setText("\n".join(meta_parts))

        # Описание
        if info.description:
            self.info_desc.setPlainText(info.description)
        else:
            self.info_desc.setPlainText("")

        # Обложка
        if info.cover_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(info.cover_bytes):
                if pixmap.width() > 300:
                    pixmap = pixmap.scaledToWidth(
                        300, Qt.TransformationMode.SmoothTransformation
                    )
                self.detail_cover.setPixmap(pixmap)
            else:
                self.detail_cover.clear()
        else:
            self.detail_cover.clear()

        # Прогресс чтения для этой книги
        if path:
            ratio = float(self.book_progress.get(os.path.abspath(path), 0.0))
            percent = int(round(ratio * 100))
            self.lbl_progress_info.setText(f"{percent}%")
            self.lbl_progress_read.setText(f"{percent}%")
        else:
            self.lbl_progress_info.setText("0%")
            self.lbl_progress_read.setText("0%")

        # Пока не в режиме чтения — страниц нет
        self.page_edit.setText("0")
        self.lbl_page_total.setText("/0")
        self.page_edit.setEnabled(False)
        self.btn_prev_page.setEnabled(False)
        self.btn_next_page.setEnabled(False)

    # ---------- Пагинация текста ----------

    def paginate_current_text(self, ratio: float):
        """
        Разбивает current_full_text на страницы в зависимости от размеров reader_edit.
        ratio (0..1) — доля прогресса, на которой надо оказаться после перепагинации.
        """
        if not self.current_full_text:
            self.pages = [""]
            self.current_page_index = 0
            self.show_current_page()
            return

        fm = self.reader_edit.fontMetrics()
        viewport = self.reader_edit.viewport()
        width = max(1, viewport.width())
        height = max(1, viewport.height())

        # грубая оценка вместимости
        avg_char_w = max(1, fm.averageCharWidth())
        line_h = max(1, fm.lineSpacing())

        chars_per_line = max(20, width // avg_char_w)
        lines_per_page = max(3, height // line_h)
        capacity = chars_per_line * lines_per_page

        text = self.current_full_text
        pages: list[str] = []
        i = 0
        n = len(text)

        while i < n:
            end = min(i + capacity, n)
            # стараемся не резать слово: ищем пробел ближе к концу
            split_from = min(n, i + int(capacity * 0.8))
            split_pos = text.rfind(" ", split_from, end)
            if split_pos == -1 or split_pos <= i:
                split_pos = end
            page_text = text[i:split_pos].strip()
            pages.append(page_text)
            i = split_pos

        if not pages:
            pages = [""]

        self.pages = pages

        if len(pages) == 1:
            self.current_page_index = 0
        else:
            ratio = max(0.0, min(1.0, ratio))
            self.current_page_index = int(round(ratio * (len(pages) - 1)))

        self.show_current_page()

    def show_current_page(self):
        """Отображает текущую страницу и обновляет прогресс/номер."""
        if not self.pages:
            self.reader_edit.setPlainText("")
            self.update_page_and_progress_labels(0.0)
            return

        idx = max(0, min(self.current_page_index, len(self.pages) - 1))
        self.current_page_index = idx
        self.reader_edit.setPlainText(self.pages[idx])

        if len(self.pages) == 1:
            ratio = 0.0
        else:
            ratio = idx / (len(self.pages) - 1)

        self.update_page_and_progress_labels(ratio)

    def update_page_and_progress_labels(self, ratio: float):
        total_pages = len(self.pages) if self.is_reading and self.pages else 0

        if not self.is_reading or total_pages == 0:
            # показываем только сохранённый прогресс
            if self.current_book_path:
                r = float(self.book_progress.get(os.path.abspath(self.current_book_path), 0.0))
                percent = int(round(r * 100))
            else:
                percent = 0
            self.lbl_progress_info.setText(f"{percent}%")
            self.lbl_progress_read.setText(f"{percent}%")
            self.page_edit.setText("0")
            self.lbl_page_total.setText("/0")
            return

        current_page = self.current_page_index + 1
        if current_page < 1:
            current_page = 1
        if current_page > total_pages:
            current_page = total_pages

        self.page_edit.blockSignals(True)
        self.page_edit.setText(str(current_page))
        self.page_edit.blockSignals(False)
        self.lbl_page_total.setText(f"/{total_pages}")

        ratio = max(0.0, min(1.0, ratio))
        percent = int(round(ratio * 100))
        self.lbl_progress_info.setText(f"{percent}%")
        self.lbl_progress_read.setText(f"{percent}%")

        if self.current_book_path:
            self.book_progress[os.path.abspath(self.current_book_path)] = ratio

        # навигационные кнопки
        self.btn_prev_page.setEnabled(total_pages > 1 and current_page > 1)
        self.btn_next_page.setEnabled(total_pages > 1 and current_page < total_pages)
        self.page_edit.setEnabled(total_pages > 1)

    # ---------- Режим чтения ----------

    def open_current_book(self):
        """
        Переходим в режим ридера:
        во ВСЁ правое поле отображается текст текущей страницы.
        """
        if not self.current_book_path:
            return

        path = self.current_book_path
        info = self.book_info_cache.get(path)
        if info is None:
            info = parse_fb2_book_info(path)
            self.book_info_cache[path] = info

        full_text = getattr(info, "full_text", None)
        if not full_text:
            full_text = info.description or "(Текст книги недоступен)"

        self.current_full_text = full_text
        self.is_reading = True
        self.stack.setCurrentWidget(self.reader_page)

        abs_path = os.path.abspath(path)
        ratio = float(self.book_progress.get(abs_path, 0.0))

        # Перепагинация после того, как виджет получит реальные размеры
        QTimer.singleShot(0, lambda: self.paginate_current_text(ratio))

    def back_to_info(self):
        """Вернуться со страницы ридера на страницу информации о книге."""
        self.is_reading = False
        self.stack.setCurrentWidget(self.info_page)
        # обновим прогресс на инфо-странице
        if self.current_book_path:
            info = self.book_info_cache.get(self.current_book_path)
            self.show_book_info(info, self.current_book_path)

    # ---------- Навигация по страницам ----------

    def get_total_pages(self) -> int:
        return len(self.pages) if self.pages else 0

    def go_to_page(self, page_index: int):
        if not self.is_reading or not self.pages:
            return
        total = len(self.pages)
        page_index = max(0, min(page_index, total - 1))
        self.current_page_index = page_index

        if total == 1:
            ratio = 0.0
        else:
            ratio = page_index / (total - 1)

        self.show_current_page()
        # show_current_page уже вызывает update_page_and_progress_labels

    def go_next_page(self):
        if not self.is_reading:
            return
        self.go_to_page(self.current_page_index + 1)

    def go_prev_page(self):
        if not self.is_reading:
            return
        self.go_to_page(self.current_page_index - 1)

    def on_page_edit_return(self):
        """Переход к странице по номеру, введённому в поле."""
        if not self.is_reading or not self.pages:
            return

        text = self.page_edit.text().strip()
        if not text.isdigit():
            return
        page = int(text)
        if page < 1:
            page = 1
        total = len(self.pages)
        if page > total:
            page = total

        self.go_to_page(page - 1)

    # ---------- Ресайз области чтения ----------

    def on_reader_resized(self):
        """
        При изменении размера области чтения — перепагинируем, сохраняя прогресс.
        """
        if not self.is_reading or not self.current_full_text or not self.current_book_path:
            return

        abs_path = os.path.abspath(self.current_book_path)
        ratio = float(self.book_progress.get(abs_path, 0.0))
        self.paginate_current_text(ratio)

    # ---------- Для совместимости: внешнее открытие (если захочешь) ----------

    def open_current_book_external(self):
        if not self.current_book_path:
            return
        url = QUrl.fromLocalFile(self.current_book_path)
        QDesktopServices.openUrl(url)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # глобальная иконка
    if os.path.exists(ICON_PATH):
        icon = QIcon(ICON_PATH)
        app.setWindowIcon(icon)
    else:
        icon = QIcon()

    apply_dark_theme(app)

    w = MainWindow()

    # Иконка также для главного окна
    if not icon.isNull():
        w.setWindowIcon(icon)

    w.show()

    # Восстановление максимизации
    if getattr(w, "_restore_maximized", False):
        w.showMaximized()

    sys.exit(app.exec())
