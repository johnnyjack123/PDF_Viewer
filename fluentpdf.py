#!/usr/bin/env python3
import sys, os, json, fitz
from pathlib import Path
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint
from PyQt6.QtGui import QImage, QPixmap, QKeySequence, QShortcut, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QLabel, QFrame, QSizePolicy, QSpinBox as QNativeSpinBox
)
from qfluentwidgets import (
    MSFluentWindow, NavigationItemPosition, FluentIcon as FIF,
    PushButton, TransparentToolButton, LineEdit,
    InfoBar, InfoBarPosition, CardWidget,
    BodyLabel, TitleLabel, SubtitleLabel, CaptionLabel, StrongBodyLabel,
    SmoothScrollArea, ProgressBar, setTheme, Theme, SearchLineEdit,
    ScrollArea, RoundMenu, Action, Flyout, FlyoutView,
    PrimaryPushButton
)

BASE_DIR      = Path(__file__).parent
DATA_DIR      = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

LIBRARY_FILE  = DATA_DIR / "library.json"
PROGRESS_FILE = DATA_DIR / "progress.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

def load_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_settings():
    return load_json(SETTINGS_FILE, {"zoom": 1.5, "offsets": {}})

def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


# ── Render Thread ──────────────────────────────────────────────────────────

class PageRenderWorker(QThread):
    pageReady = pyqtSignal(int, QPixmap)

    def __init__(self, doc_path, page_idx, zoom=1.5, dpr=1.0):
        super().__init__()
        self.doc_path = doc_path
        self.page_idx = page_idx
        self.zoom     = zoom
        self.dpr      = dpr

    def run(self):
        try:
            doc    = fitz.open(self.doc_path)
            page   = doc[self.page_idx]
            mat    = fitz.Matrix(self.zoom * self.dpr, self.zoom * self.dpr)
            pix    = page.get_pixmap(matrix=mat, alpha=False)
            img    = QImage(pix.samples, pix.width, pix.height,
                            pix.stride, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(img)
            pixmap.setDevicePixelRatio(self.dpr)
            doc.close()
            self.pageReady.emit(self.page_idx, pixmap)
        except Exception as e:
            print(f"[Render-Fehler] {e}")


# ── PDF Viewer ─────────────────────────────────────────────────────────────

class PDFViewerInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = 0
        self.total_pages  = 0
        self.pdf_path     = None
        self.workers      = []
        self.zoom = load_settings().get("zoom", 1.5)
        self._setup_ui()

    def _get_dpr(self):
        screen = QApplication.primaryScreen()
        return screen.devicePixelRatio() if screen else 1.0

    def _get_offset(self):
        if not self.pdf_path:
            return 0
        return load_settings().get("offsets", {}).get(self.pdf_path, 0)

    def _displayed_page(self, real_idx):
        return real_idx + 1 - self._get_offset()

    def _real_page(self, displayed_num):
        return displayed_num - 1 + self._get_offset()

    def _setup_ui(self):
        self.setObjectName("PDFViewerInterface")
        ml = QVBoxLayout(self)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        toolbar = QFrame(self)
        toolbar.setFixedHeight(56)
        toolbar.setStyleSheet(
            "background: rgba(255,255,255,0.03);"
            "border-bottom: 1px solid rgba(0,0,0,0.1);"
        )
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(16, 4, 16, 4)
        tb.setSpacing(8)

        self.btn_back = TransparentToolButton(FIF.LEFT_ARROW, self)
        self.btn_back.setToolTip("Zurueck zur Bibliothek")
        self.btn_back.clicked.connect(self._go_back)
        tb.addWidget(self.btn_back)

        self.title_label = BodyLabel("Kein Dokument geoeffnet", self)
        tb.addWidget(self.title_label)
        tb.addStretch()

        self.btn_zoom_out = TransparentToolButton(FIF.REMOVE, self)
        self.btn_zoom_out.setToolTip("Verkleinern [-]")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        tb.addWidget(self.btn_zoom_out)

        self.zoom_label = CaptionLabel(f"{int(self.zoom*100)}%", self)
        self.zoom_label.setFixedWidth(42)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb.addWidget(self.zoom_label)

        self.btn_zoom_in = TransparentToolButton(FIF.ADD, self)
        self.btn_zoom_in.setToolTip("Vergroessern [+]  |  Strg+Mausrad")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        tb.addWidget(self.btn_zoom_in)

        tb.addSpacing(16)

        self.btn_prev = TransparentToolButton(FIF.PAGE_LEFT, self)
        self.btn_prev.setToolTip("Vorherige Seite [links]")
        self.btn_prev.clicked.connect(self._prev_page)
        tb.addWidget(self.btn_prev)

        self.page_input = LineEdit(self)
        self.page_input.setFixedWidth(60)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.setPlaceholderText("Seite")
        self.page_input.returnPressed.connect(self._jump_to_page)
        tb.addWidget(self.page_input)

        self.page_total_label = CaptionLabel("/ 0", self)
        tb.addWidget(self.page_total_label)

        self.btn_next = TransparentToolButton(FIF.PAGE_RIGHT, self)
        self.btn_next.setToolTip("Naechste Seite [rechts]")
        self.btn_next.clicked.connect(self._next_page)
        tb.addWidget(self.btn_next)

        ml.addWidget(toolbar)

        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("border: none; background: #1e1e1e;")

        self.page_container = QWidget()
        self.page_container.setStyleSheet("background: #1e1e1e;")
        cl = QVBoxLayout(self.page_container)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.setContentsMargins(24, 24, 24, 24)

        self.page_label = QLabel(self.page_container)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet("background: white; border-radius: 3px;")
        self.page_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        cl.addWidget(self.page_label)

        self.scroll_area.setWidget(self.page_container)
        self.scroll_area.viewport().installEventFilter(self)
        ml.addWidget(self.scroll_area, 1)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        ml.addWidget(self.progress_bar)

        QShortcut(QKeySequence("Left"),  self, self._prev_page)
        QShortcut(QKeySequence("Right"), self, self._next_page)
        QShortcut(QKeySequence("+"),     self, self._zoom_in)
        QShortcut(QKeySequence("-"),     self, self._zoom_out)

        self._set_controls_enabled(False)

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and isinstance(event, QWheelEvent):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if event.angleDelta().y() > 0:
                    self._zoom_in()
                else:
                    self._zoom_out()
                return True
        return super().eventFilter(obj, event)

    def open_pdf(self, path, start_page=0):
        self.pdf_path = path
        try:
            doc = fitz.open(path)
            self.total_pages = len(doc)
            doc.close()
        except Exception as e:
            InfoBar.error("Fehler", str(e), parent=self, position=InfoBarPosition.TOP)
            return
        self.current_page = min(start_page, self.total_pages - 1)
        name = Path(path).stem
        self.title_label.setText(name[:60] + ("..." if len(name) > 60 else ""))
        offset = self._get_offset()
        self.page_total_label.setText(f"/ {self.total_pages - offset}")
        self._set_controls_enabled(True)
        self._render_page(self.current_page)

    def _render_page(self, idx):
        if not self.pdf_path or idx < 0 or idx >= self.total_pages:
            return
        self.current_page = idx
        self.page_input.setText(str(self._displayed_page(idx)))
        pct = int((idx + 1) / self.total_pages * 100) if self.total_pages else 0
        self.progress_bar.setValue(pct)
        self.btn_prev.setEnabled(idx > 0)
        self.btn_next.setEnabled(idx < self.total_pages - 1)

        worker = PageRenderWorker(self.pdf_path, idx, self.zoom, self._get_dpr())
        worker.pageReady.connect(self._on_page_ready)
        self.workers.append(worker)
        worker.start()

        progress = load_json(PROGRESS_FILE, {})
        progress[self.pdf_path] = idx
        save_json(PROGRESS_FILE, progress)

    def _on_page_ready(self, idx, pixmap):
        if idx == self.current_page:
            logical_w = int(pixmap.width()  / pixmap.devicePixelRatio())
            logical_h = int(pixmap.height() / pixmap.devicePixelRatio())
            self.page_label.setPixmap(pixmap)
            self.page_label.setFixedSize(logical_w, logical_h)

    def _prev_page(self):
        if self.current_page > 0:
            self._render_page(self.current_page - 1)

    def _next_page(self):
        if self.current_page < self.total_pages - 1:
            self._render_page(self.current_page + 1)

    def _jump_to_page(self):
        try:
            real_idx = self._real_page(int(self.page_input.text()))
            if 0 <= real_idx < self.total_pages:
                self._render_page(real_idx)
            else:
                offset = self._get_offset()
                InfoBar.warning(
                    "Ungueltige Seite",
                    f"Bitte zwischen {1-offset} und {self.total_pages-offset} eingeben.",
                    parent=self, position=InfoBarPosition.TOP, duration=2500
                )
        except ValueError:
            pass

    def _zoom_in(self):
        if self.zoom < 4.0:
            self.zoom = round(self.zoom + 0.25, 2)
            self._save_zoom()
            self.zoom_label.setText(f"{int(self.zoom*100)}%")
            self._render_page(self.current_page)

    def _zoom_out(self):
        if self.zoom > 0.25:
            self.zoom = round(self.zoom - 0.25, 2)
            self._save_zoom()
            self.zoom_label.setText(f"{int(self.zoom*100)}%")
            self._render_page(self.current_page)

    def _save_zoom(self):
        s = load_settings()
        s["zoom"] = self.zoom
        save_settings(s)

    def refresh_after_offset_change(self):
        if self.pdf_path:
            offset = self._get_offset()
            self.page_total_label.setText(f"/ {self.total_pages - offset}")
            self.page_input.setText(str(self._displayed_page(self.current_page)))

    def _set_controls_enabled(self, enabled):
        for w in [self.btn_prev, self.btn_next, self.btn_zoom_in,
                  self.btn_zoom_out, self.page_input]:
            w.setEnabled(enabled)

    def _go_back(self):
        win = self.window()
        if hasattr(win, "switchTo"):
            win.switchTo(win.library_interface)


# ── Offset Flyout ──────────────────────────────────────────────────────────

class OffsetFlyout(QWidget):
    """Kleines Popup-Widget fuer den Seitenoffset einer PDF-Karte."""

    offsetChanged = pyqtSignal(int)  # emittiert den neuen Offset

    def __init__(self, current_offset=0, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel("Seitenoffset", self))
        layout.addWidget(CaptionLabel(
            "Anzahl Seiten vor Seite 1\n(z.B. Titelseite, Vorwort)", self
        ))

        row = QHBoxLayout()
        row.setSpacing(8)

        # Nativen QSpinBox verwenden – qfluentwidgets SpinBox hat Bug mit Input
        self.spin = QNativeSpinBox(self)
        self.spin.setRange(-100, 100)
        self.spin.setValue(current_offset)
        self.spin.setFixedWidth(90)
        self.spin.setFixedHeight(32)
        self.spin.setStyleSheet("""
            QSpinBox {
                border: 1px solid rgba(0,0,0,0.2);
                border-radius: 5px;
                padding: 2px 6px;
                font-size: 14px;
            }
        """)
        row.addWidget(self.spin)
        row.addStretch()
        layout.addLayout(row)

        self.btn_ok = PrimaryPushButton("Speichern", self)
        self.btn_ok.clicked.connect(self._emit)
        layout.addWidget(self.btn_ok)

    def _emit(self):
        self.offsetChanged.emit(self.spin.value())


# ── PDF Card ───────────────────────────────────────────────────────────────

class PDFCard(CardWidget):
    openRequested   = pyqtSignal(str)
    offsetChanged   = pyqtSignal(str, int)  # (pdf_path, new_offset)

    def __init__(self, pdf_path, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.setFixedSize(200, 255)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Thumbnail
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(176, 160)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background: #d0d0d0; border-radius: 4px;")
        self.thumb_label.setText("PDF")
        layout.addWidget(self.thumb_label)

        # Titel
        self.name_label = BodyLabel(Path(pdf_path).stem, self)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        # Fortschritt
        self.progress_label = CaptionLabel("", self)
        self.progress_label.setStyleSheet("color: grey;")
        layout.addWidget(self.progress_label)
        self._update_progress_label()

        # Drei-Punkte-Button oben rechts
        self.menu_btn = TransparentToolButton(FIF.MORE, self)
        self.menu_btn.setFixedSize(28, 28)
        self.menu_btn.move(170, 4)
        self.menu_btn.raise_()
        self.menu_btn.setToolTip("Optionen")
        self.menu_btn.clicked.connect(self._show_menu)

        self._load_thumbnail(pdf_path)

    def _update_progress_label(self):
        try:
            progress = load_json(PROGRESS_FILE, {})
            pg = progress.get(self.pdf_path, 0)
            doc = fitz.open(self.pdf_path)
            total = len(doc)
            doc.close()
            offset = load_settings().get("offsets", {}).get(self.pdf_path, 0)
            pct = int((pg + 1) / total * 100) if total else 0
            self.progress_label.setText(
                f"Seite {pg+1-offset}/{total-offset}  ({pct}%)"
            )
        except Exception:
            self.progress_label.setText("")

    def _load_thumbnail(self, path):
        try:
            doc    = fitz.open(path)
            page   = doc[0]
            mat    = fitz.Matrix(0.35, 0.35)
            pix    = page.get_pixmap(matrix=mat, alpha=False)
            img    = QImage(pix.samples, pix.width, pix.height,
                            pix.stride, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(img).scaled(
                176, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumb_label.setPixmap(pixmap)
            self.thumb_label.setStyleSheet("background: #d0d0d0; border-radius: 4px;")
            doc.close()
        except Exception:
            pass

    def _show_menu(self):
        menu = RoundMenu(parent=self)
        current_offset = load_settings().get("offsets", {}).get(self.pdf_path, 0)

        # Offset-Eintrag oeffnet Flyout
        action_offset = Action(FIF.EDIT, f"Seitenoffset ({current_offset})")
        action_offset.triggered.connect(self._show_offset_flyout)
        menu.addAction(action_offset)

        menu.addSeparator()

        action_remove = Action(FIF.DELETE, "Aus Bibliothek entfernen")
        action_remove.triggered.connect(self._remove_from_library)
        menu.addAction(action_remove)

        # Menü direkt unter dem Button anzeigen
        pos = self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height()))
        menu.exec(pos)

    def _show_offset_flyout(self):
        current_offset = load_settings().get("offsets", {}).get(self.pdf_path, 0)
        flyout_widget = OffsetFlyout(current_offset)
        flyout_widget.offsetChanged.connect(self._apply_offset)

        view = FlyoutView(
            title="Seitenoffset",
            content="",
            isClosable=True
        )
        view.addWidget(flyout_widget)

        btn_pos = self.menu_btn.mapToGlobal(
            QPoint(self.menu_btn.width() // 2, self.menu_btn.height())
        )
        Flyout.make(view, self.menu_btn, self.window())

    def _apply_offset(self, value):
        s = load_settings()
        s.setdefault("offsets", {})[self.pdf_path] = value
        save_settings(s)
        self._update_progress_label()
        self.offsetChanged.emit(self.pdf_path, value)
        # Viewer aktualisieren falls dieses PDF gerade offen ist
        win = self.window()
        if hasattr(win, "viewer_interface"):
            if win.viewer_interface.pdf_path == self.pdf_path:
                win.viewer_interface.refresh_after_offset_change()
        InfoBar.success(
            "Offset gespeichert",
            f"Offset {value} fuer '{Path(self.pdf_path).stem[:30]}' gesetzt.",
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2000
        )

    def _remove_from_library(self):
        library = load_json(LIBRARY_FILE, [])
        if self.pdf_path in library:
            library.remove(self.pdf_path)
            save_json(LIBRARY_FILE, library)
        self.hide()
        # WrapWidget neu layouten
        if hasattr(self.parent(), "_relayout"):
            self.parent()._relayout()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.openRequested.emit(self.pdf_path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.openRequested.emit(self.pdf_path)
        super().mouseDoubleClickEvent(event)


# ── Wrap Widget ────────────────────────────────────────────────────────────

class WrapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = []

    def addCard(self, card):
        self._cards.append(card)
        card.setParent(self)
        card.show()
        self._relayout()

    def visibleCards(self):
        return [c for c in self._cards if c.isVisible()]

    def _relayout(self):
        visible = self.visibleCards()
        if not visible:
            self.setFixedHeight(20)
            return
        cols = max(1, self.width() // 216)
        x, y, col = 0, 0, 0
        for card in visible:
            card.move(x, y)
            col += 1
            if col >= cols:
                col = 0; x = 0; y += 271
            else:
                x += 216
        rows = (len(visible) + cols - 1) // cols
        self.setFixedHeight(max(rows * 271, 20))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def count(self):
        return len(self._cards)


# ── Library Interface ──────────────────────────────────────────────────────

class LibraryInterface(QWidget):
    openPDF = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LibraryInterface")
        self._setup_ui()
        self._load_library()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(TitleLabel("Meine Bibliothek", self))
        header.addStretch()
        self.btn_add = PushButton("PDF hinzufuegen", self, FIF.ADD)
        self.btn_add.clicked.connect(self._add_pdf)
        header.addWidget(self.btn_add)
        layout.addLayout(header)

        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText("Bibliothek durchsuchen...")
        self.search.textChanged.connect(self._filter_cards)
        self.search.setFixedHeight(36)
        layout.addWidget(self.search)

        self.scroll = SmoothScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none;")
        self.wrap = WrapWidget()
        self.scroll.setWidget(self.wrap)
        layout.addWidget(self.scroll, 1)

        self.empty_label = SubtitleLabel(
            "Keine PDFs in der Bibliothek. Klicke auf 'PDF hinzufuegen'.", self
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: grey;")
        layout.addWidget(self.empty_label)
        self.empty_label.hide()

    def _add_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "PDF-Dateien auswaehlen", "", "PDF-Dateien (*.pdf)"
        )
        if not paths:
            return
        library = load_json(LIBRARY_FILE, [])
        added = 0
        for p in paths:
            if p not in library:
                library.append(p)
                added += 1
                self._add_card(p)
        save_json(LIBRARY_FILE, library)
        self._update_empty_state()
        if added:
            InfoBar.success("Hinzugefuegt", f"{added} PDF(s) hinzugefuegt.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)

    def _add_card(self, path):
        card = PDFCard(path, self.wrap)
        card.openRequested.connect(self._open_pdf)
        self.wrap.addCard(card)

    def _open_pdf(self, path):
        progress = load_json(PROGRESS_FILE, {})
        page = progress.get(path, 0)
        self.openPDF.emit(path, page)

    def _load_library(self):
        library = load_json(LIBRARY_FILE, [])
        existing = []
        for path in library:
            if os.path.exists(path):
                self._add_card(path)
                existing.append(path)
        if len(existing) != len(library):
            save_json(LIBRARY_FILE, existing)
        self._update_empty_state()

    def _update_empty_state(self):
        self.empty_label.setVisible(self.wrap.count() == 0)

    def _filter_cards(self, text):
        text = text.lower()
        for card in self.wrap._cards:
            card.setVisible(text in Path(card.pdf_path).stem.lower())
        self.wrap._relayout()


# ── Settings Interface ─────────────────────────────────────────────────────

class SettingsInterface(ScrollArea):
    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self.setObjectName("SettingsInterface")
        self.setWidgetResizable(True)
        self.setStyleSheet("border: none;")

        container = QWidget()
        self.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(TitleLabel("Einstellungen", self))

        info_card = QFrame(self)
        info_card.setStyleSheet(
            "background: rgba(255,255,255,0.05); border-radius: 8px;"
            "border: 1px solid rgba(0,0,0,0.08);"
        )
        il = QVBoxLayout(info_card)
        il.setContentsMargins(20, 16, 20, 16)
        il.setSpacing(6)
        il.addWidget(StrongBodyLabel("Datenspeicherung", self))
        il.addWidget(BodyLabel(f"Alle Daten liegen in:\n{str(DATA_DIR)}", self))
        il.addWidget(CaptionLabel(
            "library.json   - Liste der PDFs\n"
            "progress.json  - Lesefortschritt je PDF\n"
            "settings.json  - Zoom & Seitenoffsets",
            self
        ))
        layout.addWidget(info_card)

        hint_card = QFrame(self)
        hint_card.setStyleSheet(
            "background: rgba(255,255,255,0.05); border-radius: 8px;"
            "border: 1px solid rgba(0,0,0,0.08);"
        )
        hl = QVBoxLayout(hint_card)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(6)
        hl.addWidget(StrongBodyLabel("Seitenoffset einstellen", self))
        hl.addWidget(BodyLabel(
            "Den Seitenoffset kannst du direkt in der Bibliothek einstellen:\n"
            "Klicke auf das  ...  Menue oben rechts auf einer PDF-Karte.", self
        ))
        layout.addWidget(hint_card)
        layout.addStretch()


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FluentPDF")
        self.resize(1200, 800)
        setTheme(Theme.AUTO)

        self.library_interface  = LibraryInterface(self)
        self.viewer_interface   = PDFViewerInterface(self)
        self.settings_interface = SettingsInterface(self.viewer_interface, self)

        self.library_interface.openPDF.connect(self._open_pdf_in_viewer)

        self.addSubInterface(self.library_interface,  FIF.LIBRARY,  "Bibliothek")
        self.addSubInterface(self.viewer_interface,   FIF.DOCUMENT, "Lesemodus")
        self.addSubInterface(
            self.settings_interface, FIF.SETTING, "Einstellungen",
            position=NavigationItemPosition.BOTTOM
        )
        self.stackedWidget.setCurrentWidget(self.library_interface)

    def _open_pdf_in_viewer(self, path, page):
        self.viewer_interface.open_pdf(path, page)
        self.switchTo(self.viewer_interface)


# ── Entry Point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("FluentPDF")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())