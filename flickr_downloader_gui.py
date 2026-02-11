#!/usr/bin/env python3
"""GUI for the Flickr Photo Downloader application (PyQt6)."""

import json
import os
import sys
from datetime import datetime, timedelta
from io import BytesIO

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTabWidget, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QRadioButton, QGroupBox,
    QProgressBar, QTextEdit, QFileDialog, QMessageBox, QScrollArea,
    QSplitter, QButtonGroup,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImage, QIcon

import requests
from dotenv import load_dotenv
from PIL import Image

PREVIEW_LIMIT = 50
THUMB_SIZE = 75
PREVIEW_COLS = 7

COLORS = {
    "bg": "#f8f9fa",
    "surface": "#ffffff",
    "accent": "#0078d4",
    "accent_hover": "#106ebe",
    "text": "#1a1a2e",
    "text_secondary": "#6e6e82",
    "border": "#e0e0e0",
    "log_bg": "#1e1e2e",
    "log_fg": "#d4d4dc",
    "log_selection": "#264f78",
}


def get_base_path():
    """Get the directory where the exe or script lives."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


sys.path.insert(0, get_base_path())
import flickr_downloader as core

SETTINGS_FILE = os.path.join(get_base_path(), "settings.json")

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #f8f9fa;
    font-family: "Segoe UI";
    font-size: 9pt;
    color: #1a1a2e;
}
QGroupBox {
    font-weight: bold;
    font-size: 9pt;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px 10px 8px 10px;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: #f8f9fa;
    color: #1a1a2e;
}
QTabWidget::pane {
    border: 1px solid #e0e0e0;
    border-top: 3px solid #0078d4;
    background: #ffffff;
    border-radius: 0 0 6px 6px;
}
QTabBar {
    qproperty-drawBase: 0;
}
QTabBar::tab {
    padding: 10px 22px;
    font-size: 10pt;
    font-weight: bold;
    color: #6e6e82;
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    margin-right: 2px;
}
QTabBar::tab:selected {
    color: #0078d4;
    border-bottom: 3px solid #0078d4;
    background: #ffffff;
}
QTabBar::tab:hover:!selected {
    color: #1a1a2e;
    background: #eef1f5;
    border-radius: 4px 4px 0 0;
}
QPushButton {
    padding: 6px 16px;
    border: 1px solid #e0e0e0;
    border-radius: 5px;
    background: #ffffff;
    font-size: 9pt;
    min-height: 20px;
}
QPushButton:hover {
    background: #eef1f5;
    border-color: #c0c0c0;
}
QPushButton:pressed {
    background: #dde1e6;
}
QPushButton:disabled {
    background: #f0f0f0;
    color: #aaaaaa;
}
QPushButton#downloadBtn {
    background: #0078d4;
    color: white;
    font-weight: bold;
    border: none;
    padding: 8px 22px;
}
QPushButton#downloadBtn:hover {
    background: #106ebe;
}
QPushButton#downloadBtn:pressed {
    background: #005a9e;
}
QPushButton#downloadBtn:disabled {
    background: #b0b0b0;
    color: #888888;
}
QLineEdit, QComboBox, QSpinBox {
    padding: 5px 8px;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    background: #ffffff;
    selection-background-color: #0078d4;
    min-height: 18px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border-color: #0078d4;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QProgressBar {
    border: none;
    border-radius: 4px;
    background: #e0e0e0;
    max-height: 8px;
}
QProgressBar::chunk {
    background: #0078d4;
    border-radius: 4px;
}
QCheckBox, QRadioButton {
    spacing: 6px;
}
QTextEdit#logPanel {
    background-color: #1e1e2e;
    color: #d4d4dc;
    border: none;
    border-radius: 4px;
    padding: 8px;
    selection-background-color: #264f78;
    font-family: "Consolas";
    font-size: 9pt;
}
QToolTip {
    background-color: #ffffff;
    color: #1a1a2e;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 6px;
    font-size: 8pt;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #c0c0c0;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #a0a0a0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #c0c0c0;
    border-radius: 5px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover {
    background: #a0a0a0;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QSplitter::handle {
    background: #e0e0e0;
    width: 2px;
}
"""


# ================================================================
# Worker Threads
# ================================================================

class LookupWorker(QThread):
    finished = pyqtSignal(str, str, object)  # username, nsid, albums
    error = pyqtSignal(str)

    def __init__(self, api_key, api_secret, username):
        super().__init__()
        self.api_key = api_key
        self.api_secret = api_secret
        self.username = username

    def run(self):
        try:
            dl = core.FlickrDownloader(self.api_key, self.api_secret)
            nsid, uname = dl.resolve_user(self.username)
            albums = dl.fetch_user_albums(nsid)
            self.finished.emit(uname, nsid, albums)
        except Exception as e:
            self.error.emit(str(e))


class PreviewWorker(QThread):
    status_update = pyqtSignal(str)
    thumb_ready = pyqtSignal(object, object, int)  # photo, QImage, index
    finished = pyqtSignal(int, int)  # total_available, loaded_count
    error = pyqtSignal(str)

    def __init__(self, api_key, api_secret, text, tags, tag_mode, sort,
                 license_ids, user_id):
        super().__init__()
        self.api_key = api_key
        self.api_secret = api_secret
        self.text = text
        self.tags = tags
        self.tag_mode = tag_mode
        self.sort = sort
        self.license_ids = license_ids
        self.user_id = user_id

    def run(self):
        try:
            import flickrapi
            fl = flickrapi.FlickrAPI(self.api_key, self.api_secret,
                                     format="parsed-json")
            kwargs = {
                "extras": "url_sq,owner_name,date_taken",
                "per_page": PREVIEW_LIMIT,
                "page": 1,
                "sort": self.sort,
                "safe_search": 1,
            }
            if self.text:
                kwargs["text"] = self.text
            if self.tags:
                kwargs["tags"] = self.tags
                kwargs["tag_mode"] = self.tag_mode
            if self.license_ids:
                kwargs["license"] = self.license_ids
            if self.user_id:
                kwargs["user_id"] = self.user_id

            resp = fl.photos.search(**kwargs)
            photos = resp["photos"]["photo"]
            total_available = int(resp["photos"]["total"])

            if not photos:
                self.finished.emit(0, 0)
                return

            loaded = 0
            for i, photo in enumerate(photos):
                url = photo.get("url_sq")
                if not url:
                    continue
                try:
                    r = requests.get(url, timeout=10)
                    r.raise_for_status()
                    img = Image.open(BytesIO(r.content))
                    img = img.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                    img = img.convert("RGBA")
                    data = img.tobytes("raw", "RGBA")
                    qimg = QImage(data, img.width, img.height,
                                  QImage.Format.Format_RGBA8888).copy()
                    self.thumb_ready.emit(photo, qimg, loaded)
                    loaded += 1
                except Exception:
                    pass
                self.status_update.emit(
                    f"Loading thumbnails... {i + 1}/{len(photos)}")

            self.finished.emit(total_available, loaded)
        except Exception as e:
            self.error.emit(str(e))


class DownloadWorker(QThread):
    progress_update = pyqtSignal(int, int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(bool)  # was_cancelled

    def __init__(self, api_key, api_secret, tab_index, params):
        super().__init__()
        self.api_key = api_key
        self.api_secret = api_secret
        self.tab_index = tab_index
        self.params = params
        self.downloader = None

    def cancel(self):
        if self.downloader:
            self.downloader.cancel()

    def run(self):
        try:
            self.downloader = core.FlickrDownloader(
                self.api_key, self.api_secret)
            self.downloader.set_callbacks(
                progress_cb=lambda c, t: self.progress_update.emit(c, t),
                log_cb=lambda m: self.log_message.emit(m),
            )

            p = self.params
            photos = []

            if self.tab_index == 0:
                photos = self.downloader.fetch_interestingness(
                    p["date"], p["count"])
                if p.get("user_nsid"):
                    nsid = p["user_nsid"]
                    photos = [ph for ph in photos
                              if ph.get("owner") == nsid]
                    self.log_message.emit(
                        f"Filtered to {len(photos)} photos by user {nsid}.")

            elif self.tab_index == 1:
                photos = self.downloader.search_photos(
                    text=p["text"], tags=p["tags"],
                    tag_mode=p["tag_mode"], sort=p["sort"],
                    license_ids=p["license_ids"],
                    count=p["count"], user_id=p.get("user_nsid", ""),
                )

            elif self.tab_index == 2:
                if p["mode"] == "photostream":
                    photos = self.downloader.fetch_user_photos(
                        p["user_nsid"], p["count"])
                else:
                    self.log_message.emit(
                        f"Downloading album: {p['album_title']}")
                    photos = self.downloader.fetch_album_photos(
                        p["user_nsid"], p["album_id"])

            if self.downloader.is_cancelled:
                self.log_message.emit("Operation cancelled.")
                self.finished.emit(True)
                return

            if not photos:
                self.log_message.emit("No photos found.")
                self.finished.emit(False)
                return

            self.log_message.emit(
                f"Downloading {len(photos)} photos to: {p['folder']}")
            self.downloader.download_photos(
                photos, p["folder"],
                size_key=p["size_key"],
                embed_metadata=p["metadata"],
                filename_template=p["filename"],
            )
            self.finished.emit(self.downloader.is_cancelled)

        except core.CancelledError:
            self.log_message.emit("Operation cancelled.")
            self.finished.emit(True)
        except Exception as e:
            self.log_message.emit(f"\nError: {e}")
            self.finished.emit(False)


# ================================================================
# Main Application
# ================================================================

class FlickrDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Flickr Photo Downloader")
        self.resize(1200, 680)
        self.setMinimumSize(1000, 540)

        icon_path = os.path.join(get_base_path(), "flickr_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._user_nsid = None
        self._user_albums = []
        self._preview_photos = []
        self._thumb_pixmaps = []

        self._lookup_worker = None
        self._preview_worker = None
        self._download_worker = None

        self._build_ui()
        self._load_credentials()
        self._load_settings()

    # ================================================================
    # UI Construction
    # ================================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # ---- LEFT PANEL ----
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(6)

        # Flickr User
        user_group = QGroupBox("Flickr User")
        user_grid = QGridLayout(user_group)
        user_grid.addWidget(QLabel("Username or URL:"), 0, 0)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText(
            "e.g. username or flickr.com/photos/username")
        user_grid.addWidget(self.user_input, 0, 1)
        self.lookup_btn = QPushButton("Look Up")
        self.lookup_btn.clicked.connect(self._lookup_user)
        user_grid.addWidget(self.lookup_btn, 0, 2)
        self.user_status_label = QLabel(
            "(optional \u2013 filter by user)")
        self.user_status_label.setStyleSheet(
            "color: #6e6e82; font-size: 8pt;")
        user_grid.addWidget(self.user_status_label, 1, 0, 1, 3)
        user_grid.setColumnStretch(1, 1)
        left_layout.addWidget(user_group)

        # Tabs
        self.tabs = QTabWidget()
        self._build_interestingness_tab()
        self._build_search_tab()
        self._build_user_tab()
        left_layout.addWidget(self.tabs, 1)

        # Download Options
        opts_group = QGroupBox("Download Options")
        opts_grid = QGridLayout(opts_group)

        opts_grid.addWidget(QLabel("Save to:"), 0, 0)
        self.folder_input = QLineEdit()
        self.folder_input.setText(os.path.join(
            os.path.expanduser("~"), "Pictures", "Flickr Downloads"))
        opts_grid.addWidget(self.folder_input, 0, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        opts_grid.addWidget(browse_btn, 0, 2)

        opts_grid.addWidget(QLabel("Photo size:"), 1, 0)
        self.size_combo = QComboBox()
        self.size_combo.addItems(list(core.PHOTO_SIZES.keys()))
        self.size_combo.setCurrentText("Large 1024")
        opts_grid.addWidget(self.size_combo, 1, 1)

        self.metadata_check = QCheckBox(
            "Embed metadata (title, tags, description)")
        self.metadata_check.setChecked(True)
        opts_grid.addWidget(self.metadata_check, 2, 0, 1, 3)

        opts_grid.addWidget(QLabel("Filename:"), 3, 0)
        self.filename_input = QLineEdit("{title}_{id}")
        opts_grid.addWidget(self.filename_input, 3, 1)
        hint = QLabel("({id}, {title}, {owner})")
        hint.setStyleSheet("font-size: 8pt; color: #6e6e82;")
        opts_grid.addWidget(hint, 3, 2)

        opts_grid.setColumnStretch(1, 1)
        left_layout.addWidget(opts_group)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 8pt;")
        left_layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        self.download_btn.setObjectName("downloadBtn")
        self.download_btn.clicked.connect(self._start_download)
        btn_layout.addWidget(self.download_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_download)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)

        splitter.addWidget(left_widget)

        # ---- RIGHT PANEL ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(6)

        log_group = QGroupBox("Log")
        log_inner = QVBoxLayout(log_group)
        log_inner.setContentsMargins(4, 8, 4, 4)
        self.log = QTextEdit()
        self.log.setObjectName("logPanel")
        self.log.setReadOnly(True)
        log_inner.addWidget(self.log)
        right_layout.addWidget(log_group, 1)

        cred_group = QGroupBox("Flickr API Credentials")
        cred_grid = QGridLayout(cred_group)
        cred_grid.addWidget(QLabel("API Key:"), 0, 0)
        self.api_key_input = QLineEdit()
        cred_grid.addWidget(self.api_key_input, 0, 1)
        cred_grid.addWidget(QLabel("API Secret:"), 1, 0)
        self.api_secret_input = QLineEdit()
        self.api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        cred_grid.addWidget(self.api_secret_input, 1, 1)
        cred_grid.setColumnStretch(1, 1)
        right_layout.addWidget(cred_group)

        splitter.addWidget(right_widget)
        splitter.setSizes([700, 480])

    def _build_interestingness_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Date:"), 0, 0)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.int_date_input = QLineEdit(yesterday)
        self.int_date_input.setMaximumWidth(120)
        layout.addWidget(self.int_date_input, 0, 1)
        hint = QLabel("(YYYY-MM-DD)")
        hint.setStyleSheet("font-size: 8pt; color: #6e6e82;")
        layout.addWidget(hint, 0, 2)

        layout.addWidget(QLabel("Count:"), 1, 0)
        self.int_count_spin = QSpinBox()
        self.int_count_spin.setRange(1, 500)
        self.int_count_spin.setValue(500)
        self.int_count_spin.setMaximumWidth(100)
        layout.addWidget(self.int_count_spin, 1, 1)

        layout.setColumnStretch(2, 1)
        layout.setRowStretch(2, 1)
        self.tabs.addTab(tab, "Interestingness")

    def _build_search_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Search fields
        fields = QGridLayout()
        fields.addWidget(QLabel("Keywords:"), 0, 0)
        self.search_text_input = QLineEdit()
        fields.addWidget(self.search_text_input, 0, 1, 1, 2)

        fields.addWidget(QLabel("Tags:"), 1, 0)
        self.search_tags_input = QLineEdit()
        fields.addWidget(self.search_tags_input, 1, 1, 1, 2)

        fields.addWidget(QLabel("Tag mode:"), 2, 0)
        tag_layout = QHBoxLayout()
        self.tag_any_radio = QRadioButton("Any")
        self.tag_any_radio.setChecked(True)
        self.tag_all_radio = QRadioButton("All")
        self.tag_mode_group = QButtonGroup()
        self.tag_mode_group.addButton(self.tag_any_radio)
        self.tag_mode_group.addButton(self.tag_all_radio)
        tag_layout.addWidget(self.tag_any_radio)
        tag_layout.addWidget(self.tag_all_radio)
        tag_layout.addStretch()
        fields.addLayout(tag_layout, 2, 1, 1, 2)

        fields.addWidget(QLabel("Sort:"), 3, 0)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(list(core.SORT_OPTIONS.keys()))
        self.sort_combo.setCurrentText("Relevance")
        fields.addWidget(self.sort_combo, 3, 1)

        fields.addWidget(QLabel("License:"), 4, 0)
        self.license_combo = QComboBox()
        self.license_combo.addItems(
            ["Any License"] + list(core.LICENSE_MAP.keys()))
        fields.addWidget(self.license_combo, 4, 1)

        fields.addWidget(QLabel("Count:"), 5, 0)
        self.search_count_spin = QSpinBox()
        self.search_count_spin.setRange(1, 4000)
        self.search_count_spin.setValue(100)
        self.search_count_spin.setMaximumWidth(100)
        fields.addWidget(self.search_count_spin, 5, 1)

        fields.setColumnStretch(1, 1)
        layout.addLayout(fields)

        # Preview bar
        preview_bar = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.clicked.connect(self._start_preview)
        preview_bar.addWidget(self.preview_btn)
        self.preview_status_label = QLabel("")
        self.preview_status_label.setStyleSheet(
            "font-size: 8pt; color: #6e6e82;")
        preview_bar.addWidget(self.preview_status_label, 1)
        layout.addLayout(preview_bar)

        # Preview scroll area
        preview_group = QGroupBox("Preview")
        preview_inner = QVBoxLayout(preview_group)
        preview_inner.setContentsMargins(4, 8, 4, 4)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setMinimumHeight(60)
        self.preview_widget = QWidget()
        self.preview_grid = QGridLayout(self.preview_widget)
        self.preview_grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.preview_scroll.setWidget(self.preview_widget)
        preview_inner.addWidget(self.preview_scroll)

        layout.addWidget(preview_group, 1)
        self.tabs.addTab(tab, "Search")

    def _build_user_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.user_photostream_radio = QRadioButton("Photostream")
        self.user_photostream_radio.setChecked(True)
        self.user_album_radio = QRadioButton("Album")
        self.user_mode_group = QButtonGroup()
        self.user_mode_group.addButton(self.user_photostream_radio)
        self.user_mode_group.addButton(self.user_album_radio)
        self.user_photostream_radio.toggled.connect(
            self._on_user_mode_change)
        layout.addWidget(self.user_photostream_radio, 0, 0)
        layout.addWidget(self.user_album_radio, 0, 1)

        layout.addWidget(QLabel("Album:"), 1, 0)
        self.album_combo = QComboBox()
        self.album_combo.setEnabled(False)
        self.album_combo.setMinimumWidth(250)
        layout.addWidget(self.album_combo, 1, 1, 1, 2)

        layout.addWidget(QLabel("Count:"), 2, 0)
        self.user_count_spin = QSpinBox()
        self.user_count_spin.setRange(1, 5000)
        self.user_count_spin.setValue(500)
        self.user_count_spin.setMaximumWidth(100)
        layout.addWidget(self.user_count_spin, 2, 1)

        layout.setColumnStretch(2, 1)
        layout.setRowStretch(3, 1)
        self.tabs.addTab(tab, "User / Album")

    # ================================================================
    # UI Helpers
    # ================================================================

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Download Folder", self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)

    def _on_user_mode_change(self):
        is_ps = self.user_photostream_radio.isChecked()
        self.album_combo.setEnabled(not is_ps)
        self.user_count_spin.setEnabled(is_ps)

    def _log_msg(self, msg):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_running(self, running):
        self.download_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

    # ================================================================
    # Preview
    # ================================================================

    def _clear_preview(self):
        while self.preview_grid.count():
            item = self.preview_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._thumb_pixmaps.clear()
        self._preview_photos.clear()

    def _start_preview(self):
        if self._preview_worker and self._preview_worker.isRunning():
            return

        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()
        if not api_key or not api_secret:
            QMessageBox.critical(
                self, "Error", "API Key and API Secret are required.")
            return

        text = self.search_text_input.text().strip()
        tags = self.search_tags_input.text().strip()
        if not text and not tags:
            QMessageBox.critical(
                self, "Error", "Enter keywords and/or tags to search.")
            return

        self.preview_btn.setEnabled(False)
        self.preview_status_label.setText("Searching...")
        self._clear_preview()

        tag_mode = "any" if self.tag_any_radio.isChecked() else "all"
        sort_label = self.sort_combo.currentText()
        sort_value = core.SORT_OPTIONS.get(sort_label, "relevance")
        license_label = self.license_combo.currentText()
        license_ids = ""
        if license_label != "Any License":
            license_ids = core.LICENSE_MAP.get(license_label, "")
        user_nsid = self._user_nsid or ""

        self._preview_worker = PreviewWorker(
            api_key, api_secret, text, tags, tag_mode, sort_value,
            license_ids, user_nsid)
        self._preview_worker.status_update.connect(
            self.preview_status_label.setText)
        self._preview_worker.thumb_ready.connect(self._add_thumbnail)
        self._preview_worker.finished.connect(self._finish_preview)
        self._preview_worker.error.connect(self._finish_preview_error)
        self._preview_worker.start()

    def _add_thumbnail(self, photo, qimage, index):
        pixmap = QPixmap.fromImage(qimage)
        self._thumb_pixmaps.append(pixmap)
        self._preview_photos.append(photo)

        cell = QWidget()
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(3, 3, 3, 3)
        cell_layout.setSpacing(2)

        img_label = QLabel()
        img_label.setPixmap(pixmap)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cell_layout.addWidget(img_label)

        title = photo.get("title", "") or ""
        if isinstance(title, dict):
            title = title.get("_content", "")
        short = (title[:12] + "...") if len(title) > 15 else title
        title_label = QLabel(short)
        title_label.setFont(QFont("Segoe UI", 7))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setFixedWidth(THUMB_SIZE)
        cell_layout.addWidget(title_label)

        owner = photo.get("ownername", "") or photo.get("owner", "")
        date = photo.get("datetaken", "")
        tip = f"{title}\nBy: {owner}"
        if date:
            tip += f"\nDate: {date}"
        cell.setToolTip(tip)

        row = index // PREVIEW_COLS
        col = index % PREVIEW_COLS
        self.preview_grid.addWidget(cell, row, col)

    def _finish_preview(self, total_available, loaded_count):
        self.preview_btn.setEnabled(True)
        if total_available == 0:
            self.preview_status_label.setText("No photos found.")
        else:
            self.preview_status_label.setText(
                f"{total_available:,} total photos found  |  "
                f"Previewing {loaded_count}")

    def _finish_preview_error(self, error):
        self.preview_btn.setEnabled(True)
        self.preview_status_label.setText(f"Error: {error}")

    # ================================================================
    # User Lookup
    # ================================================================

    def _lookup_user(self):
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()
        if not api_key or not api_secret:
            QMessageBox.critical(
                self, "Error", "API Key and API Secret are required.")
            return

        username = self.user_input.text().strip()
        if not username:
            self._user_nsid = None
            self._user_albums = []
            self.album_combo.clear()
            self.user_status_label.setText(
                "(optional \u2013 filter by user)")
            return

        self.lookup_btn.setEnabled(False)
        self.user_status_label.setText("Looking up user...")
        self.album_combo.clear()
        self._user_nsid = None
        self._user_albums = []

        self._lookup_worker = LookupWorker(api_key, api_secret, username)
        self._lookup_worker.finished.connect(self._finish_lookup)
        self._lookup_worker.error.connect(self._finish_lookup_error)
        self._lookup_worker.start()

    def _finish_lookup(self, username, nsid, albums):
        self._user_nsid = nsid
        self._user_albums = albums
        self.user_status_label.setText(f"User: {username} ({nsid})")
        album_names = [f"{a['title']} ({a['photos']} photos)"
                       for a in albums]
        self.album_combo.addItems(album_names)
        if album_names:
            self.album_combo.setCurrentIndex(0)
        self.lookup_btn.setEnabled(True)

    def _finish_lookup_error(self, error):
        self.user_status_label.setText(f"Error: {error}")
        self.lookup_btn.setEnabled(True)

    # ================================================================
    # Download
    # ================================================================

    def _start_download(self):
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()
        if not api_key or not api_secret:
            QMessageBox.critical(
                self, "Error", "API Key and API Secret are required.")
            return

        self.log.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting...")
        self._save_settings()
        self._set_running(True)

        tab_index = self.tabs.currentIndex()

        params = {
            "folder": self.folder_input.text(),
            "size_key": core.PHOTO_SIZES.get(
                self.size_combo.currentText(), "url_l"),
            "metadata": self.metadata_check.isChecked(),
            "filename": self.filename_input.text() or "{title}_{id}",
            "user_nsid": self._user_nsid,
        }

        if tab_index == 0:
            params["date"] = self.int_date_input.text().strip()
            params["count"] = self.int_count_spin.value()

        elif tab_index == 1:
            text = self.search_text_input.text().strip()
            tags = self.search_tags_input.text().strip()
            if not text and not tags:
                self._log_msg(
                    "Error: Enter keywords and/or tags to search.")
                self._set_running(False)
                return
            params["text"] = text
            params["tags"] = tags
            params["tag_mode"] = (
                "any" if self.tag_any_radio.isChecked() else "all")
            sort_label = self.sort_combo.currentText()
            params["sort"] = core.SORT_OPTIONS.get(
                sort_label, "relevance")
            license_label = self.license_combo.currentText()
            params["license_ids"] = ""
            if license_label != "Any License":
                params["license_ids"] = core.LICENSE_MAP.get(
                    license_label, "")
            params["count"] = self.search_count_spin.value()

        elif tab_index == 2:
            if not self._user_nsid:
                self._log_msg("Error: Look up a user first.")
                self._set_running(False)
                return
            mode = ("photostream"
                    if self.user_photostream_radio.isChecked()
                    else "album")
            params["mode"] = mode
            if mode == "photostream":
                params["count"] = self.user_count_spin.value()
            else:
                idx = self.album_combo.currentIndex()
                if idx < 0 or idx >= len(self._user_albums):
                    self._log_msg("Error: Select an album first.")
                    self._set_running(False)
                    return
                album = self._user_albums[idx]
                params["album_id"] = album["id"]
                params["album_title"] = album["title"]

        self._download_worker = DownloadWorker(
            api_key, api_secret, tab_index, params)
        self._download_worker.progress_update.connect(
            self._update_progress)
        self._download_worker.log_message.connect(self._log_msg)
        self._download_worker.finished.connect(self._download_finished)
        self._download_worker.start()

    def _cancel_download(self):
        if self._download_worker:
            self._download_worker.cancel()
            self.status_label.setText("Cancelling...")

    def _update_progress(self, current, total):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
            self.status_label.setText(f"{current}/{total} photos")

    def _download_finished(self, was_cancelled):
        self._set_running(False)
        self.status_label.setText(
            "Cancelled" if was_cancelled else "Done")
        self._download_worker = None

    # ================================================================
    # Credentials & Settings
    # ================================================================

    def closeEvent(self, event):
        self._save_settings()
        event.accept()

    def _load_credentials(self):
        env_path = os.path.join(get_base_path(), ".env")
        load_dotenv(env_path)
        env_key = os.environ.get("FLICKR_API_KEY", "")
        env_secret = os.environ.get("FLICKR_API_SECRET", "")

        if not env_key or not env_secret:
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("FLICKR_API_KEY="):
                            env_key = line.split("=", 1)[1].strip()
                        elif line.startswith("FLICKR_API_SECRET="):
                            env_secret = line.split("=", 1)[1].strip()
            except FileNotFoundError:
                pass

        saved_key = ""
        saved_secret = ""
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            saved_key = data.get("api_key", "")
            saved_secret = data.get("api_secret", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        self.api_key_input.setText(saved_key if saved_key else env_key)
        self.api_secret_input.setText(
            saved_secret if saved_secret else env_secret)

    def _save_settings(self):
        data = {
            "api_key": self.api_key_input.text(),
            "api_secret": self.api_secret_input.text(),
            "folder": self.folder_input.text(),
            "size": self.size_combo.currentText(),
            "metadata": self.metadata_check.isChecked(),
            "filename": self.filename_input.text(),
            "int_date": self.int_date_input.text(),
            "int_count": self.int_count_spin.value(),
            "search_text": self.search_text_input.text(),
            "search_tags": self.search_tags_input.text(),
            "tag_mode": (
                "any" if self.tag_any_radio.isChecked() else "all"),
            "sort": self.sort_combo.currentText(),
            "license": self.license_combo.currentText(),
            "search_count": self.search_count_spin.value(),
            "user_input": self.user_input.text(),
            "user_mode": (
                "photostream"
                if self.user_photostream_radio.isChecked()
                else "album"),
            "user_count": self.user_count_spin.value(),
            "active_tab": self.tabs.currentIndex(),
        }
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        if "folder" in data:
            self.folder_input.setText(data["folder"])
        if "size" in data:
            self.size_combo.setCurrentText(data["size"])
        if "metadata" in data:
            self.metadata_check.setChecked(data["metadata"])
        if "filename" in data:
            self.filename_input.setText(data["filename"])
        if "int_date" in data:
            self.int_date_input.setText(data["int_date"])
        if "int_count" in data:
            self.int_count_spin.setValue(data["int_count"])
        if "search_text" in data:
            self.search_text_input.setText(data["search_text"])
        if "search_tags" in data:
            self.search_tags_input.setText(data["search_tags"])
        if "tag_mode" in data:
            if data["tag_mode"] == "all":
                self.tag_all_radio.setChecked(True)
            else:
                self.tag_any_radio.setChecked(True)
        if "sort" in data:
            self.sort_combo.setCurrentText(data["sort"])
        if "license" in data:
            self.license_combo.setCurrentText(data["license"])
        if "search_count" in data:
            self.search_count_spin.setValue(data["search_count"])
        if "user_input" in data:
            self.user_input.setText(data["user_input"])
        if "user_mode" in data:
            if data["user_mode"] == "album":
                self.user_album_radio.setChecked(True)
            else:
                self.user_photostream_radio.setChecked(True)
            self._on_user_mode_change()
        if "user_count" in data:
            self.user_count_spin.setValue(data["user_count"])
        if "active_tab" in data:
            try:
                self.tabs.setCurrentIndex(data["active_tab"])
            except Exception:
                pass


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = FlickrDownloaderApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
