"""
YouTube Playlist Downloader — Windows desktop app.
Download entire playlists with selectable quality, per-video overrides,
pause/resume/retry, and MP3 audio extraction.
"""
import os
import re
import sys
import json
import subprocess
import threading
import queue
import urllib.request
import ctypes
import io

import customtkinter as ctk
from PIL import Image

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_NAME = "YouTube Playlist Downloader"
COLORS = {
    "bg": "#16161c",
    "card": "#1f1f28",
    "card2": "#26262f",
    "border": "#32323c",
    "accent": "#e62d2d",          # YouTube red
    "accent_hover": "#ff3b3b",
    "accent_dim": "#4a1f1f",
    "green": "#2ecc71",
    "amber": "#f5b942",
    "text": "#eaeaf0",
    "text_dim": "#9a9aa5",
}
QUALITIES = ["2160p", "1440p", "1080p", "720p", "480p", "360p", "Audio (MP3)"]
BITRATES = ["320", "192", "128"]


# --------------------------------------------------------------------------- #
# Paths / resources
# --------------------------------------------------------------------------- #
def res_path(rel: str) -> str:
    """Resolve bundled resources whether running as script or frozen exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def find_tool(name: str, subdir: str = "") -> str | None:
    """Find yt-dlp.exe / ffmpeg.exe in bundled resources or dev layout."""
    candidates = []
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
        candidates += [os.path.join(base, subdir, name), os.path.join(base, name)]
        # next to the exe too
        exe_dir = os.path.dirname(sys.executable)
        candidates += [os.path.join(exe_dir, subdir, name), os.path.join(exe_dir, name)]
    else:
        root = os.path.dirname(os.path.abspath(__file__))
        candidates += [os.path.join(root, subdir, name), os.path.join(root, name)]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


YTDLP = find_tool("yt-dlp.exe", "bin")
FFMPEG = find_tool("ffmpeg.exe", "ffmpeg")
if YTDLP is None:
    # last resort: the module installed in this interpreter
    YTDLP = [sys.executable, "-m", "yt_dlp"]
LOGO = res_path(os.path.join("assets", "logo.png"))
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def fmt_time(seconds) -> str:
    if seconds in (None, 0):
        return "--:--"
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_progress(line: str):
    """Return (percent, speed_str, eta_str) from a yt-dlp progress line."""
    if "[download]" not in line:
        return None
    m = re.search(r"\[download\]\s+([\d.]+)%", line)
    if not m:
        return None
    pct = float(m.group(1))
    speed = eta = ""
    ms = re.search(r"at\s+(?:Unknown B|([\d.]+)(\w+)/s)", line)
    if ms and ms.group(1):
        speed = f"{ms.group(1)} {ms.group(2)}/s"
    me = re.search(r"ETA\s+([\d:]+|Unknown)", line)
    if me:
        eta = me.group(1)
    return pct, speed, eta


def friendly_error(msg: str):
    """Map a raw yt-dlp error to (short_title, actionable_hint). None if unknown."""
    m = (msg or "").lower()
    if "dpapi" in m or "app-bound" in m or "cannot decrypt" in m or "decrypt" in m and "cookie" in m:
        return ("Chrome cookie error",
                "Chrome v127+ encrypts cookies so external tools can't read them. "
                "Pick Edge or Firefox under 'Browser cookies', or export a cookies.txt "
                "file (browser extension: 'Get cookies.txt LOCALLY') and load it with "
                "+ cookies.txt.")
    if "different account" in m:
        return ("Cookie mismatch",
                "Re-export a fresh cookies.txt from the same browser profile you are "
                "logged into YouTube with.")
    if "sign in to confirm" in m or "not a bot" in m:
        return ("YouTube bot check",
                "Select Edge or Firefox under 'Browser cookies', or load a cookies.txt "
                "file, then retry.")
    if "unsupported url" in m:
        return ("Unsupported URL", "Use a standard youtube.com video or playlist link.")
    if "private video" in m or "members-only" in m or "unavailable" in m:
        return ("Video unavailable", "This video is private, deleted, or members-only.")
    return (None, None)


class VideoRow(ctk.CTkFrame):
    """One playlist entry in the scrollable list."""

    def __init__(self, master, app, data):
        super().__init__(master, fg_color=COLORS["card"], corner_radius=12,
                         border_width=1, border_color=COLORS["border"])
        self.app = app
        self.data = data                      # dict: id,title,duration,url,thumb
        self.state = "pending"                # pending|queued|downloading|paused|done|failed
        self.proc = None                      # active subprocess
        self.pct = 0.0
        self.include_var = ctk.BooleanVar(value=True)
        self.quality_var = ctk.StringVar(value="Global")

        self.grid_columnconfigure(1, weight=1)
        pad = {"padx": 10, "pady": 8}

        self.include = ctk.CTkCheckBox(self, width=26, checkbox_width=22,
                                       checkbox_height=22, text="",
                                       variable=self.include_var,
                                       fg_color=COLORS["accent"],
                                       hover_color=COLORS["accent_hover"])
        self.include.grid(row=0, column=0, sticky="ns", **pad)

        self.thumb_label = ctk.CTkLabel(self, text="", width=96, height=54,
                                        fg_color=COLORS["card2"], corner_radius=8)
        self.thumb_label.grid(row=0, column=1, **pad)

        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.grid(row=0, column=2, sticky="nsew", padx=(0, 10), pady=8)
        mid.grid_columnconfigure(0, weight=1)

        self.title_lbl = ctk.CTkLabel(
            mid, text=data["title"], font=ctk.CTkFont("Segoe UI", 13, "bold"),
            anchor="w", text_color=COLORS["text"])
        self.title_lbl.grid(row=0, column=0, sticky="ew")

        bottom = ctk.CTkFrame(mid, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew")
        bottom.grid_columnconfigure(4, weight=1)

        self.dur_lbl = ctk.CTkLabel(
            bottom, text=fmt_time(data.get("duration")),
            font=ctk.CTkFont("Segoe UI", 11), text_color=COLORS["text_dim"], width=52)
        self.dur_lbl.grid(row=0, column=0, sticky="w")

        self.status_lbl = ctk.CTkLabel(
            bottom, text="Ready", font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=COLORS["text_dim"], width=210, anchor="w")
        self.status_lbl.grid(row=0, column=1, sticky="w", padx=8)

        self.q_menu = ctk.CTkOptionMenu(
            bottom, values=["Global", *QUALITIES], variable=self.quality_var,
            width=130, height=26, font=ctk.CTkFont("Segoe UI", 11),
            fg_color=COLORS["card2"], button_color=COLORS["border"],
            button_hover_color=COLORS["border"], text_color=COLORS["text"])
        self.q_menu.grid(row=0, column=2, sticky="e")
        self.q_menu.configure(command=lambda *_: self.app.save_layout())

        self.prog = ctk.CTkProgressBar(self, height=6, corner_radius=3,
                                       progress_color=COLORS["accent"])
        self.prog.set(0)
        self.prog.grid(row=0, column=3, sticky="ew", padx=(0, 10), pady=8)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=0, column=4, padx=(0, 10), pady=8)

        self.pause_btn = ctk.CTkButton(
            btns, text="⏸", width=30, height=30, corner_radius=8,
            fg_color=COLORS["card2"], hover_color=COLORS["border"],
            font=ctk.CTkFont(size=13), command=self.toggle_pause, state="disabled")
        self.pause_btn.grid(row=0, column=0, padx=3)

        self.retry_btn = ctk.CTkButton(
            btns, text="⟳", width=30, height=30, corner_radius=8,
            fg_color=COLORS["card2"], hover_color=COLORS["border"],
            font=ctk.CTkFont(size=13), command=self.retry, state="disabled")
        self.retry_btn.grid(row=0, column=1, padx=3)

        self.del_btn = ctk.CTkButton(
            btns, text="🗑", width=30, height=30, corner_radius=8,
            fg_color=COLORS["card2"], hover_color=COLORS["accent_dim"],
            font=ctk.CTkFont(size=13), command=self.remove)
        self.del_btn.grid(row=0, column=2, padx=3)

        self.load_thumbnail()
        # initialize button states explicitly — without this the pause/retry
        # buttons stay disabled on fresh rows and look "missing"
        self.set_state("pending", "Ready")

    # -- thumbnail -----------------------------------------------------------
    def load_thumbnail(self):
        def worker():
            try:
                url = f"https://i.ytimg.com/vi/{self.data['id']}/mqdefault.jpg"
                with urllib.request.urlopen(url, timeout=10) as r:
                    raw = r.read()
                img = Image.open(io.BytesIO(raw)).resize((96, 54))
                self.app.after(0, lambda: self._set_thumb(img))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _set_thumb(self, img):
        try:
            self.thumb_label.configure(image=ctk.CTkImage(img, size=(96, 54)), text="")
        except Exception:
            pass

    # -- state / UI ----------------------------------------------------------
    def set_state(self, state, text=None, color=None, pct=None, speed=None):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.state = state
        if text is not None:
            self.status_lbl.configure(text=text, text_color=color or COLORS["text_dim"])
        if pct is not None:
            self.prog.set(pct / 100.0)
            self.pct = pct
        downloading = state == "downloading"
        self.pause_btn.configure(
            state="normal" if downloading or state == "paused" else "disabled",
            text="▶" if state == "paused" else "⏸")
        self.retry_btn.configure(state="normal" if state in ("failed", "paused", "done", "pending") else "disabled")
        if downloading:
            self.prog.configure(progress_color=COLORS["accent"])
        elif state == "done":
            self.prog.configure(progress_color=COLORS["green"])
        elif state == "failed":
            self.prog.configure(progress_color=COLORS["accent_dim"])
        if state == "downloading" and speed:
            self.status_lbl.configure(text=f"{self.status_lbl.cget('text')}  •  {speed}")

    def toggle_pause(self):
        if self.state == "downloading":
            if self.proc:
                self.app._terminate_tree(self.proc)
            self.set_state("paused", "Paused", COLORS["amber"],
                           pct=self.pct)
            self.app.on_row_paused(self)
        elif self.state == "paused":
            self.set_state("queued", "Resuming…", COLORS["amber"], pct=self.pct)
            self.app.enqueue(self, front=True)

    def retry(self):
        if self.state in ("failed", "paused", "pending", "done"):
            self.set_state("queued", "Queued", COLORS["amber"], pct=self.pct)
            self.app.enqueue(self)

    def remove(self):
        """Delete this video from the list (stops it if it is downloading)."""
        self.app.remove_row(self)

    def effective_quality(self):
        q = self.quality_var.get()
        return self.app.global_quality.get() if q == "Global" else q


# --------------------------------------------------------------------------- #
# Main application
# --------------------------------------------------------------------------- #
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x720")
        self.minsize(860, 560)
        self.configure(fg_color=COLORS["bg"])
        if os.name == "nt":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YTPD.1")
            except Exception:
                pass

        self.rows: list[VideoRow] = []
        self.queue: queue.Queue = queue.Queue()
        self.qseq = []                # ordering for front-insertion
        self.worker = None
        self.current: VideoRow | None = None
        self.stop_all = False
        self.playlist_title = None

        self._build_header()
        self._build_input()
        self._build_list()
        self._build_footer()
        self.load_layout()

    # ------------------------------------------------------------------ UI --
    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=0, height=64)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=20)
        if os.path.isfile(LOGO):
            img = Image.open(LOGO)
            ctk.CTkLabel(left, image=ctk.CTkImage(img, size=(36, 36)), text="").pack(
                side="left", padx=(0, 12))
        ctk.CTkLabel(left, text=APP_NAME,
                     font=ctk.CTkFont("Segoe UI", 19, "bold")).pack(side="left")
        ctk.CTkButton(bar, text="⚙  Settings", width=110, height=34,
                      corner_radius=10, fg_color=COLORS["card2"],
                      hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      command=self.open_settings).pack(side="right", padx=(0, 20))
        ctk.CTkLabel(bar, text="powered by yt-dlp", font=ctk.CTkFont("Segoe UI", 11),
                     text_color=COLORS["text_dim"]).pack(side="right")

    def _build_input(self):
        card = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14)
        card.pack(fill="x", padx=20, pady=(16, 0))
        card.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            card, placeholder_text="Paste a YouTube playlist or video URL…",
            height=40, font=ctk.CTkFont("Segoe UI", 13),
            fg_color=COLORS["card2"], border_color=COLORS["border"])
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(16, 10), pady=14)
        self.url_entry.bind("<Return>", lambda e: self.fetch())

        self.fetch_btn = ctk.CTkButton(
            card, text="Fetch Playlist", width=140, height=40, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            command=self.fetch)
        self.fetch_btn.grid(row=0, column=1, padx=(0, 16), pady=14)

        opts = ctk.CTkFrame(card, fg_color="transparent")
        opts.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))

        ctk.CTkLabel(opts, text="Quality:", font=ctk.CTkFont("Segoe UI", 12),
                     text_color=COLORS["text_dim"]).grid(row=0, column=0, padx=(0, 6))
        self.global_quality = ctk.StringVar(value="1080p")
        self.q_menu = ctk.CTkOptionMenu(
            opts, values=QUALITIES, variable=self.global_quality, width=130, height=30,
            font=ctk.CTkFont("Segoe UI", 12), fg_color=COLORS["card2"],
            button_color=COLORS["border"], button_hover_color=COLORS["border"])
        self.q_menu.grid(row=0, column=1, padx=(0, 18))
        self.q_menu.configure(command=self._on_quality_change)

        self.bitrate_lbl = ctk.CTkLabel(opts, text="Bitrate:", font=ctk.CTkFont("Segoe UI", 12),
                                        text_color=COLORS["text_dim"])
        self.global_bitrate = ctk.StringVar(value="320")
        self.br_menu = ctk.CTkOptionMenu(
            opts, values=BITRATES, variable=self.global_bitrate, width=90, height=30,
            font=ctk.CTkFont("Segoe UI", 12), fg_color=COLORS["card2"],
            button_color=COLORS["border"], button_hover_color=COLORS["border"])
        # placed/re-gridded dynamically by _on_quality_change

        ctk.CTkLabel(opts, text="Output:", font=ctk.CTkFont("Segoe UI", 12),
                     text_color=COLORS["text_dim"]).grid(row=0, column=4, padx=(0, 6))
        self.outdir = ctk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        ctk.CTkButton(opts, text="📁 Choose", width=100, height=30, corner_radius=8,
                      fg_color=COLORS["card2"], hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12), command=self.pick_dir).grid(
            row=0, column=5, padx=(0, 4))
        self.dir_lbl = ctk.CTkLabel(opts, text=self.outdir.get(),
                                    font=ctk.CTkFont("Segoe UI", 11),
                                    text_color=COLORS["text_dim"])
        self.dir_lbl.grid(row=1, column=5, sticky="w", padx=(0, 4))
        # keep the inline path label in sync when the folder changes in Settings
        self.outdir.trace_add("write",
                              lambda *_: self.dir_lbl.configure(text=self.outdir.get()))

        self.subfolder_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Save in subfolder named after the playlist",
                        variable=self.subfolder_var, font=ctk.CTkFont("Segoe UI", 12),
                        checkbox_height=20, checkbox_width=20,
                        fg_color=COLORS["accent"],
                        hover_color=COLORS["accent_hover"]).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        cookies_row = ctk.CTkFrame(card, fg_color="transparent")
        cookies_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))
        ctk.CTkLabel(cookies_row, text="Browser cookies (fixes “sign in to confirm” bot checks):",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self.cookies_browser = ctk.StringVar(value="None")
        ctk.CTkOptionMenu(
            cookies_row, values=["None", "Edge", "Chrome", "Firefox", "Brave"],
            variable=self.cookies_browser, width=110, height=30,
            font=ctk.CTkFont("Segoe UI", 12), fg_color=COLORS["card2"],
            button_color=COLORS["border"], button_hover_color=COLORS["border"],
            command=lambda *_: self.save_layout()).pack(side="left", padx=(8, 0))

        self.cookies_file = ctk.StringVar(value="")
        ctk.CTkButton(cookies_row, text="+ cookies.txt…", width=120, height=30,
                      corner_radius=8, fg_color=COLORS["card2"],
                      hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12),
                      command=self.pick_cookies_file).pack(side="left", padx=(10, 0))
        self.cookies_file_lbl = ctk.CTkLabel(cookies_row, text="",
                                             font=ctk.CTkFont("Segoe UI", 11),
                                             text_color=COLORS["text_dim"])
        self.cookies_file_lbl.pack(side="left", padx=6)

        ctk.CTkButton(opts, text="Select all", width=90, height=30, corner_radius=8,
                      fg_color=COLORS["card2"], hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12),
                      command=lambda: self._toggle_all(True)).grid(row=1, column=3, padx=(30, 4), pady=(8, 0), sticky="e")
        ctk.CTkButton(opts, text="Clear", width=70, height=30, corner_radius=8,
                      fg_color=COLORS["card2"], hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12),
                      command=lambda: self._toggle_all(False)).grid(row=1, column=4, pady=(8, 0), sticky="e")
        self._on_quality_change()

    def _on_quality_change(self, *_):
        audio = self.global_quality.get() == "Audio (MP3)"
        if audio:
            self.bitrate_lbl.grid(row=0, column=2, padx=(0, 6))
            self.br_menu.grid(row=0, column=3, padx=(0, 18))
        else:
            self.bitrate_lbl.grid_remove()
            self.br_menu.grid_remove()
        self.save_layout()

    def _toggle_all(self, value):
        for r in self.rows:
            if r.state in ("pending", "done", "failed", "paused"):
                r.include_var.set(value)

    def _build_list(self):
        wrap = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14)
        wrap.pack(fill="both", expand=True, padx=20, pady=(14, 0))
        top = ctk.CTkFrame(wrap, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 0))
        self.list_lbl = ctk.CTkLabel(
            top, text="No playlist loaded — paste a URL above and click “Fetch Playlist”",
            font=ctk.CTkFont("Segoe UI", 13), text_color=COLORS["text_dim"])
        self.list_lbl.pack(side="left")
        self.clear_list_btn = ctk.CTkButton(
            top, text="🗑  Clear list", width=100, height=28, corner_radius=8,
            fg_color=COLORS["card2"], hover_color=COLORS["accent_dim"],
            font=ctk.CTkFont("Segoe UI", 12), command=self.clear_list)
        self.clear_list_btn.pack(side="right")
        self.scroll = ctk.CTkScrollableFrame(wrap, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    def _build_footer(self):
        bar = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14, height=86)
        bar.pack(fill="x", padx=20, pady=14)
        bar.pack_propagate(False)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=18, pady=12)
        left.grid_columnconfigure(0, weight=1)

        self.global_prog = ctk.CTkProgressBar(left, height=10, corner_radius=5,
                                              progress_color=COLORS["green"])
        self.global_prog.set(0)
        self.global_prog.grid(row=0, column=0, sticky="ew")

        self.status_lbl = ctk.CTkLabel(left, text="Idle", font=ctk.CTkFont("Segoe UI", 12),
                                       text_color=COLORS["text_dim"], anchor="w")
        self.status_lbl.grid(row=1, column=0, sticky="w", pady=(4, 0))

        btns = ctk.CTkFrame(bar, fg_color="transparent")
        btns.pack(side="right", padx=18)
        self.start_btn = ctk.CTkButton(
            btns, text="⬇  Download All", width=160, height=42, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self.start_all)
        self.start_btn.grid(row=0, column=0, padx=6)
        self.stop_btn = ctk.CTkButton(
            btns, text="■  Stop", width=100, height=42, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=COLORS["card2"], hover_color=COLORS["accent_dim"],
            state="disabled", command=self.stop_everything)
        self.stop_btn.grid(row=0, column=1, padx=6)

    # ------------------------------------------------------------- actions --
    def pick_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=self.outdir.get())
        if d:
            self.outdir.set(d)
            self.dir_lbl.configure(text=d)
            self.save_layout()

    def set_status(self, text, color=COLORS["text_dim"]):
        self.status_lbl.configure(text=text, text_color=color)

    def fetch(self):
        url = self.url_entry.get().strip()
        if not url:
            self.set_status("Enter a URL first.", COLORS["amber"])
            return
        self.fetch_btn.configure(state="disabled", text="Fetching…")
        self.set_status("Fetching playlist info…")
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def _fetch_worker(self, url):
        try:
            import yt_dlp
            opts = {"extract_flat": "in_playlist", "skip_download": True,
                    "quiet": True, "no_warnings": True}
            browser = self.cookies_browser.get().lower()
            if browser and browser != "none":
                opts["cookiesfrombrowser"] = (browser,)
            cf = self.cookies_file.get()
            if cf and os.path.isfile(cf):
                opts["cookiefile"] = cf
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if "entries" in info:
                entries = list(info.get("entries") or [])
                playlist_title = info.get("title")
            else:
                entries = [info]
                playlist_title = None
            vids = [{"id": (e.get("id") or ""), "title": e.get("title") or "Untitled",
                     "duration": e.get("duration"),
                     "url": e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}"}
                    for e in entries]
            self.after(0, lambda: self._populate(vids, playlist_title))
        except Exception as ex:
            msg = str(ex)
            self.after(0, lambda: self._fetch_error(msg))

    def _populate(self, vids, playlist_title):
        self.playlist_title = playlist_title
        for r in self.rows:
            if r.proc:
                self._terminate_tree(r.proc)
            r.state = "removed"
            r.destroy()
        self.rows.clear()
        self.qseq.clear()
        for v in vids:
            row = VideoRow(self.scroll, self, v)
            row.pack(fill="x", pady=5, padx=4)
            self.rows.append(row)
        self.fetch_btn.configure(state="normal", text="Fetch Playlist")
        saved = self.load_saved_qualities()
        if saved:
            for r in self.rows:
                if r.data["id"] in saved:
                    r.quality_var.set(saved[r.data["id"]])
        total = len(vids)
        self.list_lbl.configure(
            text=(f"“{playlist_title}” — " if playlist_title else "")
                 + f"{total} video{'s' if total != 1 else ''} loaded")
        self.set_status(f"Loaded {total} video{'s' if total != 1 else ''}"
                        + (f" from “{playlist_title}”" if playlist_title else ""))

    def _fetch_error(self, msg):
        self.fetch_btn.configure(state="normal", text="Fetch Playlist")
        title, hint = friendly_error(msg)
        if title:
            self.set_status(f"Fetch failed: {title} → {hint}", COLORS["amber"])
        else:
            self.set_status(f"Fetch failed: {msg[:140]}", COLORS["accent"])

    def pick_cookies_file(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename(
            title="Select a cookies.txt file (Netscape format)",
            filetypes=[("cookies.txt", "*.txt;*.cookies"), ("All files", "*.*")],
            initialdir=self.outdir.get())
        if f:
            self.cookies_file.set(f)
            self.cookies_file_lbl.configure(text=os.path.basename(f))
            self.save_layout()

    def _cookies_args(self):
        """yt-dlp args for the current cookie settings (file takes priority)."""
        cf = self.cookies_file.get()
        if cf and os.path.isfile(cf):
            return ["--cookies", cf]
        browser = self.cookies_browser.get()
        if browser and browser != "None":
            return ["--cookies-from-browser", browser.lower()]
        return []

    # ------------------------------------------------------------- settings --
    def _clear_cookies_file(self):
        self.cookies_file.set("")
        self.cookies_file_lbl.configure(text="")
        self.save_layout()

    def open_settings(self):
        win = getattr(self, "_settings_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        win = ctk.CTkToplevel(self)
        self._settings_win = win
        win.title("Settings")
        win.geometry("580x480")
        win.minsize(540, 460)
        win.configure(fg_color=COLORS["bg"])
        win.transient(self)

        card = ctk.CTkFrame(win, fg_color="transparent")
        card.pack(fill="both", expand=True, padx=24, pady=20)
        card.grid_columnconfigure(1, weight=1)
        row = [0]

        def section(text):
            row[0] += 1
            ctk.CTkLabel(card, text=text, font=ctk.CTkFont("Segoe UI", 13, "bold"),
                         anchor="w").grid(row=row[0], column=0, columnspan=2,
                                          sticky="w", pady=(16, 6))

        def hint(text):
            row[0] += 1
            ctk.CTkLabel(card, text=text, font=ctk.CTkFont("Segoe UI", 11),
                         text_color=COLORS["text_dim"], anchor="w",
                         wraplength=500, justify="left").grid(
                row=row[0], column=0, columnspan=2, sticky="w", pady=(0, 4))

        # -- output folder
        section("Output folder")
        row[0] += 1
        folder = ctk.CTkFrame(card, fg_color="transparent")
        folder.grid(row=row[0], column=0, columnspan=2, sticky="ew")
        folder.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(folder, textvariable=self.outdir, height=32,
                     font=ctk.CTkFont("Segoe UI", 12),
                     fg_color=COLORS["card2"],
                     border_color=COLORS["border"]).grid(
            row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(folder, text="📁 Browse", width=100, height=32,
                      corner_radius=8, fg_color=COLORS["card2"],
                      hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12),
                      command=self.pick_dir).grid(row=0, column=1)

        # -- quality
        section("Default quality")
        row[0] += 1
        qrow = ctk.CTkFrame(card, fg_color="transparent")
        qrow.grid(row=row[0], column=0, columnspan=2, sticky="w")
        ctk.CTkLabel(qrow, text="Video:", font=ctk.CTkFont("Segoe UI", 12),
                     text_color=COLORS["text_dim"]).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkOptionMenu(qrow, values=QUALITIES, variable=self.global_quality,
                          width=130, height=30, font=ctk.CTkFont("Segoe UI", 12),
                          fg_color=COLORS["card2"], button_color=COLORS["border"],
                          button_hover_color=COLORS["border"],
                          command=lambda *_: self._on_quality_change()).grid(
            row=0, column=1, padx=(0, 18))
        ctk.CTkLabel(qrow, text="MP3 bitrate:", font=ctk.CTkFont("Segoe UI", 12),
                     text_color=COLORS["text_dim"]).grid(row=0, column=2, padx=(0, 6))
        ctk.CTkOptionMenu(qrow, values=BITRATES, variable=self.global_bitrate,
                          width=90, height=30, font=ctk.CTkFont("Segoe UI", 12),
                          fg_color=COLORS["card2"], button_color=COLORS["border"],
                          button_hover_color=COLORS["border"]).grid(row=0, column=3)

        # -- subfolder
        row[0] += 1
        ctk.CTkCheckBox(card, text="Save in subfolder named after the playlist",
                        variable=self.subfolder_var,
                        font=ctk.CTkFont("Segoe UI", 12),
                        checkbox_height=20, checkbox_width=20,
                        fg_color=COLORS["accent"],
                        hover_color=COLORS["accent_hover"]).grid(
            row=row[0], column=0, columnspan=2, sticky="w", pady=(10, 0))

        # -- cookies
        section("Browser cookies (fixes “sign in to confirm” bot checks)")
        row[0] += 1
        crow = ctk.CTkFrame(card, fg_color="transparent")
        crow.grid(row=row[0], column=0, columnspan=2, sticky="w")
        ctk.CTkOptionMenu(crow, values=["None", "Edge", "Chrome", "Firefox", "Brave"],
                          variable=self.cookies_browser, width=110, height=30,
                          font=ctk.CTkFont("Segoe UI", 12),
                          fg_color=COLORS["card2"],
                          button_color=COLORS["border"],
                          button_hover_color=COLORS["border"],
                          command=lambda *_: self.save_layout()).grid(
            row=0, column=0, padx=(0, 10))
        ctk.CTkButton(crow, text="+ cookies.txt…", width=120, height=30,
                      corner_radius=8, fg_color=COLORS["card2"],
                      hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12),
                      command=self.pick_cookies_file).grid(row=0, column=1,
                                                           padx=(0, 10))
        ctk.CTkButton(crow, text="✕ Clear file", width=100, height=30,
                      corner_radius=8, fg_color=COLORS["card2"],
                      hover_color=COLORS["border"],
                      font=ctk.CTkFont("Segoe UI", 12),
                      command=self._clear_cookies_file).grid(row=0, column=2)
        hint("Chrome v127+ often blocks cookie decryption for external tools — "
             "Edge or Firefox usually works. A loaded cookies.txt file always "
             "overrides the browser setting.")

        # -- save
        row[0] += 1
        ctk.CTkButton(card, text="Save & Close", width=140, height=36,
                      corner_radius=10, fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      font=ctk.CTkFont("Segoe UI", 13, "bold"),
                      command=lambda: (self.save_layout(), win.destroy())).grid(
            row=row[0], column=0, columnspan=2, sticky="e", pady=(22, 0))

    # ------------------------------------------------------------- downloads --
    def start_all(self):
        self.stop_all = False
        targets = [r for r in self.rows if r.include_var.get()
                   and r.state in ("pending", "failed", "paused", "done")]
        if not targets:
            self.set_status("Nothing selected to download.", COLORS["amber"])
            return
        for r in targets:
            if r.state == "paused":
                continue  # resume separately; part files keep progress
            r.set_state("queued", "Queued", COLORS["amber"], pct=r.pct if r.state != "done" else 0)
            self.enqueue(r)
        self.stop_btn.configure(state="normal")
        self.set_status("Starting downloads…")
        self.save_layout()

    def stop_everything(self):
        self.stop_all = True
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.qseq.clear()
        if self.current and self.current.proc:
            self._terminate_tree(self.current.proc)
        for r in self.rows:
            if r.state in ("queued", "downloading"):
                r.set_state("pending", "Stopped", COLORS["text_dim"], pct=r.pct)
        self.stop_btn.configure(state="disabled")
        self.set_status("Stopped.", COLORS["amber"])

    def _terminate_tree(self, proc):
        """Kill a yt-dlp process and everything it spawned (ffmpeg, etc.)."""
        if proc is None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=5)
            else:
                proc.terminate()
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

    def enqueue(self, row, front=False):
        self.stop_all = False          # a new/queued download cancels a prior Stop
        if front:
            self.qseq.insert(0, row)
        else:
            self.qseq.append(row)
        self.queue.put(row)
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._download_loop, daemon=True)
            self.worker.start()

    def on_row_paused(self, row):
        self.qseq = [r for r in self.qseq if r is not row]

    def remove_row(self, row):
        """Delete one video from the list (kills its download if active)."""
        if row.proc:
            self._terminate_tree(row.proc)
        row.state = "removed"          # worker/_download_one will skip it
        self.qseq = [r for r in self.qseq if r is not row]
        if self.current is row:
            self.current = None
        if row in self.rows:
            self.rows.remove(row)
        try:
            row.destroy()
        except Exception:
            pass
        self._update_overall()
        self.save_layout()

    def clear_list(self):
        """Delete every video from the list."""
        if not self.rows:
            return
        for r in list(self.rows):
            self.remove_row(r)
        self.list_lbl.configure(
            text="No playlist loaded — paste a URL above and click “Fetch Playlist”")
        self.set_status("List cleared.", COLORS["amber"])

    def _download_loop(self):
        while True:
            try:
                row = self.queue.get(timeout=2)
            except queue.Empty:
                if self.current is None:
                    return
                continue
            if row.state != "queued":
                continue
            if self.stop_all:
                break
            self._download_one(row)

    def _download_one(self, row):
        self.current = row
        quality = row.effective_quality()
        outdir = self.outdir.get()
        if self.subfolder_var.get() and self.playlist_title:
            safe = re.sub(r'[<>:"/\\|?*]', "_", self.playlist_title).strip(" .")
            outdir = os.path.join(outdir, safe)
        os.makedirs(outdir, exist_ok=True)

        cmd = list(YTDLP) if isinstance(YTDLP, list) else [YTDLP]
        cmd += [row.data["url"], "--newline", "--no-playlist", "--color", "no_color",
                "--no-warnings", "--continue", "--retries", "3",
                "-P", outdir, "-o", "%(title)s.%(ext)s"]
        browser = self.cookies_browser.get()
        if browser and browser != "None" and not (self.cookies_file.get()
                                                  and os.path.isfile(self.cookies_file.get())):
            cmd += ["--cookies-from-browser", browser.lower()]
        if quality == "Audio (MP3)":
            cmd += ["-x", "--audio-format", "mp3",
                    "--audio-quality", f"{self.global_bitrate.get()}K"]
        else:
            h = int(quality.replace("p", ""))
            cmd += ["-f", f"bv*[height<={h}]+ba/b[height<={h}]",
                    "--merge-output-format", "mp4"]
        if FFMPEG:
            cmd += ["--ffmpeg-location", os.path.dirname(FFMPEG)]

        self.after(0, lambda: self._on_start(row, outdir))
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW)
        except Exception as ex:
            self.after(0, lambda: row.set_state("failed", f"Error: {str(ex)[:60]}",
                                                COLORS["accent"], pct=row.pct))
            self.current = None
            return
        row.proc = proc
        if self.stop_all:              # Stop was pressed while this was spawning
            self._terminate_tree(proc)
        err_line = None
        for line in proc.stdout:
            if self.stop_all and proc.poll() is None:
                self._terminate_tree(proc)
            if "ERROR:" in line or line.startswith("ERROR"):
                err_line = line.strip()
            p = parse_progress(line)
            if p:
                pct, speed, eta = p
                txt = f"{pct:.0f}%" + (f" • {eta}" if eta else "")
                self.after(0, lambda r=row, t=txt, s=speed, p_=pct: r.set_state(
                    "downloading", t, COLORS["text"], pct=p_, speed=s))
            elif "[Merger]" in line or "[ExtractAudio]" in line:
                self.after(0, lambda r=row: r.set_state(
                    "downloading", "Processing…", COLORS["text"]))
        code = proc.wait()
        row.proc = None
        if self.current is row:
            self.current = None
        if self.stop_all or row.state in ("paused", "removed", "pending"):
            # Stopped, paused, or deleted while running — don't mark as failed
            self.after(0, self._update_overall)
            return
        if code == 0:
            self.after(0, lambda: (row.set_state("done", "✓ Done", COLORS["green"], pct=100),
                                   self._update_overall()))
        elif row.state == "paused":
            pass
        else:
            self.after(0, lambda: (row.set_state("failed", "Failed — retry?", COLORS["accent"]),
                                   self._download_failed(row, err_line)))
        self.after(0, self._update_overall)

    def _download_failed(self, row, err_line):
        title, hint = friendly_error(err_line or "")
        if title:
            self.set_status(f"{row.data['title'][:40]}: {title} → {hint}", COLORS["amber"])
        else:
            self.set_status(f"Download failed: {row.data['title'][:60]} "
                            f"— {re.sub(r'\\[.*?\\]\\s*', '', err_line or '')[:90]}",
                            COLORS["accent"])

    def _on_start(self, row, outdir):
        row.set_state("downloading", "0%", COLORS["text"], pct=0)
        self.stop_btn.configure(state="normal")
        self.set_status(f"Downloading: {row.data['title'][:60]}…  →  {outdir}")

    def _update_overall(self):
        total = len(self.rows)
        if not total:
            self.global_prog.set(0)
            self.stop_btn.configure(state="disabled")
            return
        done = sum(1 for r in self.rows if r.state == "done")
        active_pct = sum(r.pct for r in self.rows if r.state == "downloading") / 100.0
        self.global_prog.set((done + active_pct) / total)
        active = sum(1 for r in self.rows if r.state in ("downloading", "queued"))
        if active:
            self.set_status(f"Downloading…  {done}/{total} complete "
                            f"({int((done + active_pct) / total * 100)}%)")
        else:
            failed = sum(1 for r in self.rows if r.state == "failed")
            if done == total:
                self.set_status(f"All done — {total} video{'s' if total != 1 else ''} downloaded.",
                                COLORS["green"])
                self.stop_btn.configure(state="disabled")
            elif failed:
                self.set_status(f"Finished with {failed} failure(s) — use ⟳ to retry.",
                                COLORS["amber"])
                self.stop_btn.configure(state="disabled")

    # ---------------------------------------------------------- persistence --
    @property
    def _cfg_path(self):
        return os.path.join(os.path.expanduser("~"), ".ytpld_config.json")

    def save_layout(self):
        try:
            cfg = {"outdir": self.outdir.get(), "quality": self.global_quality.get(),
                   "subfolder": self.subfolder_var.get(),
                   "cookies": self.cookies_browser.get(),
                   "cookies_file": self.cookies_file.get(),
                   "per_video": {r.data["id"]: r.quality_var.get() for r in self.rows}}
            with open(self._cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except Exception:
            pass

    def load_layout(self):
        try:
            with open(self._cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            self.outdir.set(cfg.get("outdir", self.outdir.get()))
            self.dir_lbl.configure(text=self.outdir.get())
            self.global_quality.set(cfg.get("quality", "1080p"))
            self.subfolder_var.set(cfg.get("subfolder", True))
            self.cookies_browser.set(cfg.get("cookies", "None"))
            cf = cfg.get("cookies_file", "")
            if cf and os.path.isfile(cf):
                self.cookies_file.set(cf)
                self.cookies_file_lbl.configure(text=os.path.basename(cf))
            self._on_quality_change()
        except Exception:
            pass

    def load_saved_qualities(self):
        try:
            with open(self._cfg_path, encoding="utf-8") as f:
                return json.load(f).get("per_video", {})
        except Exception:
            return {}


if __name__ == "__main__":
    App().mainloop()
