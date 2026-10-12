# Changelog

## 1.5.0 - 2026-10-12

- Windows-focused release: organized launchers, fixed setup permission failures, added first-run README acknowledgement in the extension, staged-update restart, repair setup, and TikTok carousel PNG handling.
- Windows setup/helper behavior tested. macOS, Linux, and ChromeOS are not tested for this release.

## 2026-10-12

- Added staged-update restart, a Settings repair-setup action, and TikTok photo-carousel PNG extraction with numbered outputs. Verified with 12 Python tests, JavaScript syntax checking, a live helper restart, and a live update check. Not pushed.
- Fixed setup reruns failing with permission denied on `.venv\Scripts\python.exe` by stopping Downloadable's own helper before rebuilding the environment. Full setup and authenticated helper state were verified. Chrome intentionally cannot launch arbitrary local executables directly from an extension.
- Fixed setup's Chrome handoff: it now uses the Windows `chrome://extensions/` protocol handler so an already-open Chrome session navigates to the Extensions page instead of opening a blank New Tab.
- Removed automatic Chrome navigation from setup and moved the README acknowledgement into the extension's first-run popup screen.
- Organized platform launchers under `launchers/windows`, `launchers/macos`, and `launchers/linux`; kept root `Downloadable.cmd` as the normal Windows entry point and updated release packaging.
