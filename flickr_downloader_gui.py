#!/usr/bin/env python3
"""GUI for the Flickr Photo Downloader application."""

import json
import os
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from io import BytesIO
from tkinter import ttk, scrolledtext, messagebox, filedialog

import requests
from dotenv import load_dotenv
from PIL import Image, ImageTk

PREVIEW_LIMIT = 50
THUMB_SIZE = 75
PREVIEW_COLS = 7


def get_base_path():
    """Get the directory where the exe or script lives."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Import core logic
sys.path.insert(0, get_base_path())
import flickr_downloader as core

SETTINGS_FILE = os.path.join(get_base_path(), "settings.json")


class Tooltip:
    """Lightweight tooltip that shows on hover over a widget."""

    def __init__(self, widget, text):
        self._widget = widget
        self._text = text
        self._tip_window = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def update_text(self, text):
        self._text = text

    def _show(self, event=None):
        if self._tip_window:
            return
        x = self._widget.winfo_rootx() + 10
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 5
        self._tip_window = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self._text, justify="left",
            background="#ffffe0", relief="solid", borderwidth=1,
            font=("TkDefaultFont", 8), wraplength=300,
        )
        label.pack()

    def _hide(self, event=None):
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None


class FlickrDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Flickr Photo Downloader")
        self.root.geometry("700x1000")
        self.root.resizable(False, True)

        icon_path = os.path.join(get_base_path(), "flickr_icon.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        self.downloader = None
        self.running = False
        self._user_nsid = None
        self._user_albums = []
        self._preview_photos = []
        self._thumb_images = []
        self._preview_loading = False
        self._int_user_nsid = None
        self._search_user_nsid = None

        self._build_ui()
        self._load_credentials()
        self._load_settings()

        # Save settings automatically when the window is closed
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================================================================
    # UI Construction
    # ================================================================

    def _build_ui(self):
        # --- Credentials frame ---
        cred_frame = ttk.LabelFrame(self.root, text="Flickr API Credentials", padding=10)
        cred_frame.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(cred_frame, text="API Key:").grid(row=0, column=0, sticky="w")
        self.api_key_var = tk.StringVar()
        ttk.Entry(cred_frame, textvariable=self.api_key_var, width=55).grid(
            row=0, column=1, padx=(5, 0), pady=2
        )

        ttk.Label(cred_frame, text="API Secret:").grid(row=1, column=0, sticky="w")
        self.api_secret_var = tk.StringVar()
        ttk.Entry(cred_frame, textvariable=self.api_secret_var, width=55, show="*").grid(
            row=1, column=1, padx=(5, 0), pady=2
        )

        # --- Tabbed notebook ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self._build_interestingness_tab()
        self._build_search_tab()
        self._build_user_tab()

        # --- Download options frame ---
        opts_frame = ttk.LabelFrame(self.root, text="Download Options", padding=10)
        opts_frame.pack(fill="x", padx=10, pady=5)

        # Folder
        ttk.Label(opts_frame, text="Save to:").grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Pictures", "Flickr Downloads"))
        folder_entry = ttk.Entry(opts_frame, textvariable=self.folder_var, width=45)
        folder_entry.grid(row=0, column=1, padx=(5, 5), pady=2, sticky="w")
        ttk.Button(opts_frame, text="Browse...", command=self._browse_folder).grid(
            row=0, column=2, pady=2
        )

        # Photo size
        ttk.Label(opts_frame, text="Photo size:").grid(row=1, column=0, sticky="w")
        self.size_var = tk.StringVar(value="Large 1024")
        size_combo = ttk.Combobox(
            opts_frame, textvariable=self.size_var,
            values=list(core.PHOTO_SIZES.keys()),
            state="readonly", width=20,
        )
        size_combo.grid(row=1, column=1, padx=(5, 0), pady=2, sticky="w")

        # Metadata checkbox
        self.metadata_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts_frame, text="Embed metadata (title, tags, description)",
            variable=self.metadata_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)

        # Filename format
        ttk.Label(opts_frame, text="Filename:").grid(row=3, column=0, sticky="w")
        self.filename_var = tk.StringVar(value="{title}_{id}")
        fname_entry = ttk.Entry(opts_frame, textvariable=self.filename_var, width=30)
        fname_entry.grid(row=3, column=1, padx=(5, 0), pady=2, sticky="w")
        ttk.Label(opts_frame, text="({id}, {title}, {owner})", font=("", 8)).grid(
            row=3, column=2, sticky="w", padx=(5, 0)
        )

        # --- Progress ---
        prog_frame = ttk.Frame(self.root, padding=(10, 5))
        prog_frame.pack(fill="x", padx=10)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            prog_frame, variable=self.progress_var, maximum=100
        )
        self.progress_bar.pack(fill="x")

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(prog_frame, textvariable=self.status_var, font=("", 8)).pack(
            anchor="w", pady=(2, 0)
        )

        # --- Buttons ---
        btn_frame = ttk.Frame(self.root, padding=5)
        btn_frame.pack(fill="x", padx=10)

        self.download_btn = ttk.Button(
            btn_frame, text="Download", command=self._start_download
        )
        self.download_btn.pack(side="left", padx=(0, 5))

        self.cancel_btn = ttk.Button(
            btn_frame, text="Cancel", command=self._cancel_download, state="disabled"
        )
        self.cancel_btn.pack(side="left")

        # --- Log ---
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        log_frame.pack(fill="both", padx=10, pady=(5, 10))

        self.log = scrolledtext.ScrolledText(log_frame, height=10, state="disabled")
        self.log.pack(fill="both", expand=True)

    def _build_interestingness_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Interestingness")

        ttk.Label(tab, text="Date:").grid(row=0, column=0, sticky="w")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.int_date_var = tk.StringVar(value=yesterday)
        ttk.Entry(tab, textvariable=self.int_date_var, width=15).grid(
            row=0, column=1, padx=(5, 0), pady=2, sticky="w"
        )
        ttk.Label(tab, text="(YYYY-MM-DD)", font=("", 8)).grid(
            row=0, column=2, padx=(5, 0), sticky="w"
        )

        ttk.Label(tab, text="Count:").grid(row=1, column=0, sticky="w")
        self.int_count_var = tk.IntVar(value=500)
        ttk.Spinbox(
            tab, textvariable=self.int_count_var, from_=1, to=500, width=8
        ).grid(row=1, column=1, padx=(5, 0), pady=2, sticky="w")

        # Optional user filter
        ttk.Label(tab, text="Username or URL:").grid(row=2, column=0, sticky="w")
        self.int_user_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.int_user_var, width=25).grid(
            row=2, column=1, padx=(5, 5), pady=2, sticky="w"
        )
        self.int_lookup_btn = ttk.Button(
            tab, text="Look Up", command=self._lookup_int_user
        )
        self.int_lookup_btn.grid(row=2, column=2, pady=2)

        self.int_user_status_var = tk.StringVar(value="(optional – filter by user)")
        ttk.Label(tab, textvariable=self.int_user_status_var, font=("", 8)).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(0, 0)
        )

    def _build_search_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Search")
        tab.rowconfigure(2, weight=1)
        tab.columnconfigure(0, weight=1)

        # --- Search fields sub-frame ---
        fields = ttk.Frame(tab)
        fields.grid(row=0, column=0, sticky="ew")

        ttk.Label(fields, text="Keywords:").grid(row=0, column=0, sticky="w")
        self.search_text_var = tk.StringVar()
        ttk.Entry(fields, textvariable=self.search_text_var, width=40).grid(
            row=0, column=1, columnspan=2, padx=(5, 0), pady=2, sticky="w"
        )

        ttk.Label(fields, text="Tags:").grid(row=1, column=0, sticky="w")
        self.search_tags_var = tk.StringVar()
        ttk.Entry(fields, textvariable=self.search_tags_var, width=40).grid(
            row=1, column=1, columnspan=2, padx=(5, 0), pady=2, sticky="w"
        )

        ttk.Label(fields, text="Tag mode:").grid(row=2, column=0, sticky="w")
        self.tag_mode_var = tk.StringVar(value="any")
        tag_mode_frame = ttk.Frame(fields)
        tag_mode_frame.grid(row=2, column=1, sticky="w", padx=(5, 0), pady=2)
        ttk.Radiobutton(tag_mode_frame, text="Any", variable=self.tag_mode_var, value="any").pack(side="left")
        ttk.Radiobutton(tag_mode_frame, text="All", variable=self.tag_mode_var, value="all").pack(side="left", padx=(10, 0))

        ttk.Label(fields, text="Sort:").grid(row=3, column=0, sticky="w")
        self.sort_var = tk.StringVar(value="Relevance")
        ttk.Combobox(
            fields, textvariable=self.sort_var,
            values=list(core.SORT_OPTIONS.keys()),
            state="readonly", width=25,
        ).grid(row=3, column=1, padx=(5, 0), pady=2, sticky="w")

        ttk.Label(fields, text="License:").grid(row=4, column=0, sticky="w")
        self.license_var = tk.StringVar(value="Any License")
        license_values = ["Any License"] + list(core.LICENSE_MAP.keys())
        ttk.Combobox(
            fields, textvariable=self.license_var,
            values=license_values,
            state="readonly", width=25,
        ).grid(row=4, column=1, padx=(5, 0), pady=2, sticky="w")

        ttk.Label(fields, text="Count:").grid(row=5, column=0, sticky="w")
        self.search_count_var = tk.IntVar(value=100)
        ttk.Spinbox(
            fields, textvariable=self.search_count_var, from_=1, to=4000, width=8
        ).grid(row=5, column=1, padx=(5, 0), pady=2, sticky="w")

        # Optional user filter
        ttk.Label(fields, text="Username or URL:").grid(row=6, column=0, sticky="w")
        self.search_user_var = tk.StringVar()
        ttk.Entry(fields, textvariable=self.search_user_var, width=25).grid(
            row=6, column=1, padx=(5, 5), pady=2, sticky="w"
        )
        self.search_lookup_btn = ttk.Button(
            fields, text="Look Up", command=self._lookup_search_user
        )
        self.search_lookup_btn.grid(row=6, column=2, pady=2)

        self.search_user_status_var = tk.StringVar(value="(optional – filter by user)")
        ttk.Label(fields, textvariable=self.search_user_status_var, font=("", 8)).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(0, 0)
        )

        # --- Preview button + status ---
        preview_bar = ttk.Frame(tab)
        preview_bar.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        self.preview_btn = ttk.Button(
            preview_bar, text="Preview", command=self._start_preview
        )
        self.preview_btn.pack(side="left")

        self.preview_status_var = tk.StringVar()
        ttk.Label(
            preview_bar, textvariable=self.preview_status_var, font=("", 8)
        ).pack(side="left", padx=(10, 0))

        # --- Scrollable preview canvas ---
        preview_frame = ttk.LabelFrame(tab, text="Preview", padding=2)
        preview_frame.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)

        self._preview_canvas = tk.Canvas(preview_frame, highlightthickness=0)
        self._preview_scrollbar = ttk.Scrollbar(
            preview_frame, orient="vertical", command=self._preview_canvas.yview
        )
        self._preview_canvas.configure(yscrollcommand=self._preview_scrollbar.set)

        self._preview_scrollbar.grid(row=0, column=1, sticky="ns")
        self._preview_canvas.grid(row=0, column=0, sticky="nsew")

        self._preview_inner = ttk.Frame(self._preview_canvas)
        self._preview_canvas_window = self._preview_canvas.create_window(
            (0, 0), window=self._preview_inner, anchor="nw"
        )

        self._preview_inner.bind("<Configure>", self._on_preview_configure)
        self._preview_canvas.bind("<Configure>", self._on_canvas_configure)
        self._preview_canvas.bind("<Enter>", self._bind_preview_mousewheel)
        self._preview_canvas.bind("<Leave>", self._unbind_preview_mousewheel)

    def _build_user_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="User / Album")

        # Username/URL + lookup
        ttk.Label(tab, text="Username or URL:").grid(row=0, column=0, sticky="w")
        self.user_input_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.user_input_var, width=35).grid(
            row=0, column=1, padx=(5, 5), pady=2, sticky="w"
        )
        self.lookup_btn = ttk.Button(tab, text="Look Up", command=self._lookup_user)
        self.lookup_btn.grid(row=0, column=2, pady=2)

        self.user_status_var = tk.StringVar()
        ttk.Label(tab, textvariable=self.user_status_var, font=("", 8)).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )

        # Radio: Photostream or Album
        self.user_mode_var = tk.StringVar(value="photostream")
        ttk.Radiobutton(
            tab, text="Photostream", variable=self.user_mode_var,
            value="photostream", command=self._on_user_mode_change,
        ).grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(
            tab, text="Album", variable=self.user_mode_var,
            value="album", command=self._on_user_mode_change,
        ).grid(row=2, column=1, sticky="w", padx=(5, 0))

        # Album dropdown
        ttk.Label(tab, text="Album:").grid(row=3, column=0, sticky="w")
        self.album_var = tk.StringVar()
        self.album_combo = ttk.Combobox(
            tab, textvariable=self.album_var,
            state="disabled", width=40,
        )
        self.album_combo.grid(row=3, column=1, columnspan=2, padx=(5, 0), pady=2, sticky="w")

        # Count (for photostream only)
        ttk.Label(tab, text="Count:").grid(row=4, column=0, sticky="w")
        self.user_count_var = tk.IntVar(value=500)
        self.user_count_spinbox = ttk.Spinbox(
            tab, textvariable=self.user_count_var, from_=1, to=5000, width=8
        )
        self.user_count_spinbox.grid(row=4, column=1, padx=(5, 0), pady=2, sticky="w")

    # ================================================================
    # UI Helpers
    # ================================================================

    def _browse_folder(self):
        folder = filedialog.askdirectory(
            initialdir=self.folder_var.get(), title="Select Download Folder"
        )
        if folder:
            self.folder_var.set(folder)

    def _on_user_mode_change(self):
        if self.user_mode_var.get() == "album":
            self.album_combo.config(state="readonly")
            self.user_count_spinbox.config(state="disabled")
        else:
            self.album_combo.config(state="disabled")
            self.user_count_spinbox.config(state="normal")

    # ================================================================
    # Preview
    # ================================================================

    def _on_preview_configure(self, event=None):
        self._preview_canvas.configure(scrollregion=self._preview_canvas.bbox("all"))

    def _on_canvas_configure(self, event=None):
        self._preview_canvas.itemconfigure(
            self._preview_canvas_window, width=event.width
        )

    def _bind_preview_mousewheel(self, event=None):
        self._preview_canvas.bind_all("<MouseWheel>", self._on_preview_mousewheel)

    def _unbind_preview_mousewheel(self, event=None):
        self._preview_canvas.unbind_all("<MouseWheel>")

    def _on_preview_mousewheel(self, event):
        self._preview_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _clear_preview(self):
        for child in self._preview_inner.winfo_children():
            child.destroy()
        self._thumb_images.clear()
        self._preview_photos.clear()

    def _start_preview(self):
        if self._preview_loading:
            return

        api_key = self.api_key_var.get().strip()
        api_secret = self.api_secret_var.get().strip()
        if not api_key or not api_secret:
            messagebox.showerror("Error", "API Key and API Secret are required.")
            return

        text = self.search_text_var.get().strip()
        tags = self.search_tags_var.get().strip()
        if not text and not tags:
            messagebox.showerror("Error", "Enter keywords and/or tags to search.")
            return

        self._preview_loading = True
        self.preview_btn.config(state="disabled")
        self.preview_status_var.set("Searching...")
        self._clear_preview()

        tag_mode = self.tag_mode_var.get()
        sort_label = self.sort_var.get()
        sort_value = core.SORT_OPTIONS.get(sort_label, "relevance")
        license_label = self.license_var.get()
        license_ids = ""
        if license_label != "Any License":
            license_ids = core.LICENSE_MAP.get(license_label, "")

        search_nsid = self._search_user_nsid or ""
        thread = threading.Thread(
            target=self._run_preview,
            args=(api_key, api_secret, text, tags, tag_mode, sort_value, license_ids, search_nsid),
            daemon=True,
        )
        thread.start()

    def _run_preview(self, api_key, api_secret, text, tags, tag_mode, sort, license_ids, user_id):
        try:
            import flickrapi
            fl = flickrapi.FlickrAPI(api_key, api_secret, format="parsed-json")
            kwargs = {
                "extras": "url_sq,owner_name,date_taken",
                "per_page": PREVIEW_LIMIT,
                "page": 1,
                "sort": sort,
                "safe_search": 1,
            }
            if text:
                kwargs["text"] = text
            if tags:
                kwargs["tags"] = tags
                kwargs["tag_mode"] = tag_mode
            if license_ids:
                kwargs["license"] = license_ids
            if user_id:
                kwargs["user_id"] = user_id

            resp = fl.photos.search(**kwargs)
            photos = resp["photos"]["photo"]
            total_available = int(resp["photos"]["total"])

            if not photos:
                self.root.after(0, self._finish_preview, [], [], 0)
                return

            thumb_data = []
            for i, photo in enumerate(photos):
                url = photo.get("url_sq")
                if not url:
                    continue
                try:
                    r = requests.get(url, timeout=10)
                    r.raise_for_status()
                    img = Image.open(BytesIO(r.content))
                    img = img.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                    thumb_data.append((photo, img))
                except Exception:
                    pass
                self.root.after(
                    0, self.preview_status_var.set,
                    f"Loading thumbnails... {i + 1}/{len(photos)}"
                )

            self.root.after(0, self._finish_preview, photos, thumb_data, total_available)

        except Exception as e:
            self.root.after(
                0, self._finish_preview_error, str(e)
            )

    def _finish_preview(self, photos, thumb_data, total_available=0):
        self._preview_loading = False
        self.preview_btn.config(state="normal")

        if not photos:
            self.preview_status_var.set("No photos found.")
            return

        self._preview_photos = photos
        self._thumb_images.clear()

        for idx, (photo, pil_img) in enumerate(thumb_data):
            tk_img = ImageTk.PhotoImage(pil_img)
            self._thumb_images.append(tk_img)

            row = idx // PREVIEW_COLS
            col = idx % PREVIEW_COLS

            cell = ttk.Frame(self._preview_inner)
            cell.grid(row=row, column=col, padx=3, pady=3)

            lbl = ttk.Label(cell, image=tk_img)
            lbl.pack()

            title = photo.get("title", "") or ""
            if isinstance(title, dict):
                title = title.get("_content", "")
            short_title = (title[:12] + "...") if len(title) > 15 else title
            ttk.Label(cell, text=short_title, font=("", 7), width=12, anchor="center").pack()

            # Tooltip with full details
            owner = photo.get("ownername", "") or photo.get("owner", "")
            date = photo.get("datetaken", "")
            tip_text = f"{title}\nBy: {owner}"
            if date:
                tip_text += f"\nDate: {date}"
            Tooltip(cell, tip_text)

        if total_available > len(thumb_data):
            self.preview_status_var.set(
                f"Showing {len(thumb_data)} of {total_available} results"
            )
        else:
            self.preview_status_var.set(f"{len(thumb_data)} results found.")
        self._preview_canvas.yview_moveto(0)

    def _finish_preview_error(self, error):
        self._preview_loading = False
        self.preview_btn.config(state="normal")
        self.preview_status_var.set(f"Error: {error}")

    def _log_msg(self, msg):
        """Thread-safe log append."""
        self.root.after(0, self._append_log, msg)

    def _append_log(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _update_progress(self, current, total):
        """Thread-safe progress update."""
        if total > 0:
            pct = (current / total) * 100
            self.root.after(0, self.progress_var.set, pct)
            self.root.after(0, self.status_var.set, f"{current}/{total} photos")

    def _set_running(self, running):
        self.running = running
        self.root.after(0, lambda: self.download_btn.config(
            state="disabled" if running else "normal"
        ))
        self.root.after(0, lambda: self.cancel_btn.config(
            state="normal" if running else "disabled"
        ))

    # ================================================================
    # Credentials & Settings
    # ================================================================

    def _on_close(self):
        """Save all settings before closing the window."""
        self._save_settings()
        self.root.destroy()

    def _load_credentials(self):
        """Load API credentials from .env file and/or settings.json.

        Priority: settings.json (if non-empty) > .env file > empty.
        """
        # Try .env file first as baseline
        env_path = os.path.join(get_base_path(), ".env")
        load_dotenv(env_path)
        env_key = os.environ.get("FLICKR_API_KEY", "")
        env_secret = os.environ.get("FLICKR_API_SECRET", "")

        # Also try reading .env directly in case load_dotenv didn't work
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

        # Load saved credentials from settings.json (override if non-empty)
        saved_key = ""
        saved_secret = ""
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            saved_key = data.get("api_key", "")
            saved_secret = data.get("api_secret", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # Use saved credentials if available, otherwise fall back to .env
        self.api_key_var.set(saved_key if saved_key else env_key)
        self.api_secret_var.set(saved_secret if saved_secret else env_secret)

    def _save_settings(self):
        data = {
            "api_key": self.api_key_var.get(),
            "api_secret": self.api_secret_var.get(),
            "folder": self.folder_var.get(),
            "size": self.size_var.get(),
            "metadata": self.metadata_var.get(),
            "filename": self.filename_var.get(),
            "int_date": self.int_date_var.get(),
            "int_count": self.int_count_var.get(),
            "search_text": self.search_text_var.get(),
            "search_tags": self.search_tags_var.get(),
            "tag_mode": self.tag_mode_var.get(),
            "sort": self.sort_var.get(),
            "license": self.license_var.get(),
            "search_count": self.search_count_var.get(),
            "int_user": self.int_user_var.get(),
            "search_user": self.search_user_var.get(),
            "user_input": self.user_input_var.get(),
            "user_mode": self.user_mode_var.get(),
            "user_count": self.user_count_var.get(),
            "active_tab": self.notebook.index(self.notebook.select()),
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
            self.folder_var.set(data["folder"])
        if "size" in data:
            self.size_var.set(data["size"])
        if "metadata" in data:
            self.metadata_var.set(data["metadata"])
        if "filename" in data:
            self.filename_var.set(data["filename"])
        if "int_date" in data:
            self.int_date_var.set(data["int_date"])
        if "int_count" in data:
            self.int_count_var.set(data["int_count"])
        if "search_text" in data:
            self.search_text_var.set(data["search_text"])
        if "search_tags" in data:
            self.search_tags_var.set(data["search_tags"])
        if "tag_mode" in data:
            self.tag_mode_var.set(data["tag_mode"])
        if "sort" in data:
            self.sort_var.set(data["sort"])
        if "license" in data:
            self.license_var.set(data["license"])
        if "search_count" in data:
            self.search_count_var.set(data["search_count"])
        if "int_user" in data:
            self.int_user_var.set(data["int_user"])
        if "search_user" in data:
            self.search_user_var.set(data["search_user"])
        if "user_input" in data:
            self.user_input_var.set(data["user_input"])
        if "user_mode" in data:
            self.user_mode_var.set(data["user_mode"])
            self._on_user_mode_change()
        if "user_count" in data:
            self.user_count_var.set(data["user_count"])
        if "active_tab" in data:
            try:
                self.notebook.select(data["active_tab"])
            except Exception:
                pass

    # ================================================================
    # User lookup
    # ================================================================

    def _lookup_int_user(self):
        """Look up user for the Interestingness tab filter."""
        username = self.int_user_var.get().strip()
        if not username:
            # Clear the filter
            self._int_user_nsid = None
            self.int_user_status_var.set("(optional – filter by user)")
            return
        self._resolve_user_for_tab(
            username, self.int_lookup_btn, self.int_user_status_var,
            "_int_user_nsid",
        )

    def _lookup_search_user(self):
        """Look up user for the Search tab filter."""
        username = self.search_user_var.get().strip()
        if not username:
            # Clear the filter
            self._search_user_nsid = None
            self.search_user_status_var.set("(optional – filter by user)")
            return
        self._resolve_user_for_tab(
            username, self.search_lookup_btn, self.search_user_status_var,
            "_search_user_nsid",
        )

    def _resolve_user_for_tab(self, username, btn, status_var, nsid_attr):
        """Generic user resolver that works for any tab."""
        api_key = self.api_key_var.get().strip()
        api_secret = self.api_secret_var.get().strip()
        if not api_key or not api_secret:
            messagebox.showerror("Error", "API Key and API Secret are required.")
            return

        btn.config(state="disabled")
        status_var.set("Looking up user...")
        setattr(self, nsid_attr, None)

        def _do_resolve():
            try:
                dl = core.FlickrDownloader(api_key, api_secret)
                nsid, uname = dl.resolve_user(username)
                setattr(self, nsid_attr, nsid)
                self.root.after(0, lambda: (
                    status_var.set(f"User: {uname} ({nsid})"),
                    btn.config(state="normal"),
                ))
            except Exception as e:
                self.root.after(0, lambda: (
                    status_var.set(f"Error: {e}"),
                    btn.config(state="normal"),
                ))

        threading.Thread(target=_do_resolve, daemon=True).start()

    def _lookup_user(self):
        api_key = self.api_key_var.get().strip()
        api_secret = self.api_secret_var.get().strip()
        if not api_key or not api_secret:
            messagebox.showerror("Error", "API Key and API Secret are required.")
            return

        username = self.user_input_var.get().strip()
        if not username:
            messagebox.showerror("Error", "Enter a username or Flickr URL.")
            return

        self.lookup_btn.config(state="disabled")
        self.user_status_var.set("Looking up user...")
        self.album_combo.set("")
        self.album_combo["values"] = []
        self._user_nsid = None
        self._user_albums = []

        thread = threading.Thread(target=self._do_lookup, args=(api_key, api_secret, username), daemon=True)
        thread.start()

    def _do_lookup(self, api_key, api_secret, username):
        try:
            dl = core.FlickrDownloader(api_key, api_secret)
            nsid, uname = dl.resolve_user(username)
            self._user_nsid = nsid

            # Fetch albums
            albums = dl.fetch_user_albums(nsid)
            self._user_albums = albums
            album_names = [f"{a['title']} ({a['photos']} photos)" for a in albums]

            self.root.after(0, self._finish_lookup, uname, nsid, album_names)
        except Exception as e:
            self.root.after(0, self._finish_lookup_error, str(e))

    def _finish_lookup(self, username, nsid, album_names):
        self.user_status_var.set(f"User: {username} ({nsid})")
        self.album_combo["values"] = album_names
        if album_names:
            self.album_combo.set(album_names[0])
        self.lookup_btn.config(state="normal")

    def _finish_lookup_error(self, error):
        self.user_status_var.set(f"Error: {error}")
        self.lookup_btn.config(state="normal")

    # ================================================================
    # Download
    # ================================================================

    def _start_download(self):
        api_key = self.api_key_var.get().strip()
        api_secret = self.api_secret_var.get().strip()
        if not api_key or not api_secret:
            messagebox.showerror("Error", "API Key and API Secret are required.")
            return

        # Clear log
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

        self.progress_var.set(0)
        self.status_var.set("Starting...")
        self._save_settings()
        self._set_running(True)

        thread = threading.Thread(target=self._run_download, args=(api_key, api_secret), daemon=True)
        thread.start()

    def _cancel_download(self):
        if self.downloader:
            self.downloader.cancel()
            self.status_var.set("Cancelling...")

    def _run_download(self, api_key, api_secret):
        try:
            self.downloader = core.FlickrDownloader(api_key, api_secret)
            self.downloader.set_callbacks(
                progress_cb=self._update_progress,
                log_cb=self._log_msg,
            )

            # Determine active tab
            tab_index = self.notebook.index(self.notebook.select())
            photos = []

            if tab_index == 0:
                # Interestingness
                date_str = self.int_date_var.get().strip()
                count = self.int_count_var.get()
                photos = self.downloader.fetch_interestingness(date_str, count)
                # Client-side filter by user if set
                if self._int_user_nsid:
                    nsid = self._int_user_nsid
                    photos = [p for p in photos if p.get("owner") == nsid]
                    self._log_msg(f"Filtered to {len(photos)} photos by user {nsid}.")

            elif tab_index == 1:
                # Search
                text = self.search_text_var.get().strip()
                tags = self.search_tags_var.get().strip()
                if not text and not tags:
                    self._log_msg("Error: Enter keywords and/or tags to search.")
                    return

                tag_mode = self.tag_mode_var.get()
                sort_label = self.sort_var.get()
                sort_value = core.SORT_OPTIONS.get(sort_label, "relevance")
                license_label = self.license_var.get()
                license_ids = ""
                if license_label != "Any License":
                    license_ids = core.LICENSE_MAP.get(license_label, "")
                count = self.search_count_var.get()

                search_nsid = self._search_user_nsid or ""
                photos = self.downloader.search_photos(
                    text=text, tags=tags, tag_mode=tag_mode,
                    sort=sort_value, license_ids=license_ids, count=count,
                    user_id=search_nsid,
                )

            elif tab_index == 2:
                # User / Album
                if not self._user_nsid:
                    self._log_msg("Error: Look up a user first.")
                    return

                mode = self.user_mode_var.get()
                if mode == "photostream":
                    count = self.user_count_var.get()
                    photos = self.downloader.fetch_user_photos(self._user_nsid, count)
                else:
                    # Album
                    album_idx = self.album_combo.current()
                    if album_idx < 0 or album_idx >= len(self._user_albums):
                        self._log_msg("Error: Select an album first.")
                        return
                    album = self._user_albums[album_idx]
                    self._log_msg(f"Downloading album: {album['title']}")
                    photos = self.downloader.fetch_album_photos(
                        self._user_nsid, album["id"]
                    )

            if self.downloader.is_cancelled:
                self._log_msg("Operation cancelled.")
                return

            if not photos:
                self._log_msg("No photos found.")
                return

            # Download
            size_label = self.size_var.get()
            size_key = core.PHOTO_SIZES.get(size_label, "url_l")
            download_dir = self.folder_var.get()
            embed = self.metadata_var.get()
            filename_tmpl = self.filename_var.get() or "{title}_{id}"

            self._log_msg(f"Downloading {len(photos)} photos to: {download_dir}")
            self.downloader.download_photos(
                photos, download_dir, size_key=size_key,
                embed_metadata=embed, filename_template=filename_tmpl,
            )

        except core.CancelledError:
            self._log_msg("Operation cancelled.")
        except Exception as e:
            self._log_msg(f"\nError: {e}")
        finally:
            self.root.after(0, self._download_finished)

    def _download_finished(self):
        self._set_running(False)
        if self.downloader and not self.downloader.is_cancelled:
            self.status_var.set("Done")
        else:
            self.status_var.set("Cancelled")
        self.downloader = None


def main():
    root = tk.Tk()
    FlickrDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
