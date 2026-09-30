# Personal Video & Audio Downloader

A Chrome extension for saving a YouTube or TikTok video as MP3 or MP4 to a folder you choose. It uses a small local helper because Chrome extensions cannot directly combine media streams or write to arbitrary folders.

Use this only with videos you own, public-domain material, or videos whose owner has authorized downloads. The platforms' official offline features are the appropriate option for other videos.

## Install on macOS

1. Double-click `setup.command`. If macOS blocks it, Control-click it, choose **Open**, then confirm.
2. In Chrome, open `chrome://extensions`.
3. Turn on **Developer mode** in the upper-right corner.
4. Click **Load unpacked** and select the `extension` folder inside this project.
5. The setup installs the helper as a macOS background service, so no Terminal window needs to stay open.
6. Open a YouTube or TikTok video, or paste its link into the popup. Choose a folder, then click **MP3** or **MP4**. TikTok `/music/` sound-page links are accepted for MP3 and limited to the first available sound result.

For CapCut, choose the folder where you keep edit audio, download as **MP3**, then import that file into CapCut Desktop. MP4 saves the complete video and audio together.

YouTube and YouTube Music MP3 downloads include the source thumbnail as cover art and embed available music metadata such as title, artist, album, date, and duration. Dedicated or officially identified music uploads usually provide the richest tags; the helper does not invent missing artist or album information.

## Install on Windows

1. Install Python 3.11+ and FFmpeg (`winget install Python.Python.3.11` and `winget install Gyan.FFmpeg`).
2. Double-click `setup.cmd`. It removes the downloaded-file marker only from this project's local PowerShell scripts, then runs them under a process-only `RemoteSigned` policy to create the Python environment and configuration. It does not change Windows' saved execution policy.
3. Setup registers and starts the helper as a hidden per-user Windows task, so no PowerShell window needs to stay open. Use `start.cmd` only for visible troubleshooting output.
4. In Chrome, open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked**. Select this project's `extension` folder.

The MP3 and MP4 folders are remembered separately in both the local helper and Chrome's extension storage. Only one download runs at a time.

The helper checks the Downloadable GitHub release once per hour. When a newer build is found, it downloads it locally and shows an update-ready message in the extension. Restart the helper to apply the staged update.

## Requirements

- macOS or Windows 10/11
- Google Chrome or another Chromium browser
- Internet access during initial setup
- `ffmpeg` available on the command line (already present on the Mac this was built for)

## Build a release ZIP

Run `python3 tools/build_release.py` from the project folder. The builder excludes tokens, saved folders, virtual environments, generated extension configuration, caches, and temporary files. It also preserves executable permissions for the macOS `.command` launchers while including the Windows `.cmd` launchers.

## Troubleshooting

- **Local helper is not running:** on macOS, double-click `start.command`; on Windows, run `start.ps1`. Keep the terminal window open.
- **Authentication failed:** run `setup.command` again, then click Reload on the extension's card at `chrome://extensions`.
- **Video requires sign-in:** this first version intentionally does not read browser cookies. Use YouTube's official download feature for restricted videos.
- **YouTube or TikTok changed something:** run `setup.command` again to update `yt-dlp`, then reload the extension.
- **Download failed after a site or Chrome update:** copy the final error shown in the extension or Terminal window when asking for help.

## Privacy and security

The helper listens only on `127.0.0.1`, accepts requests only from Chrome-extension pages, and requires a random local token generated during setup. URLs and folder choices stay on this computer except for the normal requests made to the selected media site by `yt-dlp`.
