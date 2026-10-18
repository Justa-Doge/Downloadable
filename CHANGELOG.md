# Changelog

## Unreleased

- Broadened media-link validation so HTTPS links from yt-dlp-supported sites can be tried, while preserving TikTok photo/sound handling and adding clearer unsupported-site errors.
- Added separate Windows, macOS, and combined Linux/ChromeOS experimental release packaging so each platform can be tested independently.
- Updated the automatic updater to prefer the current platform's archive and only fall back to the legacy generic archive, preventing a Mac helper from staging a Windows build (or vice versa).
- YouTube and TikTok titles are cleaned from the active tab and sent as a fallback filename; yt-dlp's own title-plus-ID filename remains authoritative whenever metadata is available.

## 1.5.1 - 2026-10-18

- Windows remains on the 1.5.1 patch release; its setup/helper behavior is unchanged.
- macOS 1.5.1 is now tested on an Apple-silicon VM, including Homebrew Python/FFmpeg setup, background helper startup, Chrome extension authentication, and a real MP4 download.
- Linux and ChromeOS remain experimental and untested.
- Fixed the local helper's job-status response failing when it tried to serialize its internal download process object. Download progress can now be read normally by the extension.

## 1.5.0 - 2026-10-12

- Windows-focused release: organized launchers, fixed setup permission failures, added first-run README acknowledgement in the extension, staged-update restart, repair setup, and TikTok carousel PNG handling.
- Windows setup/helper behavior tested. macOS, Linux, and ChromeOS are not tested for this release.

## 2026-10-12

- Added staged-update restart, a Settings repair-setup action, and TikTok photo-carousel PNG extraction with numbered outputs. Verified with 12 Python tests, JavaScript syntax checking, a live helper restart, and a live update check. Not pushed.
- Fixed setup reruns failing with permission denied on `.venv\Scripts\python.exe` by stopping Downloadable's own helper before rebuilding the environment. Full setup and authenticated helper state were verified. Chrome intentionally cannot launch arbitrary local executables directly from an extension.
- Fixed setup's Chrome handoff: it now uses the Windows `chrome://extensions/` protocol handler so an already-open Chrome session navigates to the Extensions page instead of opening a blank New Tab.
- Removed automatic Chrome navigation from setup and moved the README acknowledgement into the extension's first-run popup screen.
- Organized platform launchers under `launchers/windows`, `launchers/macos`, and `launchers/linux`; kept root `Downloadable.cmd` as the normal Windows entry point and updated release packaging.
- Replaced the Windows Python `ctypes` folder dialog with the modern Explorer-style Windows folder picker, including foreground ownership so it opens above Chrome.
### macOS 1.5.1 validation details

- Fixed the macOS launch agent to use a per-user Application Support runtime copy, avoiding macOS privacy restrictions when the project is stored in Downloads.
- Made macOS `start.command` background-safe: it now kickstarts the LaunchAgent instead of attaching the helper to the Terminal, and runs setup automatically when needed.
- Simplified the Mac release to one launcher: `setup.command` installs and starts the background helper; `start.command` is no longer packaged.
- Fixed the macOS runtime copy to include the extension manifest required by the helper's state endpoint.
- Moved the macOS virtual environment itself into Application Support so setup does not try to write `.venv` inside protected Downloads.
- Fixed the final macOS setup token-generation path that still referenced the old Downloads virtual environment.
- Made downloads invoke yt-dlp through the active Python environment and fixed error logging on macOS Python 3.9.
