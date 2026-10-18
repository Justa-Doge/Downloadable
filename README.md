# Personal Video & Audio Downloader

A Chrome extension for saving media from sites supported by yt-dlp as MP3 or MP4 to a folder you choose, or a TikTok `/photo/` post as PNG. It uses a small local helper because Chrome extensions cannot directly combine media streams or write to arbitrary folders.

Version 1.5.2 is split into platform archives. Windows and macOS are on 1.5.2, and the macOS build is tested on an Apple-silicon VM. The combined Linux/ChromeOS archive is experimental and untested.

Use this only with videos you own, public-domain material, or videos whose owner has authorized downloads. The platforms' official offline features are the appropriate option for other videos.

## Install on macOS

1. Double-click `launchers/macos/setup.command`. This is the only Mac launcher: it installs and starts the background helper. If macOS blocks it, Control-click it, choose **Open**, then confirm.
2. In Chrome, open `chrome://extensions`.
3. Turn on **Developer mode** in the upper-right corner.
4. Click **Load unpacked** and select the `extension` folder inside this project.
5. The setup installs the helper and its virtual environment under `~/Library/Application Support/Downloadable`, so it works even when the project is inside the protected Downloads folder. No Terminal window needs to stay open.
6. Open a supported media page, or paste its link into the popup. Choose a folder, then click **MP3** or **MP4**. TikTok `/music/` sound-page links are accepted for MP3 and limited to the first available sound result.

For CapCut, choose the folder where you keep edit audio, download as **MP3**, then import that file into CapCut Desktop. MP4 saves the complete video and audio together.

YouTube and YouTube Music MP3 downloads include the source thumbnail as cover art and embed available music metadata such as title, artist, album, date, and duration. Dedicated or officially identified music uploads usually provide the richest tags; the helper does not invent missing artist or album information.

## Install on Windows

1. Double-click `Downloadable.cmd`. This is the one-file Windows installer. It asks you to confirm you have read this README, offers to install missing Python 3.11 and FFmpeg through winget, creates the local environment, and asks whether to keep the helper running after setup. If you run it again to repair the install, it stops Downloadable's own helper first so Python files are not locked. It does not change Windows' saved execution policy.
2. In Chrome, open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked**, and select this project's `extension` folder. The extension asks you to confirm that you have read this README the first time it opens.
3. No PowerShell or command prompt needs to stay open. Windows repair and diagnostic launchers are in `launchers/windows/`; the normal entry point is still `Downloadable.cmd`.

The MP3 and MP4 folders are remembered separately in both the local helper and Chrome's extension storage. Only one download runs at a time.

Open the gear button in the extension popup for local helper status, a manual reconnect check, clearing saved destination folders, opening the temporary error-log folder, and a shortcut back to Chrome's extension details page. Downloads can be canceled while they are running. Reconnect only checks the existing local helper; it does not reauthorize an account or send data anywhere.

Helper errors are written to the per-user temporary folder (`%TEMP%\Downloadable\logs` on Windows). Use **Settings → Open error logs** instead of hunting for that folder manually.

The helper checks the Downloadable GitHub release once per hour. You can also use Settings → Check for updates in the extension. When a newer build is found, it validates and downloads it locally, then shows an update-ready message. Use Restart and apply update to restart the scheduled helper and apply the staged update. If setup or dependencies need fixing, Settings → Repair setup opens the one-file setup launcher again.

TikTok `/photo/` posts show a PNG/s button. Photo carousels are saved as numbered PNG files when TikTok exposes the carousel image list; posts that only expose a thumbnail still save that image as one PNG.

## Install on Linux

1. Install Python 3, FFmpeg, and a Chromium-based browser using your distribution's package manager.
2. Run `./launchers/linux/setup.sh` from this folder. It creates the local environment, token, extension configuration, and user service when systemd user services are available.
3. In Chrome, open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked** for this project's `extension` folder.
4. If your desktop does not provide a user service manager, setup starts the helper for the current session; use `./launchers/linux/start.sh` after reboot.

## Install on ChromeOS

1. Enable the Linux development environment and share the ChromeOS **Downloads** folder with it.
2. Place this project in the Linux container and run `./launchers/linux/setup.sh` in the Terminal.
3. Load the `extension` folder in Chrome using **Developer mode → Load unpacked**.
4. The extension uses `penguin.linux.test` to reach the helper in the Linux container. MP3 and MP4 defaults point to the shared ChromeOS Downloads folder when it is available.

## Requirements

- Windows 10/11, macOS, Linux, or ChromeOS with the Linux development environment
- Google Chrome or another Chromium browser
- Internet access during initial setup
- `ffmpeg` and Python 3 available on the command line; macOS setup can offer to install missing copies through Homebrew, and installs the Python-side TikTok impersonation dependency automatically

## Build a release ZIP

Run `python3 tools/build_release.py --platform macos`, `--platform windows`, or `--platform linux-chromeos` from the project folder to build a platform-specific archive. The default archive names are stable (`personal-media-downloader-macos.zip`, `personal-media-downloader-windows.zip`, and `personal-media-downloader-linux-chromeos.zip`) so extracting an update reuses the same folder instead of creating a new version-numbered folder. The manifest and GitHub release tag carry the actual version. The builder excludes tokens, saved folders, virtual environments, generated extension configuration, caches, and temporary files. It preserves executable permissions for macOS `.command` and Linux `.sh` launchers. The Linux/ChromeOS archive is experimental.

## Troubleshooting

- **Local helper is not running:** on macOS, rerun `launchers/macos/setup.command`. On Windows, run `Downloadable.cmd` again to repair the background task, or use the popup's **Settings → Repair setup** / **Reconnect** buttons. Linux users can run `launchers/linux/start.sh` for visible troubleshooting output.
- **Authentication failed:** rerun the setup launcher for your platform, then click Reload on the extension's card at `chrome://extensions`.
- **Video requires sign-in:** this first version intentionally does not read browser cookies. Use YouTube's official download feature for restricted videos.
- **A site is not recognized:** Downloadable passes normal HTTPS links to yt-dlp, which supports a large and changing list of sites. Rerun the setup launcher for your platform to update `yt-dlp`, then try the direct media page URL. A site can still fail when that specific page or media type is unsupported or requires sign-in.
- **Download failed after a site or Chrome update:** copy the final error shown in the extension or Terminal window when asking for help.

## Privacy and security

The helper listens only on `127.0.0.1`, accepts requests only from Chrome-extension pages, and requires a random local token generated during setup. URLs and folder choices stay on this computer except for the normal requests made to the selected media site by `yt-dlp`.
