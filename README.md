# YouTube Playlist Downloader

A Windows desktop app to download entire YouTube playlists with selectable
video quality, per-video overrides, pause/resume/retry, and MP3 extraction.

## The exe
- **File:** `dist\YouTubePlaylistDownloader.exe` (portable, single file — no Python needed)
- **Desktop shortcut:** created at install time

## How to use
1. Paste a **playlist URL** (or a single video URL) and click **Fetch Playlist**.
2. Uncheck any videos you want to skip; use **Select all / Clear** as needed.
3. Pick a **quality**: 2160p / 1440p / 1080p / 720p / 480p / 360p / Audio (MP3).
   - Each row has its own dropdown — set it to anything other than **Global** to
     override the global setting for that video.
   - For **Audio (MP3)**, choose a bitrate (320 / 192 / 128 kbps).
4. Choose the **output folder** (default: `Downloads`). Optionally save into a
   subfolder named after the playlist.
5. Click **⬇ Download All**. Watch per-video progress bars, speed and ETA.
6. Per-row controls: **⏸ pause** (resumes from the same byte), **▶ resume**, **⟳ retry**.
   **■ Stop** halts everything.

## Troubleshooting
- **"Chrome cookie error / Failed to decrypt with DPAPI"** — Chrome v127+ encrypts
  its cookies (App-Bound Encryption), so yt-dlp can't read them anymore. Use
  **Edge** or **Firefox** in the *Browser cookies* dropdown instead, or export a
  `cookies.txt` file from Chrome with the extension *Get cookies.txt LOCALLY*
  and load it via **+ cookies.txt…** in the app.
- **"Sign in to confirm you're not a bot"** — select your browser in the
  **Browser cookies** dropdown (Edge / Chrome / Firefox / Brave) or load a
  `cookies.txt` file so yt-dlp can reuse your logged-in YouTube session. Close
  the browser first if the cookies can't be read.
- Quality above 1080p or MP3 conversion requires ffmpeg — it is **bundled
  inside the exe**, nothing to install.

## For developers
```
.venv\Scripts\python make_logo.py     # regenerate logo.png + icon.ico
.venv\Scripts\python smoke_test.py    # headless GUI smoke test
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed ^
  --name YouTubePlaylistDownloader --icon assets\icon.ico ^
  --collect-all customtkinter ^
  --add-binary "bin\yt-dlp.exe;bin" ^
  --add-binary "ffmpeg\ffmpeg.exe;ffmpeg" ^
  --add-binary "ffmpeg\ffprobe.exe;ffmpeg" ^
  --add-data "assets\logo.png;assets" app.py
```
When YouTube breaks things, refresh the engine:
`Invoke-WebRequest https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe -OutFile bin\yt-dlp.exe`
then rebuild.
