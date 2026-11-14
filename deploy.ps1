# One-shot deployment to GitHub Releases (run when the user says GO)
# Usage:  powershell -File deploy.ps1  (from the project folder)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$repo = "Ish474/YouTubePlaylistDownloader"
$exe  = "dist\YouTubePlaylistDownloader.exe"
$zip  = "dist\YouTubePlaylistDownloader-1.0.1-win64.zip"

# 1. git repo + initial commit (if not already)
if (-not (Test-Path .git)) {
    git init
    git add .
    git commit -m "YouTube Playlist Downloader v1.0.0 - initial release"
}

# 2. create public repo and push source
gh repo create $repo --public --source . --remote origin --push --description "Download entire YouTube playlists on Windows with quality selection, pause/resume, and MP3 extraction."

# 3. create the release with both artifacts
gh release create v1.0.1 $exe $zip `
  --title "v1.0.1 - Cookie fixes + UI polish" `
  --notes "## Downloads
- **YouTubePlaylistDownloader.exe** - portable, single file, nothing to install
- **YouTubePlaylistDownloader-1.0.0-win64.zip** - same thing, zipped (recommended if your antivirus complains)

## Features
- Download entire YouTube playlists
- Quality selection: 2160p / 1440p / 1080p / 720p / 480p / 360p / MP3 (320/192/128 kbps)
- Per-video quality overrides
- Pause / resume / retry for every download
- Modern dark UI with thumbnails and live progress
- ffmpeg and yt-dlp bundled - no extra installs needed

> **Note:** Windows SmartScreen may warn on first run (the exe is not code-signed). Click *More info -> Run anyway*. This app is for personal use - please respect content creators' rights and YouTube's Terms of Service."

Write-Host ""
Write-Host "Published:"
Write-Host "  Repo:    https://github.com/$repo"
Write-Host "  Release: https://github.com/$repo/releases/latest"
