#!/usr/bin/env python3
"""Local HTTP helper for the Personal Video & Audio Downloader extension."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import urllib.request
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:  # Windows Python installs may omit Tk.
    tk = None
    filedialog = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HOST = "127.0.0.1"
PORT = 47821
UPDATE_INTERVAL = 3600
RELEASE_API = "https://api.github.com/repos/Justa-Doge/Downloadable/releases/latest"
ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / ".helper-token"
STATE_FILE = ROOT / ".state.json"
DEFAULT_DESTINATION = Path.home() / "Downloads" / "MUSIC!!!!!"
DEFAULT_VIDEO_DESTINATION = Path.home() / "Movies"
TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip() if TOKEN_FILE.exists() else ""
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3]) or (0,)


def check_for_update() -> None:
    try:
        current = json.loads((ROOT / ".." / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"]
        request = urllib.request.Request(RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Downloadable-Updater"})
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.loads(response.read().decode("utf-8"))
        latest = str(release.get("tag_name", "")).lstrip("v")
        if version_tuple(latest) <= version_tuple(current):
            return
        asset = next((item for item in release.get("assets", []) if str(item.get("name", "")).endswith(".zip")), None)
        if not asset:
            return
        update_path = ROOT / ".downloadable-update.zip"
        urllib.request.urlretrieve(asset["browser_download_url"], update_path)
        (ROOT / ".update-available.json").write_text(json.dumps({"version": latest, "release_url": release.get("html_url", ""), "asset": asset["name"]}, indent=2), encoding="utf-8")
        print(f"Update {latest} downloaded. Restart the helper to apply it.")
    except Exception as error:
        print(f"Update check skipped: {error}")


def update_loop() -> None:
    while True:
        check_for_update()
        threading.Event().wait(UPDATE_INTERVAL)


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
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def choose_folder(output_format: str) -> str:
    description = "MP3 audio" if output_format == "mp3" else "MP4 video"
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class BROWSEINFO(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", wintypes.LPWSTR), ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p),
                ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int),
            ]

        display_name = ctypes.create_unicode_buffer(260)
        info = BROWSEINFO(
            None, None, display_name, f"Choose where {description} should be saved",
            0x0001 | 0x0040, None, 0, 0,
        )
        shell32 = ctypes.windll.shell32
        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            raise ValueError("Folder selection canceled.")
        try:
            path_buffer = ctypes.create_unicode_buffer(32768)
            if not shell32.SHGetPathFromIDListW(pidl, path_buffer):
                raise RuntimeError("Windows returned no folder path.")
            return str(Path(path_buffer.value).resolve())
        finally:
            ctypes.windll.ole32.CoTaskMemFree(pidl)
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
    )
    return parsed.scheme == "https" and (youtube_media or youtube_short_link or tiktok_media)


def is_tiktok_sound_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return (host == "tiktok.com" or host.endswith(".tiktok.com")) and "/music/" in parsed.path


def is_youtube_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def update_job(job_id: str, **changes: object) -> None:
    with LOCK:
        JOBS[job_id].update(changes)


def run_download(job_id: str, url: str, output_format: str, destination: Path) -> None:
    output_template = str(destination / "%(title).180B [%(id)s].%(ext)s")
    command = [
        str(ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")),
        "--newline",
        "--no-playlist",
        "--no-overwrites",
        "--restrict-filenames",
        "--progress-template",
        "download:%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--print",
        "after_move:RESULT:%(filepath)s",
        "-o",
        output_template,
    ]
    if output_format == "mp3":
        command += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
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
        ]
    if is_tiktok_sound_url(url):
        command += ["--playlist-end", "1"]
    command.append(url)

    update_job(job_id, status="downloading", message="Starting download…")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    last_line = ""
    result_path: Path | None = None
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        last_line = line
        if line.startswith("RESULT:"):
            result_path = Path(line.removeprefix("RESULT:"))
            continue
        match = re.search(r"download:\s*([\d.]+)%\|([^|]*)\|([^|]*)", line)
        if match:
            progress = float(match.group(1))
            speed = match.group(2).strip()
            eta = match.group(3).strip()
            message = f"{progress:.1f}%"
            if speed and speed != "N/A":
                message += f" · {speed}"
            if eta and eta != "N/A":
                message += f" · ETA {eta}"
            update_job(job_id, progress=progress, message=message)
        elif line.startswith("[ExtractAudio]") or line.startswith("[VideoConvertor]"):
            update_job(job_id, progress=99, message="Converting…")

    return_code = process.wait()
    if return_code != 0:
        if is_tiktok_sound_url(url):
            error = (
                "TikTok blocked this sound-page download. Paste a TikTok video that uses "
                "the sound and choose MP3 instead."
            )
        else:
            error = last_line or "yt-dlp failed."
        update_job(job_id, status="error", error=error)
        return

    update_job(
        job_id,
        status="complete",
        progress=100,
        message="Download complete.",
        filename=result_path.name if result_path else f"{output_format.upper()} download",
    )


def download_worker(job_id: str, url: str, output_format: str, destination: Path) -> None:
    try:
        run_download(job_id, url, output_format, destination)
    except Exception as error:
        update_job(job_id, status="error", error=f"Helper failed: {error}")


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
            self.send_json(403, {"error": "Helper authentication failed. Run setup.command again."})
            return False
        origin = self.headers.get("Origin", "")
        if not origin.startswith("chrome-extension://"):
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
            state = load_state()
            save_state(state)
            with LOCK:
                active = next(
                    (job_id for job_id, job in JOBS.items() if job["status"] not in {"complete", "error"}),
                    None,
                )
            self.send_json(
                200,
                {
                    "mp3_destination": state.get("mp3_destination", ""),
                    "mp4_destination": state.get("mp4_destination", ""),
                    "active_job": active,
                    "update": json.loads((ROOT / ".update-available.json").read_text(encoding="utf-8")) if (ROOT / ".update-available.json").exists() else None,
                },
            )
            return
        match = re.fullmatch(r"/jobs/([a-f0-9-]+)", self.path)
        if match:
            with LOCK:
                job = JOBS.get(match.group(1))
                payload = dict(job) if job else None
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
                if output_format not in {"mp3", "mp4"}:
                    raise ValueError("Choose either the MP3 or MP4 folder.")
                destination = choose_folder(output_format)
                state = load_state()
                state[f"{output_format}_destination"] = destination
                save_state(state)
                self.send_json(200, {"format": output_format, "destination": destination})
                return
            if self.path == "/download":
                url = str(body.get("url", ""))
                output_format = str(body.get("format", ""))
                destination = Path(str(body.get("destination", ""))).expanduser().resolve()
                if not valid_media_url(url):
                    raise ValueError("That is not a supported YouTube or TikTok video URL.")
                if output_format not in {"mp3", "mp4"}:
                    raise ValueError("Format must be MP3 or MP4.")
                if not destination.is_dir():
                    raise ValueError("The selected destination folder no longer exists.")
                if not os.access(destination, os.W_OK):
                    raise ValueError("The selected destination is not writable.")
                with LOCK:
                    if any(job["status"] not in {"complete", "error"} for job in JOBS.values()):
                        raise ValueError("Another download is already running.")
                    job_id = str(uuid.uuid4())
                    JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Queued…"}
                state = load_state()
                state[f"{output_format}_destination"] = str(destination)
                save_state(state)
                threading.Thread(
                    target=download_worker,
                    args=(job_id, url, output_format, destination),
                    daemon=True,
                ).start()
                self.send_json(202, {"job_id": job_id})
                return
            self.send_json(404, {"error": "Not found."})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": str(error)})


def main() -> None:
    if not TOKEN:
        print("Missing helper token. Run setup.command or setup.ps1 first.", file=sys.stderr)
        raise SystemExit(1)
    yt_dlp = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if not yt_dlp.exists():
        print("yt-dlp is not installed. Run setup.command or setup.ps1 first.", file=sys.stderr)
        raise SystemExit(1)
    if not shutil.which("ffmpeg"):
        print("ffmpeg is not installed or is not on PATH.", file=sys.stderr)
        raise SystemExit(1)
    print(f"Personal Video & Audio Downloader helper is running at http://{HOST}:{PORT}")
    threading.Thread(target=update_loop, daemon=True).start()
    print("Keep this window open while downloading. Press Control-C to stop.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
