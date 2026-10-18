import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helper"))
import helper


class FolderPickerTests(unittest.TestCase):
    @unittest.skipUnless(helper.os.name == "nt", "Windows picker test")
    def test_windows_picker_uses_native_sta_dialog(self):
        selected = str(Path(tempfile.gettempdir()).resolve())
        completed = type("Completed", (), {"returncode": 0, "stdout": selected, "stderr": ""})()
        with mock.patch.object(helper.subprocess, "run", return_value=completed) as run:
            self.assertEqual(helper.choose_folder("mp3"), selected)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["powershell.exe", "-NoProfile", "-STA"])
        startupinfo = run.call_args.kwargs["startupinfo"]
        self.assertTrue(startupinfo.dwFlags & helper.subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(startupinfo.wShowWindow, helper.subprocess.SW_HIDE)
        self.assertIn("IFileOpenDialog", command[-1])

    def test_macos_picker_uses_finder_choose_folder(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": "/Users/test/Music/\n", "stderr": ""})()
        with mock.patch.object(helper.os, "name", "posix"), mock.patch.object(helper.sys, "platform", "darwin"), mock.patch.object(helper.subprocess, "run", return_value=completed) as run, mock.patch.object(helper, "Path") as path_class:
            path_class.return_value.resolve.return_value = "/Users/test/Music"
            self.assertEqual(helper.choose_folder("mp3"), "/Users/test/Music")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "osascript")
        self.assertIn("tell application \"Finder\"", command[-1])
        self.assertIn("choose folder", command[-1])

    def test_macos_picker_cancel_is_reported(self):
        completed = type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "User canceled."})()
        with mock.patch.object(helper.os, "name", "posix"), mock.patch.object(helper.sys, "platform", "darwin"), mock.patch.object(helper.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(ValueError, "canceled"):
                helper.choose_folder("mp4")


class SharedHelperTests(unittest.TestCase):
    def test_fallback_filename_uses_title_or_existing_default(self):
        self.assertEqual(helper.fallback_filename("A video: title", "mp4"), "A video title")
        self.assertEqual(helper.fallback_filename("", "mp3"), "MP3 download")

    def test_job_status_omits_live_process_object(self):
        job_id = "12345678-1234-1234-1234-123456789abc"
        helper.JOBS[job_id] = {
            "status": "downloading",
            "progress": 42,
            "message": "Downloading…",
            "process": object(),
        }
        try:
            handler = object.__new__(helper.Handler)
            handler.path = f"/jobs/{job_id}"
            handler.headers = {"X-Helper-Token": "test-token"}
            handler.send_json = mock.Mock()
            with mock.patch.object(helper, "TOKEN", "test-token"):
                handler.do_GET()
            handler.send_json.assert_called_once_with(
                200,
                {"status": "downloading", "progress": 42, "message": "Downloading…"},
            )
        finally:
            del helper.JOBS[job_id]

    def test_download_process_stays_hidden_on_windows(self):
        job_id = "test-hidden-download"
        helper.JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Queued…"}
        try:
            # run_download only builds the output template before Popen. Use
            # the project directory so Windows' sandbox temp cleanup cannot
            # mask the assertion with an unrelated PermissionError.
            directory = Path(__file__).resolve().parents[1]
            with mock.patch.object(helper.subprocess, "Popen") as popen:
                popen.return_value.stdout = io.StringIO("")
                popen.return_value.wait.return_value = 0
                helper.run_download(job_id, "https://www.youtube.com/watch?v=test", "mp4", directory)
            if helper.os.name == "nt":
                self.assertEqual(popen.call_args.kwargs["creationflags"], helper.subprocess.CREATE_NO_WINDOW)
            else:
                self.assertNotIn("creationflags", popen.call_args.kwargs)
        finally:
            del helper.JOBS[job_id]

    def test_extension_request_without_origin_uses_token(self):
        handler = object.__new__(helper.Handler)
        handler.headers = {"X-Helper-Token": "test-token"}
        handler.send_json = mock.Mock()
        with mock.patch.object(helper, "TOKEN", "test-token"):
            self.assertTrue(handler.authenticated())
        handler.send_json.assert_not_called()

    def test_web_page_origin_is_rejected_even_with_token(self):
        handler = object.__new__(helper.Handler)
        handler.headers = {"X-Helper-Token": "test-token", "Origin": "https://example.com"}
        handler.send_json = mock.Mock()
        with mock.patch.object(helper, "TOKEN", "test-token"):
            self.assertFalse(handler.authenticated())
        handler.send_json.assert_called_once()

    def test_manifest_used_by_update_check_exists(self):
        manifest = helper.ROOT / "extension" / "manifest.json"
        self.assertTrue(manifest.is_file())
        self.assertIn("version", json.loads(manifest.read_text(encoding="utf-8")))

    def test_release_asset_prefers_current_platform_archive(self):
        assets = [
            {"name": "personal-media-downloader-1.5.1.zip"},
            {"name": "personal-media-downloader-macos-1.5.2.zip"},
            {"name": "personal-media-downloader-windows-1.5.2.zip"},
        ]
        with mock.patch.object(helper, "runtime_platform", return_value="macos"):
            self.assertEqual(helper.select_release_asset(assets)["name"], "personal-media-downloader-macos-1.5.2.zip")

    def test_supported_urls(self):
        self.assertTrue(helper.valid_media_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(helper.valid_media_url("https://youtu.be/abc"))
        self.assertTrue(helper.valid_media_url("https://www.tiktok.com/@user/video/123"))
        self.assertTrue(helper.valid_media_url("https://www.tiktok.com/@user/photo/123"))
        self.assertTrue(helper.valid_media_url("https://www.tiktok.com/t/ZTRC5xgJp"))
        self.assertTrue(helper.valid_media_url("https://www.tiktok.com/v/123"))
        self.assertTrue(helper.valid_media_url("https://vm.tiktok.com/ZMabc123/"))
        self.assertTrue(helper.valid_media_url("https://vimeo.com/123456"))
        self.assertTrue(helper.valid_media_url("https://example.org/media/item"))
        self.assertFalse(helper.valid_media_url("http://example.com/video/123"))
        self.assertFalse(helper.valid_media_url("https://localhost/video/123"))

    def test_tiktok_photo_url_is_detected(self):
        self.assertTrue(helper.is_tiktok_photo_url("https://www.tiktok.com/@user/photo/123"))
        self.assertFalse(helper.is_tiktok_photo_url("https://www.tiktok.com/@user/video/123"))

    def test_tiktok_carousel_images_are_extracted_from_embedded_json(self):
        html = (
            '<script type="application/json">'
            '{"itemInfo":{"itemStruct":{"imagePost":{"images":['
            '{"imageURL":{"url_list":["https://cdn.example/one.jpeg"]}},'
            '{"imageURL":{"url_list":["https://cdn.example/two.webp"]}}'
            ']}}}}'
            '</script>'
        )
        self.assertEqual(
            helper.extract_tiktok_photo_urls(html),
            ["https://cdn.example/one.jpeg", "https://cdn.example/two.webp"],
        )

    def test_tiktok_short_url_resolution_keeps_original_on_failure(self):
        short = "https://www.tiktok.com/t/example"
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(helper.resolve_tiktok_short_url(short), short)

    @unittest.skipUnless(helper.os.name == "nt", "Windows PATH test")
    def test_windows_tool_path_points_at_winget_links(self):
        import os
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(Path(tempfile.gettempdir())), "PATH": "base"}, clear=False):
            with mock.patch.object(helper.Path, "is_dir", return_value=True):
                helper.add_windows_tool_path()
                self.assertIn("Microsoft\\WinGet\\Links", os.environ["PATH"])

    def test_old_release_does_not_stage_an_update(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"tag_name": "0.0.1", "assets": []}).encode()

        output = io.StringIO()
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=Response()), contextlib.redirect_stdout(output):
            result = helper.check_for_update()
        self.assertNotIn("Update check skipped", output.getvalue())
        self.assertEqual(result["status"], "current")

    def test_private_repository_404_is_silent(self):
        error = helper.urllib.error.HTTPError("https://api.github.com/", 404, "Not Found", {}, None)
        output = io.StringIO()
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=error), contextlib.redirect_stdout(output):
            helper.check_for_update()
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
