"""Local integration test. Run with the helper's Python and FFmpeg on PATH."""

import contextlib
import functools
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helper"))
import helper


@contextlib.contextmanager
def serve(handler):
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


class QuietHelper(helper.Handler):
    def log_message(self, *_args):
        pass


class MediaSmokeTest(unittest.TestCase):
    def test_overlapping_mp3_jobs_keep_progress_and_cancel_only_one_job(self):
        webm = self.make_audio("libopus", "webm")
        aac = self.make_audio("aac", "adts")

        class Media(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                sample, content_type = (
                    (webm, "audio/webm") if self.path.endswith(".webm") else (aac, "audio/aac")
                )
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(sample)))
                self.end_headers()
                try:
                    for offset in range(0, len(sample), 4096):
                        self.wfile.write(sample[offset:offset + 4096])
                        time.sleep(.05)
                except ConnectionError:
                    pass

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory(prefix="downloadable-smoke-") as folder:
            root = Path(folder)
            destination = root / "downloads"
            destination.mkdir()
            existing = destination / "existing.webm"
            existing.write_bytes(b"existing user file")
            with (
                serve(Media) as media_url,
                serve(QuietHelper) as api_url,
                patch.object(helper, "TOKEN", "fixture-only"),
                patch.object(helper, "STATE_FILE", root / "state.json"),
                patch.object(helper, "JOBS", {}),
                patch.object(helper, "valid_media_url", side_effect=lambda url: url.startswith(media_url + "/")),
            ):
                def request(path, payload=None):
                    data = json.dumps(payload).encode() if payload is not None else None
                    req = urllib.request.Request(
                        api_url + path, data=data, headers={"X-Helper-Token": "fixture-only"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as response:
                        return json.load(response)

                def start(name):
                    job = request("/download", {
                        "url": f"{media_url}/{name}", "format": "mp3",
                        "destination": str(destination), "title": name,
                    })
                    return f"/jobs/{job['job_id']}"

                canceled = start("cancel.webm")
                surviving = start("finish.aac")
                try:
                    def both_transferring():
                        active = request("/state")["active_jobs"]
                        polls = [request(job) for job in (canceled, surviving)]
                        return len(active) == 2 and all(
                            0 < job["progress"] < 95 and job["speed"] and job["eta"] for job in polls
                        )

                    self.wait_until(both_transferring)
                    self.assertTrue(list(destination.glob(".downloadable-*/*.webm.part")))
                    self.assertTrue(request(canceled + "/cancel", {})["canceled"])
                    self.wait_until(lambda: all(
                        request(job)["status"] in {"complete", "error"} for job in (canceled, surviving)
                    ))
                    self.assertEqual(request(canceled)["error"], "Download canceled.")
                    finished = request(surviving)
                    self.assertEqual(finished["status"], "complete", finished)
                    self.assertEqual(finished["progress"], 100)
                finally:
                    for job in (canceled, surviving):
                        request(job + "/cancel", {})
                    self.wait_until(lambda: not request("/state")["active_jobs"])

            saved = destination / finished["filename"]
            self.assertEqual(saved.suffix, ".mp3")
            self.assertEqual(set(destination.iterdir()), {existing, saved})
            self.assertEqual(existing.read_bytes(), b"existing user file")
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(saved), "-f", "null", "-"], check=True)

    def test_source_selection_split_mp4_and_portrait_png(self):
        with tempfile.TemporaryDirectory(prefix="downloadable-formats-") as folder:
            root = Path(folder)
            destination = root / "output"
            destination.mkdir()
            fixtures = [
                ("testsrc2=size=320x240:rate=24", ["-t", "4", "-c:v", "libx264"], "video.mp4"),
                ("anoisesrc", ["-t", "4", "-c:a", "aac"], "audio.m4a"),
                ("anoisesrc", ["-t", "4", "-c:a", "libopus"], "audio.webm"),
                ("testsrc=size=1080x1920", ["-frames:v", "1"], "portrait.png"),
            ]
            for source, options, name in fixtures:
                subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "lavfi", "-i", source, *options, str(root / name),
                ], check=True)

            fetched = []

            class Media(http.server.SimpleHTTPRequestHandler):
                def do_GET(self):
                    fetched.append(self.path)
                    super().do_GET()

                def log_message(self, *_args):
                    pass

            with serve(functools.partial(Media, directory=folder)) as media_url:
                split_formats = [
                        {"format_id": "video", "url": media_url + "/video.mp4", "ext": "mp4",
                         "vcodec": "avc1", "acodec": "none", "filesize": (root / "video.mp4").stat().st_size},
                        {"format_id": "audio", "url": media_url + "/audio.m4a", "ext": "m4a",
                         "vcodec": "none", "acodec": "mp4a", "filesize": (root / "audio.m4a").stat().st_size},
                ]
                opus_format = {
                    "format_id": "opus", "url": media_url + "/audio.webm", "ext": "webm",
                    "vcodec": "none", "acodec": "opus", "filesize": (root / "audio.webm").stat().st_size,
                }
                metadata = {
                    "mp4": split_formats,
                    "preferred": [*split_formats, opus_format],
                    "fallback": [split_formats[0], opus_format],
                }
                for key, formats in metadata.items():
                    (root / f"{key}.json").write_text(json.dumps({
                        "id": key, "title": key, "formats": formats,
                    }), encoding="utf-8")
                launch = helper.start_download_process
                progress = helper.update_job
                stream_updates = []

                def start(job_id, command, **options):
                    if job_id in metadata:
                        command = [*command[:-1], "--load-info-json", str(root / f"{job_id}.json")]
                    return launch(job_id, command, **options)

                def record(job_id, **changes):
                    if job_id == "mp4" and "progress" in changes:
                        stream_updates.append(changes)
                    progress(job_id, **changes)

                jobs = {name: {"status": "queued"} for name in (*metadata, "png")}
                with (
                    patch.object(helper, "JOBS", jobs),
                    patch.object(helper, "start_download_process", side_effect=start),
                    patch.object(helper, "update_job", side_effect=record),
                    patch.object(helper, "fetch_tiktok_photo_urls",
                                 return_value=([media_url + "/portrait.png"], {"title": "Portrait"})),
                ):
                    helper.download_worker("mp4", media_url, "mp4", destination)
                    helper.download_worker("png", "https://www.tiktok.com/@fixture/photo/123", "png", destination)
                    for job_id, selected in (("preferred", "/audio.m4a"), ("fallback", "/audio.webm")):
                        fetched.clear()
                        helper.download_worker(job_id, media_url, "mp3", destination)
                        self.assertEqual(jobs[job_id]["status"], "complete", jobs[job_id])
                        self.assertEqual(set(fetched), {selected})

            for job in jobs.values():
                self.assertEqual(job["status"], "complete", job)
            percentages = [update["progress"] for update in stream_updates]
            self.assertEqual(percentages, sorted(percentages))
            self.assertGreater(len(set(percentages)), 2)
            self.assertTrue(any(update.get("eta_scope") == "Stream" for update in stream_updates))
            movie = self.probe(destination / jobs["mp4"]["filename"])
            self.assertEqual({stream["codec_type"] for stream in movie}, {"audio", "video"})
            photo = self.probe(destination / jobs["png"]["filename"])[0]
            self.assertEqual((photo["width"], photo["height"]), (1080, 1920))
            for key in ("preferred", "fallback"):
                audio = self.probe(destination / jobs[key]["filename"])
                self.assertEqual([stream["codec_name"] for stream in audio], ["mp3"])

    @staticmethod
    def probe(path):
        result = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
            "-of", "json", str(path),
        ])
        return json.loads(result)["streams"]

    @staticmethod
    def make_audio(encoder, container):
        return subprocess.check_output([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=45",
            "-c:a", encoder, "-f", container, "-",
        ])

    def wait_until(self, condition):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.1)
        self.fail("Media smoke test timed out")


if __name__ == "__main__":
    unittest.main()
