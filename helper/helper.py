#!/usr/bin/env python3
"""Local HTTP helper for the Personal Video & Audio Downloader extension."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import tempfile
import time
import traceback
import uuid
import urllib.error
import urllib.request
import zipfile
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:  # Windows Python installs may omit Tk.
    tk = None
    filedialog = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import urllib.parse


HOST = os.environ.get("DOWNLOADABLE_HOST", "127.0.0.1")
PORT = 47821
UPDATE_INTERVAL = 3600
RELEASE_API = "https://api.github.com/repos/Justa-Doge/Downloadable/releases/latest"
ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(tempfile.gettempdir()) / "Downloadable" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "downloadable.log"
TOKEN_FILE = ROOT / ".helper-token"
STATE_FILE = ROOT / ".state.json"
CHROMEOS_DOWNLOADS = Path("/mnt/chromeos/MyFiles/Downloads")
DOWNLOAD_ROOT = CHROMEOS_DOWNLOADS if CHROMEOS_DOWNLOADS.is_dir() else Path.home() / "Downloads"
if os.name == "nt":
    DEFAULT_DESTINATION = Path.home() / "Music"
    DEFAULT_VIDEO_DESTINATION = Path.home() / "Videos"
else:
    DEFAULT_DESTINATION = DOWNLOAD_ROOT / "Music"
    DEFAULT_VIDEO_DESTINATION = CHROMEOS_DOWNLOADS if CHROMEOS_DOWNLOADS.is_dir() else Path.home() / "Movies"
TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip() if TOKEN_FILE.exists() else ""
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
UPDATE_LOCK = threading.Lock()
RESTART_LOCK = threading.Lock()


def log_error(context: str, error: BaseException) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as stream:
            stream.write(f"\n[{__import__('datetime').datetime.now().isoformat(timespec='seconds')}] {context}\n")
            stream.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
    except OSError:
        pass


def open_log_folder() -> None:
    # The helper can stay alive across temp-folder cleanup, so recreate the
    # directory immediately before opening it.  Explorer is more reliable
    # than os.startfile for opening a directory from a packaged helper.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", str(LOG_DIR)], close_fds=True)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(LOG_DIR)])
    else:
        subprocess.Popen(["xdg-open", str(LOG_DIR)])


def add_windows_tool_path() -> None:
    if os.name != "nt":
        return
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
    if links.is_dir() and str(links) not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = str(links) + os.pathsep + os.environ.get("PATH", "")


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3]) or (0,)


def runtime_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux-chromeos" if CHROMEOS_DOWNLOADS.is_dir() else "linux"


def select_release_asset(assets: list[dict]) -> dict | None:
    """Prefer an archive built for this OS, with legacy generic fallback."""
    archives = [item for item in assets if str(item.get("name", "")).endswith(".zip")]
    platform = runtime_platform()
    # Release archives intentionally use stable, human-readable filenames
    # such as Downloadable-MacOS.zip so extracting a new build does not create
    # a version-numbered install folder. Keep accepting the older names for
    # existing releases.
    label = {"windows": "Windows", "macos": "MacOS", "linux-chromeos": "Linux-ChromeOS", "linux": "Linux"}.get(platform, platform)
    marker = re.compile(
        rf"(?:downloadable-{re.escape(label)}|personal-media-downloader-{re.escape(platform)})(?:-|\.zip$)",
        re.IGNORECASE,
    )
    specific = [item for item in archives if marker.search(str(item.get("name", "")).lower())]
    if specific:
        return specific[0]
    return next(
        (item for item in archives if re.fullmatch(r"personal-media-downloader(?:-[0-9.]+)?\.zip", str(item.get("name", "")).lower())),
        None,
    )


def check_for_update() -> dict:
    """Check GitHub for a newer release and stage it for the next restart."""
    if not UPDATE_LOCK.acquire(blocking=False):
        return {"status": "checking"}
    try:
        current = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"]
        request = urllib.request.Request(RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Downloadable-Updater"})
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.loads(response.read().decode("utf-8"))
        latest = str(release.get("tag_name", "")).lstrip("v")
        if version_tuple(latest) <= version_tuple(current):
            return {"status": "current", "current": current, "latest": latest}
        asset = select_release_asset(release.get("assets", []))
        if not asset:
            return {"status": "unavailable", "current": current, "latest": latest}
        update_path = ROOT / ".downloadable-update.zip"
        metadata = {"version": latest, "release_url": release.get("html_url", ""), "asset": asset["name"], "current": current}
        available_path = ROOT / ".update-available.json"
        if available_path.exists() and update_path.exists():
            staged = json.loads(available_path.read_text(encoding="utf-8"))
            if str(staged.get("version", "")) == latest:
                return {"status": "staged", **staged}
        temporary_path = ROOT / ".downloadable-update.zip.part"
        try:
            urllib.request.urlretrieve(asset["browser_download_url"], temporary_path)
            with zipfile.ZipFile(temporary_path) as archive:
                if not archive.namelist():
                    raise ValueError("The update archive was empty.")
            temporary_path.replace(update_path)
            available_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        finally:
            temporary_path.unlink(missing_ok=True)
        print(f"Update {latest} downloaded. Restart the helper to apply it.")
        return {"status": "staged", **metadata}
    except urllib.error.HTTPError as error:
        if error.code == 404:  # Private repositories are intentionally invisible without credentials.
            return {"status": "unavailable"}
        print(f"Update check skipped: {error}")
        return {"status": "error", "error": str(error)}
    except Exception as error:
        print(f"Update check skipped: {error}")
        return {"status": "error", "error": str(error)}
    finally:
        UPDATE_LOCK.release()


def apply_staged_update() -> None:
    update_path = ROOT / ".downloadable-update.zip"
    if not update_path.exists():
        return
    try:
        with zipfile.ZipFile(update_path) as archive:
            for member in archive.infolist():
                name = Path(member.filename)
                if not name.parts or name.parts[0] in {".git", ".venv"} or name.name in {".helper-token", ".state.json", "config.js", ".downloadable-update.zip", ".downloadable-update.zip.part", ".update-available.json"}:
                    continue
                target = (ROOT / name).resolve()
                if ROOT not in target.parents:
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        update_path.unlink()
        (ROOT / ".update-available.json").unlink(missing_ok=True)
        print("Staged Downloadable update applied.")
    except Exception as error:
        print(f"Could not apply staged update: {error}")


def update_loop() -> None:
    while True:
        check_for_update()
        threading.Event().wait(UPDATE_INTERVAL)


def schedule_helper_restart() -> None:
    """Restart the scheduled helper so a staged update can be applied."""
    if not RESTART_LOCK.acquire(blocking=False):
        return
    try:
        if os.name == "nt":
            command = (
                "Start-Sleep -Milliseconds 650; "
                "schtasks /End /TN 'Downloadable Helper' 2>$null; "
                "Start-Sleep -Milliseconds 700; "
                "schtasks /Run /TN 'Downloadable Helper' 2>$null"
            )
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
                creationflags=flags,
                close_fds=True,
            )
        elif sys.platform == "darwin":
            # launchd keeps the helper alive and restarts it after this process exits.
            subprocess.Popen(
                ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.downloadable.helper"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        else:
            raise RuntimeError("Automatic helper restart is not configured for this platform.")
        threading.Timer(0.35, os._exit, args=(0,)).start()
    finally:
        RESTART_LOCK.release()


def open_setup() -> None:
    """Open the platform setup launcher so a user can repair dependencies."""
    if os.name == "nt":
        subprocess.Popen(["cmd.exe", "/c", "start", "", str(ROOT / "Downloadable.cmd")], cwd=ROOT)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ROOT / "launchers" / "macos" / "setup.command")])
    else:
        subprocess.Popen(["xdg-open", str(ROOT / "launchers" / "linux" / "setup.sh")])


def load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    legacy_destination = state.pop("destination", "")
    if not state.get("mp3_destination"):
        if legacy_destination:
            state["mp3_destination"] = legacy_destination
        elif DEFAULT_DESTINATION.is_dir():
            state["mp3_destination"] = str(DEFAULT_DESTINATION)
    if not state.get("mp4_destination") and DEFAULT_VIDEO_DESTINATION.is_dir():
        state["mp4_destination"] = str(DEFAULT_VIDEO_DESTINATION)
    return state


def save_state(state: dict) -> None:
    pending = STATE_FILE.with_suffix(".tmp")
    pending.write_text(json.dumps(state, indent=2), encoding="utf-8")
    pending.replace(STATE_FILE)


def remember_destination(output_format: str, destination: str) -> None:
    with STATE_LOCK:
        state = load_state()
        state[f"{output_format}_destination"] = destination
        save_state(state)


def choose_folder(output_format: str) -> str:
    description = {"mp3": "MP3 audio", "mp4": "MP4 video", "png": "PNG photos"}[output_format]
    if os.name == "nt":
        picker_script = (
            "$source = @'\n"
            "using System;\n"
            "using System.Runtime.InteropServices;\n"
            "namespace DownloadablePicker {\n"
            "  [ComImport, Guid(\"42f85136-db7e-439c-85f1-e4075d135fc8\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
            "  public interface IFileDialog {\n"
            "    [PreserveSig] int Show(IntPtr parent);\n"
            "    void SetFileTypes(uint count, IntPtr specs); void SetFileTypeIndex(uint index); uint GetFileTypeIndex();\n"
            "    void Advise(IntPtr sink, out uint cookie); void Unadvise(uint cookie); void SetOptions(uint options); void GetOptions(out uint options);\n"
            "    void SetDefaultFolder(IShellItem item); void SetFolder(IShellItem item); void GetFolder(out IShellItem item); void GetCurrentSelection(out IShellItem item);\n"
            "    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name); void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);\n"
            "    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title); void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);\n"
            "    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string text); void GetResult(out IShellItem item);\n"
            "    void AddPlace(IShellItem item, int alignment); void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);\n"
            "    void Close(int hr); void SetClientGuid(ref Guid guid); void ClearClientData(); void SetFilter(IntPtr filter);\n"
            "  }\n"
            "  [ComImport, Guid(\"D57C7288-D4AD-4768-BE02-9D969532D960\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
            "  public interface IFileOpenDialog : IFileDialog { void GetResults(out IntPtr results); void GetSelectedItems(out IntPtr items); }\n"
            "  [ComImport, Guid(\"43826D1E-E718-42EE-BC55-A1E261C37BFE\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
            "  public interface IShellItem { void BindToHandler(IntPtr p, ref Guid bhid, ref Guid riid, out IntPtr ppv); void GetParent(out IShellItem item); void GetDisplayName(uint sigdn, out IntPtr name); void GetAttributes(uint mask, out uint attrs); void Compare(IShellItem item, uint hint, out int order); }\n"
            "  public static class NativePicker {\n"
            "    [DllImport(\"user32.dll\")] private static extern IntPtr GetForegroundWindow();\n"
            "    public static string Show(string title) {\n"
            "      var type = Type.GetTypeFromCLSID(new Guid(\"DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7\"));\n"
            "      var dialog = (IFileOpenDialog)Activator.CreateInstance(type);\n"
            "      dialog.SetOptions(0x40u | 0x20u); dialog.SetTitle(title);\n"
            "      int hr = dialog.Show(GetForegroundWindow()); if (hr != 0) return string.Empty;\n"
            "      IShellItem item; dialog.GetResult(out item); IntPtr ptr; item.GetDisplayName(0x80058000u, out ptr);\n"
            "      try { return Marshal.PtrToStringUni(ptr); } finally { Marshal.FreeCoTaskMem(ptr); }\n"
            "    }\n"
            "  }\n"
            "}\n"
            "'@; "
            "Add-Type -TypeDefinition $source; "
            "[Console]::Out.Write([DownloadablePicker.NativePicker]::Show($env:DOWNLOADABLE_PICKER_TITLE))"
        )
        environment = os.environ.copy()
        environment["DOWNLOADABLE_PICKER_TITLE"] = f"Choose where {description} should be saved"
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", picker_script],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            startupinfo=startupinfo,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Could not open the Windows folder picker.")
        selected = result.stdout.strip()
        if not selected:
            raise ValueError("Folder selection canceled.")
        return str(Path(selected).resolve())
    if sys.platform.startswith("linux"):
        if tk is not None and filedialog is not None and os.environ.get("DISPLAY"):
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(title=f"Choose where {description} should be saved")
            root.destroy()
            if not selected:
                raise ValueError("Folder selection canceled.")
            return str(Path(selected).resolve())
        fallback = DEFAULT_DESTINATION if output_format == "mp3" else DEFAULT_VIDEO_DESTINATION
        fallback.mkdir(parents=True, exist_ok=True)
        return str(fallback.resolve())

    script = f"""
        tell application "Finder"
            activate
            set selectedFolder to choose folder with prompt "Choose where {description} should be saved"
            return POSIX path of selectedFolder
        end tell
    """
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        if "User canceled" in result.stderr:
            raise ValueError("Folder selection canceled.")
        raise RuntimeError(result.stderr.strip() or "Could not open the folder picker.")
    return str(Path(result.stdout.strip()).resolve())


def valid_media_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    youtube_host = host == "youtube.com" or host.endswith(".youtube.com")
    youtube_media = youtube_host and (
        parsed.path == "/watch"
        or parsed.path.startswith(("/shorts/", "/live/", "/embed/"))
    )
    youtube_short_link = host == "youtu.be" and len(parsed.path) > 1
    tiktok_host = host == "tiktok.com" or host.endswith(".tiktok.com")
    tiktok_media = tiktok_host and (
        "/video/" in parsed.path
        or "/photo/" in parsed.path
        or "/music/" in parsed.path
        or (host in {"vm.tiktok.com", "vt.tiktok.com"} and len(parsed.path) > 1)
        or (host in {"tiktok.com", "www.tiktok.com"} and parsed.path.startswith(("/t/", "/v/")) and len(parsed.path) > 3)
    )
    # yt-dlp supports many more sites than the two with special UI behavior
    # above. Let it validate other normal HTTPS media links at download time.
    return parsed.scheme == "https" and bool(host) and host not in {"localhost", "127.0.0.1", "::1"}


def resolve_tiktok_short_url(value: str) -> str:
    """Follow TikTok share redirects so yt-dlp receives the canonical video URL."""
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        is_short = host in {"vm.tiktok.com", "vt.tiktok.com"} or (
            host in {"tiktok.com", "www.tiktok.com"} and parsed.path.startswith(("/t/", "/v/"))
        )
        if not is_short:
            return value
        request = urllib.request.Request(value, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            resolved = response.geturl()
        return resolved if valid_media_url(resolved) else value
    except Exception:
        return value


def is_tiktok_sound_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return (host == "tiktok.com" or host.endswith(".tiktok.com")) and "/music/" in parsed.path


def is_tiktok_photo_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return (host == "tiktok.com" or host.endswith(".tiktok.com")) and "/photo/" in parsed.path


def is_tiktok_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower()
    return host == "tiktok.com" or host.endswith(".tiktok.com")


def is_youtube_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def update_job(job_id: str, **changes: object) -> None:
    with LOCK:
        if job_id in JOBS and not JOBS[job_id].get("cancel_requested"):
            changes.setdefault("updated_at", __import__("time").monotonic())
            JOBS[job_id].update(changes)


class DownloadCanceled(Exception):
    pass


def check_canceled(job_id: str) -> None:
    with LOCK:
        if JOBS[job_id].get("cancel_requested"):
            raise DownloadCanceled


def start_download_process(job_id: str, command: list[str], **options) -> subprocess.Popen:
    with LOCK:
        job = JOBS[job_id]
        if job.get("cancel_requested"):
            raise DownloadCanceled
        platform_options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt" else {"start_new_session": True}
        )
        process = subprocess.Popen(command, **platform_options, **options)
        job["process"] = process
        return process


def stop_download_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False,
        )
        if result.returncode and process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def start_job_heartbeat(job_id: str, process: subprocess.Popen[str]) -> None:
    """Show that extraction is alive when yt-dlp emits no output for a while."""
    def heartbeat() -> None:
        import time
        while process.poll() is None:
            time.sleep(3)
            with LOCK:
                job = JOBS.get(job_id)
                if not job or job.get("status") in {"complete", "error"}:
                    return
                quiet_for = time.monotonic() - float(job.get("updated_at", time.monotonic()))
            if quiet_for >= 5:
                update_job(job_id, message="Still working…")
    threading.Thread(target=heartbeat, name=f"download-heartbeat-{job_id}", daemon=True).start()


def _image_urls(value: object) -> list[str]:
    """Collect direct image URLs from TikTok's varied embedded post shapes."""
    found: list[str] = []

    def add(candidate: object) -> None:
        if not isinstance(candidate, str):
            return
        candidate = candidate.replace("\\u002F", "/").replace("\\/", "/")
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        if not candidate.startswith(("http://", "https://")):
            return
        lower = candidate.lower().split("?", 1)[0]
        if any(ext in lower for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif")) and candidate not in found:
            found.append(candidate)

    def walk(node: object, image_context: bool = False) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                key_lower = str(key).lower()
                child_context = image_context or any(
                    word in key_lower for word in (
                        "imagepost", "image_url", "imageurl", "display_image", "url_list",
                        "image_list", "image_urls", "photo_images", "photo_list",
                    )
                )
                if isinstance(child, list) and child_context:
                    for item in child:
                        add(item)
                elif isinstance(child, str) and child_context:
                    add(child)
                walk(child, child_context)
        elif isinstance(node, list):
            for child in node:
                if image_context:
                    add(child)
                walk(child, image_context)
        elif image_context:
            add(node)

    walk(value)
    return found


def extract_tiktok_photo_urls(html: str) -> list[str]:
    """Extract carousel image URLs from TikTok's embedded JSON state."""
    urls: list[str] = []
    scripts = re.findall(
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for script in scripts:
        try:
            payload = json.loads(script)
        except json.JSONDecodeError:
            continue
        for candidate in _image_urls(payload):
            if candidate not in urls:
                urls.append(candidate)
    return urls


def fetch_tiktok_photo_urls(url: str) -> tuple[list[str], dict]:
    """Fetch embedded photo data and oEmbed metadata for a TikTok photo post."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", "replace")
    urls = extract_tiktok_photo_urls(html)
    embed_value = url.replace("/photo/", "/video/", 1)
    oembed_url = "https://www.tiktok.com/oembed?url=" + urllib.parse.quote(embed_value, safe="")
    request = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    thumbnail = str(metadata.get("thumbnail_url") or "")
    # The oEmbed thumbnail is commonly a cropped 16:9 preview. Only use it
    # when the post did not expose any of its original photo URLs.
    if thumbnail and not urls:
        urls.append(thumbnail)
    return urls, metadata


def run_photo_download(job_id: str, url: str, destination: Path) -> list[Path]:
    """Save the image exposed by a TikTok photo post as a PNG."""
    update_job(job_id, status="downloading", message="Preparing photo…")
    image_urls, metadata = fetch_tiktok_photo_urls(url)
    if not image_urls:
        raise RuntimeError("TikTok did not expose a downloadable photo for this post.")
    title = re.sub(r"[^A-Za-z0-9._ -]+", "", str(metadata.get("title") or "TikTok photo")).strip() or "TikTok photo"
    post_id = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or "photo"
    total = len(image_urls)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    outputs: list[Path] = []
    for index, image_url in enumerate(image_urls, start=1):
        check_canceled(job_id)
        suffix = f" ({index:02d})" if total > 1 else ""
        stem = f"{title[:120]} [{post_id}]{suffix}"
        source = destination / f".{stem}.source.jpg"
        output = destination / f"{stem}.png"
        started = time.monotonic()
        received = 0
        with urllib.request.urlopen(image_url, timeout=30) as response, source.open("wb") as stream:
            length = response.length
            while chunk := response.read(65536):
                check_canceled(job_id)
                stream.write(chunk)
                received += len(chunk)
                elapsed = time.monotonic() - started
                speed = received / elapsed if elapsed > 0 else 0
                fraction = min(received / length, 1) if length else 0
                remaining = (length - received) / speed if length and speed and length >= received else None
                update_job(job_id, progress=95 * (index - 1 + .9 * fraction) / total,
                           message=f"Downloading photo {index} of {total}…",
                           speed=f"{speed / 1024:.0f} KiB/s" if elapsed >= .3 else "",
                           eta=format_eta(remaining) if elapsed >= .3 else "",
                           eta_scope="Photo" if total > 1 else "")
        update_job(job_id, progress=95 * (index - .1) / total,
                   message=f"Converting photo {index} of {total}…", speed="", eta="")
        with start_download_process(
            job_id, [ffmpeg, "-nostdin", "-y", "-i", str(source), "-frames:v", "1", str(output)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) as process:
            return_code = process.wait()
        update_job(job_id, process=None)
        check_canceled(job_id)
        source.unlink(missing_ok=True)
        if return_code != 0 or not output.is_file():
            raise RuntimeError("Could not convert a TikTok photo to PNG.")
        outputs.append(output)
    return outputs


def fallback_filename(title: str, output_format: str) -> str:
    """Use a browser-supplied title only when yt-dlp did not report a path."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", str(title or "")).strip()
    cleaned = cleaned[:180].strip(" .")
    return cleaned or f"{output_format.upper()} download"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    minutes, seconds = divmod(max(0, int(seconds + .999)), 60)
    return f"{minutes:02d}:{seconds:02d}"


def transfer_progress(percent: float, format_id: str, formats: list[dict]) -> tuple[float, bool]:
    """Report one monotonically advancing transfer across separate AV streams."""
    for index, entry in enumerate(formats):
        if entry["format_id"] == format_id:
            sizes = [f.get("filesize") or f.get("filesize_approx") for f in formats]
            weights = sizes if all(sizes) else [1] * len(formats)
            return 95 * (sum(weights[:index]) + weights[index] * percent / 100) / sum(weights), len(formats) > 1
    return .95 * percent, False


def run_download(job_id: str, url: str, output_format: str, destination: Path, title: str = "") -> list[Path]:
    if output_format == "png":
        return run_photo_download(job_id, url, destination)
    output_template = str(destination / "%(title).180B [%(id)s].%(ext)s")
    command = [
        sys.executable,
        "-u",
        "-m",
        "yt_dlp",
        "--newline",
        # --print implies quiet mode, which otherwise suppresses progress.
        "--progress",
        "--no-quiet",
        "--no-playlist",
        # Replace stale outputs from interrupted runs so Windows can complete
        # yt-dlp's temporary-file rename instead of failing with Access Denied.
        "--force-overwrites",
        "--socket-timeout", "30",
        "--retries", "3",
        "--fragment-retries", "3",
        "--restrict-filenames",
        "--progress-template",
        "download:DOWNLOAD_PROGRESS:%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(info.format_id)s",
        "--print",
        "before_dl:DOWNLOAD_FORMATS:%(requested_formats.:.{format_id,filesize,filesize_approx})j",
        "--print",
        "after_move:RESULT:%(filepath)s",
        "-o",
        output_template,
    ]
    if output_format == "mp3":
        command += [
            # Avoid downloading a video stream that will be discarded during
            # MP3 extraction.
            # Prefer AAC in an M4A container for a smaller, broadly supported
            # source stream before falling back to the site's best audio.
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "-x", "--audio-format", "mp3", "--audio-quality", "0",
            # Keep the V0 bitrate target while reducing LAME's CPU effort.
            "--postprocessor-args", "ExtractAudio+ffmpeg_o:-compression_level 5",
        ]
        if is_youtube_url(url):
            command += [
                "--embed-thumbnail",
                "--convert-thumbnails", "jpg",
                "--embed-metadata",
                "--no-embed-chapters",
                "--no-embed-info-json",
            ]
    else:
        command += [
            "-f", "bestvideo*+bestaudio/best",
            "-S", "ext:mp4:m4a",
            "--merge-output-format", "mp4",
            "--remux-video", "mp4",
        ]
    if is_tiktok_url(url):
        command += ["--impersonate", "chrome"]
    if is_tiktok_sound_url(url):
        command += ["--playlist-end", "1"]
    command.append(url)

    update_job(job_id, status="downloading", message="Connecting to video site…")
    process = start_download_process(
        job_id, command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    start_job_heartbeat(job_id, process)
    last_line = ""
    result_path: Path | None = None
    formats: list[dict] = []
    progress = 0.0
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        last_line = line
        if line.startswith("RESULT:"):
            result_path = Path(line.removeprefix("RESULT:"))
            continue
        if line.startswith("DOWNLOAD_FORMATS:"):
            values = line.removeprefix("DOWNLOAD_FORMATS:")
            if values.startswith("["):
                formats = json.loads(values)
            continue
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
        match = re.fullmatch(r"DOWNLOAD_PROGRESS:([^|]*)\|([^|]*)\|([^|]*)\|(.*)", line)
        if match:
            percent = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", match.group(1).strip())
            speed = match.group(2).strip()
            eta = match.group(3).strip()
            split_streams = False
            if percent:
                current, split_streams = transfer_progress(min(float(percent.group(1)), 100), match.group(4), formats)
                progress = max(progress, current)
            update_job(
                job_id, progress=progress, message="Downloading media…",
                speed=speed if speed not in {"N/A", "Unknown"} else "",
                eta=eta if re.fullmatch(r"\d+(?::\d{2}){1,2}", eta) else "",
                eta_scope="Stream" if split_streams else "",
            )
        elif line.startswith("[ExtractAudio]"):
            update_job(job_id, progress=98, speed="", eta="", message="Converting to MP3…")
        elif line.startswith(("[Merger]", "[VideoConvertor]", "[VideoRemuxer]")):
            update_job(job_id, progress=98, speed="", eta="", message="Merging video and audio…")
        elif line.startswith("[download] Destination"):
            update_job(job_id, message="Downloading media…")
        elif line.startswith("[youtube]") and "Downloading" in line:
            update_job(job_id, message="Preparing YouTube streams…")

    return_code = process.wait()
    process.stdout.close()
    update_job(job_id, process=None)
    check_canceled(job_id)
    if return_code != 0:
        if is_tiktok_sound_url(url):
            error = (
                "TikTok blocked this sound-page download. Paste a TikTok video that uses "
                "the sound and choose MP3 instead."
            )
        else:
            detail = last_line or "yt-dlp failed."
            error = (
                "yt-dlp could not recognize that link. The site may not be supported, "
                "or the media may require sign-in."
                if "unsupported url" in detail.lower() or "no suitable" in detail.lower()
                else detail
            )
        raise ValueError(error)
    if (result_path is None or result_path.resolve().parent != destination.resolve()
            or result_path.suffix.lower() != f".{output_format}" or not result_path.is_file()):
        raise ValueError("The downloader did not produce a finished file.")
    return [result_path]


def publish_file_without_overwrite(output: Path, target: Path) -> None:
    """Move a staged file into place without ever replacing another file."""
    try:
        os.link(output, target)
    except FileExistsError:
        raise
    except OSError:
        # Some removable or network filesystems do not support hard links.
        # Create the destination exclusively there, then copy the finished file.
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        try:
            with os.fdopen(descriptor, "wb") as destination_stream:
                descriptor = -1
                with output.open("rb") as source_stream:
                    shutil.copyfileobj(source_stream, destination_stream, length=1024 * 1024)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            target.unlink(missing_ok=True)
            raise
    try:
        output.unlink(missing_ok=True)
    except OSError:
        # The published destination is complete; staging cleanup retries later.
        pass


def publish_download(outputs: list[Path], destination: Path) -> list[Path]:
    """Publish files without replacing existing user files."""
    published: list[tuple[Path, Path]] = []
    reserved: set[Path] = set()
    try:
        for output in outputs:
            number = 1
            while True:
                if number == 1:
                    target = destination / output.name
                else:
                    target = destination / f"{output.stem} ({number}){output.suffix}"
                if target.exists() or target.is_symlink() or target in reserved:
                    number += 1
                    continue
                try:
                    # The hard-link path is atomic; exclusive-copy fallback
                    # keeps removable filesystems safe without overwriting.
                    publish_file_without_overwrite(output, target)
                except FileExistsError:
                    number += 1
                    continue
                except OSError as error:
                    raise OSError(
                        f"Could not safely save {output.name} without replacing an existing file. "
                        "Try a folder on a local filesystem that supports hard links."
                    ) from error
                try:
                    output.unlink()
                except OSError:
                    target.unlink(missing_ok=True)
                    raise
                reserved.add(target)
                published.append((output, target))
                break
    except OSError:
        rollback_errors: list[Path] = []
        for output, target in reversed(published):
            try:
                target.replace(output)
            except OSError:
                rollback_errors.append(target)
        if rollback_errors:
            raise OSError("Could not roll back files saved here: " + ", ".join(path.name for path in rollback_errors))
        raise
    return [target for _, target in published]


def clean_download_staging(staging: Path) -> None:
    # A terminated FFmpeg or yt-dlp child can briefly retain its file handles.
    for attempt in range(6):
        try:
            shutil.rmtree(staging)
            return
        except FileNotFoundError:
            if not staging.exists():
                return
            if attempt == 5:
                raise
        except PermissionError:
            if attempt == 5:
                raise
        time.sleep(.2)


def download_worker(job_id: str, url: str, output_format: str, destination: Path, title: str = "") -> None:
    staging = None
    cleanup_error = None
    try:
        check_canceled(job_id)
        staging = Path(tempfile.mkdtemp(prefix=".downloadable-", dir=destination))
        outputs = run_download(job_id, url, output_format, staging, title)
        with LOCK:
            job = JOBS[job_id]
            if job.get("cancel_requested"):
                raise DownloadCanceled
            published = publish_download(outputs, destination)
            filename = published[0].name if len(published) == 1 else f"{len(published)} PNG files"
            job.update(status="complete", progress=100, speed="", eta="",
                       message="Download complete.", filename=filename, process=None)
    except DownloadCanceled:
        pass
    except Exception as error:
        log_error(f"Download failed for {url}", error)
        update_job(job_id, status="error", error=str(error), process=None)
    finally:
        if staging is not None:
            try:
                clean_download_staging(staging)
            except OSError as error:
                cleanup_error = f"Temporary files could not be removed from {staging}."
                log_error(cleanup_error, error)
        with LOCK:
            job = JOBS[job_id]
            if job.get("cancel_requested"):
                message = "Download canceled."
                if cleanup_error:
                    message += f" {cleanup_error}"
                job.update(status="error", error=message, message=message,
                           speed="", eta="", process=None)


class Handler(BaseHTTPRequestHandler):
    server_version = "PersonalDownloader/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Helper-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def authenticated(self) -> bool:
        if not TOKEN or self.headers.get("X-Helper-Token") != TOKEN:
            self.send_json(403, {"error": "Helper authentication failed. Run the platform setup launcher again."})
            return False
        origin = self.headers.get("Origin", "")
        # Chrome may omit Origin on a privileged extension request. The token is
        # still required; reject an explicit non-extension Origin from a web page.
        if origin and not origin.startswith("chrome-extension://"):
            self.send_json(403, {"error": "Requests are accepted only from a Chrome extension."})
            return False
        return True

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16_384:
            raise ValueError("Request is too large.")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if not self.authenticated():
            return
        if self.path == "/state":
            with STATE_LOCK:
                state = load_state()
            with LOCK:
                active_jobs = [
                    job_id for job_id, job in JOBS.items()
                    if job["status"] not in {"complete", "error"}
                ]
            self.send_json(
                200,
                {
                    "mp3_destination": state.get("mp3_destination", ""),
                    "mp4_destination": state.get("mp4_destination", ""),
                    "png_destination": state.get("png_destination", ""),
                    "active_job": active_jobs[0] if active_jobs else None,
                    "active_jobs": active_jobs,
                    "version": json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")).get("version", ""),
                    "update": json.loads((ROOT / ".update-available.json").read_text(encoding="utf-8")) if (ROOT / ".update-available.json").exists() else None,
                },
            )
            return
        match = re.fullmatch(r"/jobs/([a-f0-9-]+)", self.path)
        if match:
            with LOCK:
                job = JOBS.get(match.group(1))
                payload = ({key: value for key, value in job.items()
                            if key not in {"process", "cancel_requested", "download_key"}} if job else None)
            self.send_json(200, payload) if payload else self.send_json(404, {"error": "Job not found."})
            return
        self.send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self.authenticated():
            return
        try:
            body = self.read_json()
            if self.path == "/choose-folder":
                output_format = str(body.get("format", ""))
                if output_format not in {"mp3", "mp4", "png"}:
                    raise ValueError("Choose an MP3, MP4, or PNG folder.")
                destination = choose_folder(output_format)
                remember_destination(output_format, destination)
                self.send_json(200, {"format": output_format, "destination": destination})
                return
            if self.path == "/download":
                url = str(body.get("url", ""))
                output_format = str(body.get("format", ""))
                title = str(body.get("title", "")).strip()[:180]
                destination = Path(str(body.get("destination", ""))).expanduser().resolve()
                download_url = resolve_tiktok_short_url(url)
                if not valid_media_url(download_url):
                    raise ValueError("Paste a valid HTTPS media link.")
                if output_format not in {"mp3", "mp4", "png"}:
                    raise ValueError("Format must be MP3, MP4, or PNG.")
                if output_format == "png" and not is_tiktok_photo_url(download_url):
                    raise ValueError("PNG downloads are only available for TikTok /photo/ posts.")
                if not destination.is_dir():
                    raise ValueError("The selected destination folder no longer exists.")
                if not os.access(destination, os.W_OK):
                    raise ValueError("The selected destination is not writable.")
                with LOCK:
                    active = [job for job in JOBS.values() if job["status"] not in {"complete", "error"}]
                    download_key = (download_url, output_format, str(destination))
                    if any(job.get("download_key") == download_key for job in active):
                        raise ValueError("That download is already running.")
                    if len(active) >= 3:
                        raise ValueError("Three downloads are already running. Wait for one to finish.")
                    remember_destination(output_format, str(destination))
                    job_id = str(uuid.uuid4())
                    JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Queued…",
                                    "title": title, "format": output_format, "download_key": download_key}
                threading.Thread(
                    target=download_worker,
                    args=(job_id, download_url, output_format, destination, title),
                    daemon=True,
                ).start()
                self.send_json(202, {"job_id": job_id})
                return
            cancel_match = re.fullmatch(r"/jobs/([a-f0-9-]+)/cancel", self.path)
            if cancel_match:
                job_id = cancel_match.group(1)
                with LOCK:
                    job = JOBS.get(job_id)
                    canceled = bool(job and job["status"] not in {"complete", "error"})
                    if canceled:
                        job.update(cancel_requested=True, status="canceling", message="Canceling…", speed="", eta="")
                        if process := job.get("process"):
                            stop_download_process(process)
                if not job:
                    self.send_json(404, {"error": "Job not found."})
                    return
                self.send_json(200, {"canceled": canceled})
                return
            if self.path == "/reset-settings":
                with STATE_LOCK:
                    save_state({})
                self.send_json(200, {"reset": True})
                return
            if self.path == "/open-logs":
                open_log_folder()
                self.send_json(200, {"opened": True, "path": str(LOG_DIR)})
                return
            if self.path == "/check-update":
                result = check_for_update()
                self.send_json(200, result)
                return
            if self.path == "/restart":
                if not (ROOT / ".downloadable-update.zip").exists():
                    raise ValueError("There is no staged update to apply.")
                self.send_json(202, {"restarting": True})
                threading.Thread(target=schedule_helper_restart, daemon=True).start()
                return
            if self.path == "/repair-setup":
                open_setup()
                self.send_json(200, {"opened": True})
                return
            self.send_json(404, {"error": "Not found."})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except Exception as error:
            log_error(f"HTTP {self.command} {self.path}", error)
            self.send_json(500, {"error": str(error)})


def main() -> None:
    add_windows_tool_path()
    apply_staged_update()
    if not TOKEN:
        print("Missing helper token. Run the platform setup launcher first.", file=sys.stderr)
        raise SystemExit(1)
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("yt-dlp is not installed. Run the platform setup launcher first.", file=sys.stderr)
        raise SystemExit(1)
    if not shutil.which("ffmpeg"):
        print("Warning: ffmpeg is not installed or is not on PATH. Folder picking will work, but downloads need ffmpeg.", file=sys.stderr)
    print(f"Personal Video & Audio Downloader helper is running at http://{HOST}:{PORT}")
    threading.Thread(target=update_loop, daemon=True).start()
    print("Keep this window open while downloading. Press Control-C to stop.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Downloadable helper stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
