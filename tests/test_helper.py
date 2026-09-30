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


class FakeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class FolderPickerTests(unittest.TestCase):
    @unittest.skipUnless(helper.os.name == "nt", "Windows picker test")
    def test_windows_picker_preserves_64_bit_pidl(self):
        import ctypes

        selected = str(Path(tempfile.gettempdir()).resolve())
        large_pidl = 0x1234567887654321
        freed = []
        uninitialized = []

        shell32 = type("Shell32", (), {})()
        shell32.SHBrowseForFolderW = FakeFunction(lambda _info: large_pidl)

        def get_path(pidl, buffer):
            self.assertEqual(pidl, large_pidl)
            buffer.value = selected
            return 1

        shell32.SHGetPathFromIDListW = FakeFunction(get_path)
        ole32 = type("Ole32", (), {})()
        ole32.CoInitializeEx = FakeFunction(lambda _reserved, _mode: 0)
        ole32.CoTaskMemFree = FakeFunction(lambda pidl: freed.append(pidl))
        ole32.CoUninitialize = FakeFunction(lambda: uninitialized.append(True))
        fake_loader = type("Loader", (), {"shell32": shell32, "ole32": ole32})()

        with mock.patch.object(ctypes, "windll", fake_loader):
            self.assertEqual(helper.choose_folder("mp3"), selected)
        self.assertEqual(freed, [large_pidl])
        self.assertEqual(uninitialized, [True])
        self.assertEqual(shell32.SHGetPathFromIDListW.argtypes[0], ctypes.c_void_p)
        self.assertEqual(ole32.CoTaskMemFree.argtypes, [ctypes.c_void_p])


class SharedHelperTests(unittest.TestCase):
    def test_download_process_stays_hidden_on_windows(self):
        job_id = "test-hidden-download"
        helper.JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Queued…"}
        try:
            with tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(helper.subprocess, "Popen") as popen:
                    popen.return_value.stdout = io.StringIO("")
                    popen.return_value.wait.return_value = 0
                    helper.run_download(job_id, "https://www.youtube.com/watch?v=test", "mp4", Path(directory))
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

    def test_supported_urls(self):
        self.assertTrue(helper.valid_media_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(helper.valid_media_url("https://youtu.be/abc"))
        self.assertTrue(helper.valid_media_url("https://www.tiktok.com/@user/video/123"))
        self.assertTrue(helper.valid_media_url("https://www.tiktok.com/t/ZTRC5xgJp"))
        self.assertTrue(helper.valid_media_url("https://www.tiktok.com/v/123"))
        self.assertTrue(helper.valid_media_url("https://vm.tiktok.com/ZMabc123/"))
        self.assertFalse(helper.valid_media_url("https://example.com/video/123"))

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
            helper.check_for_update()
        self.assertNotIn("Update check skipped", output.getvalue())

    def test_private_repository_404_is_silent(self):
        error = helper.urllib.error.HTTPError("https://api.github.com/", 404, "Not Found", {}, None)
        output = io.StringIO()
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=error), contextlib.redirect_stdout(output):
            helper.check_for_update()
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
