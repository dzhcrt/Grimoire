import os
import base64
from dataclasses import dataclass, field
from typing import List, Optional

import xml.etree.ElementTree as ET


@dataclass
class BookInfo:
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    genres: List[str] = field(default_factory=list)
    publisher: Optional[str] = None
    date: Optional[str] = None
    lang: Optional[str] = None
    description: Optional[str] = None
    cover_bytes: Optional[bytes] = None
    full_text: Optional[str] = None  # <<< ВАЖНО: полный текст книги


# ---------- Вспомогательные функции ----------

def _local_name(tag: str) -> str:
    """Возвращает имя тега без namespace, например '{ns}body' -> 'body'."""
    return tag.split('}', 1)[-1]


def _iter_children_with_name(elem, name: str):
    """Итератор по дочерним элементам с локальным именем name."""
    for child in list(elem):
        if _local_name(child.tag) == name:
            yield child


def _find_first_child(elem, name: str):
    for child in list(elem):
        if _local_name(child.tag) == name:
            return child
    return None


def _elem_text(elem) -> str:
    """Возвращает полный текст элемента (включая вложенные теги)."""
    if elem is None:
        return ""
    parts = []
    for txt in elem.itertext():
        if txt:
            parts.append(txt)
    return "".join(parts)


# ---------- Извлечение только заголовка (для дерева) ----------

def extract_fb2_title(path: str) -> str:
    """
    Быстрый способ вытащить название книги для дерева.
    Если не получилось — возвращаем имя файла без расширения.
    """
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return os.path.splitext(os.path.basename(path))[0]

    # <FictionBook><description><title-info>...
    description = _find_first_child(root, "description")
    if description is not None:
        title_info = _find_first_child(description, "title-info")
        if title_info is not None:
            book_title = _find_first_child(title_info, "book-title")
            if book_title is not None:
                text = _elem_text(book_title).strip()
                if text:
                    return text

    return os.path.splitext(os.path.basename(path))[0]


# ---------- Полный разбор файла ----------

def parse_fb2_book_info(path: str) -> BookInfo:
    """
    Полноценный парсер fb2:
    - title, authors, genres, publisher, date, lang;
    - annotation -> description;
    - обложка из <binary>;
    - полный текст книги из <body> -> full_text.
    """
    info = BookInfo()

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        # В случае ошибки хотя бы заголовок из имени файла
        info.title = os.path.splitext(os.path.basename(path))[0]
        return info

    # ---------- description / title-info ----------
    description = _find_first_child(root, "description")
    title_info = _find_first_child(description, "title-info") if description is not None else None
    publish_info = None
    if description is not None:
        # Некоторые книги используют <publish-info> для издательства/даты
        publish_info = _find_first_child(description, "publish-info")

    # --- title ---
    if title_info is not None:
        book_title = _find_first_child(title_info, "book-title")
        if book_title is not None:
            txt = _elem_text(book_title).strip()
            if txt:
                info.title = txt

    if not info.title:
        info.title = os.path.splitext(os.path.basename(path))[0]

    # --- authors ---
    if title_info is not None:
        for author in _iter_children_with_name(title_info, "author"):
            first_name = _find_first_child(author, "first-name")
            last_name = _find_first_child(author, "last-name")
            middle_name = _find_first_child(author, "middle-name")

            parts = []
            if first_name is not None:
                parts.append(_elem_text(first_name).strip())
            if middle_name is not None:
                parts.append(_elem_text(middle_name).strip())
            if last_name is not None:
                parts.append(_elem_text(last_name).strip())

            name = " ".join(p for p in parts if p)
            if name:
                info.authors.append(name)

    # --- genres ---
    if title_info is not None:
        for genre in _iter_children_with_name(title_info, "genre"):
            g = _elem_text(genre).strip()
            if g:
                info.genres.append(g)

    # --- lang ---
    if title_info is not None:
        lang = _find_first_child(title_info, "lang")
        if lang is not None:
            txt = _elem_text(lang).strip()
            if txt:
                info.lang = txt

    # --- publisher / date ---
    if publish_info is not None:
        publisher = _find_first_child(publish_info, "publisher")
        if publisher is not None:
            txt = _elem_text(publisher).strip()
            if txt:
                info.publisher = txt

        date = _find_first_child(publish_info, "year")
        if date is not None:
            txt = _elem_text(date).strip()
            if txt:
                info.date = txt

    # Иногда дата бывает и в title-info/date
    if not info.date and title_info is not None:
        date = _find_first_child(title_info, "date")
        if date is not None:
            txt = _elem_text(date).strip()
            if txt:
                info.date = txt

    # --- annotation -> description ---
    if title_info is not None:
        annotation = _find_first_child(title_info, "annotation")
        if annotation is not None:
            # Соберём параграфы <p> в annotation
            paras = []
            for elem in annotation.iter():
                if _local_name(elem.tag) == "p":
                    t = _elem_text(elem).strip()
                    if t:
                        paras.append(t)
            if paras:
                info.description = "\n\n".join(paras)

    # ---------- Обложка (binary) ----------
    # В title-info/coverpage/image xlink:href="#id" -> <binary id="id">
    cover_id = None
    if title_info is not None:
        coverpage = _find_first_child(title_info, "coverpage")
        if coverpage is not None:
            image = _find_first_child(coverpage, "image")
            if image is not None:
                href = image.attrib.get("href") or image.attrib.get("{http://www.w3.org/1999/xlink}href")
                if href:
                    cover_id = href.lstrip("#")

    if cover_id:
        for bin_elem in root.iter():
            if _local_name(bin_elem.tag) == "binary":
                if bin_elem.attrib.get("id") == cover_id:
                    # binary содержит base64
                    data_base64 = _elem_text(bin_elem).strip()
                    if data_base64:
                        try:
                            info.cover_bytes = base64.b64decode(data_base64)
                        except Exception:
                            info.cover_bytes = None
                    break

    # ---------- Полный текст книги из <body> ----------
    # Собираем все <p> из всех <body> (включая главы/sections)
    paragraphs = []

    for body in root:
        if _local_name(body.tag) != "body":
            continue

        # Можно игнорировать body с типом "notes" при желании:
        # if body.attrib.get("name") == "notes": continue

        for elem in body.iter():
            if _local_name(elem.tag) == "p":
                t = _elem_text(elem).strip()
                if t:
                    paragraphs.append(t)

    if paragraphs:
        info.full_text = "\n\n".join(paragraphs)
    else:
        info.full_text = None

    return info
