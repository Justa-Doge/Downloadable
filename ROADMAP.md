# Downloadable Roadmap

## Native helper startup and cross-platform installation

Replace the current manually installed local HTTP helper workflow with a registered Chrome Native Messaging host.

### Goals

- Bundle the helper as a platform-appropriate executable so users do not need Python, a virtual environment, or terminal commands after installation.
- Have the extension connect to the native host and let Chrome start the helper automatically when it is missing from memory.
- Keep first-time setup to one user-approved installer action; Chrome extensions cannot silently install native software or register a host.
- Preserve existing settings, downloads, staged updates, and safe shutdown behavior during upgrades.

### Platform work

- **Windows:** package the helper, register a per-user native-host manifest through the installer, and support clean upgrade/rollback behavior.
- **macOS:** package the helper, install the user-level native-host manifest in the supported Chrome location, and account for signing/notarization and launch permissions.
- **Linux:** support the user-level native-host manifest locations used by Chrome/Chromium and package installers for common distributions where practical.
- **ChromeOS/Linux container:** confirm whether the native host can be exposed to the ChromeOS browser; if not, retain the current `penguin.linux.test` fallback with a clearly documented setup path.

### Security and compatibility requirements

- Declare the `nativeMessaging` permission and restrict the host manifest to the exact extension origin; never use wildcard origins.
- Validate the caller origin and sanitize every message in the helper.
- Keep download destinations and user settings intact across upgrades.
- Verify update archives before applying them and make failed upgrades recoverable.
- Provide an extension status screen that distinguishes “host not installed,” “host unavailable,” and “helper error,” with a single repair path.

### Acceptance criteria

1. A fresh install requires one explicit helper-install approval and no manual command.
2. Opening the extension afterward starts the helper automatically through Native Messaging.
3. Reinstalling or upgrading stops/replaces only Downloadable's helper and does not interrupt unrelated processes.
4. Windows and macOS are validated first; Linux and ChromeOS behavior is then confirmed or documented with a supported fallback.
5. The README and release packaging describe the same workflow for every supported platform.
