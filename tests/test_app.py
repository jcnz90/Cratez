"""Quick checks for the backend: python -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="cratez-test-")
os.environ["XDG_CONFIG_HOME"] = TMP          # keep settings / cookies / log out of the real app folder
os.environ["APPDATA"] = TMP
os.environ["HOME"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402


class Names(unittest.TestCase):
    def test_safe_never_climbs_out(self):
        for bad in ["..", ".", "", "  ", None, ". ."]:
            self.assertEqual(app.safe(bad), "Unknown")
        self.assertNotIn("/", app.safe("../../etc/passwd"))
        self.assertNotIn("\\", app.safe("..\\..\\x"))
        self.assertEqual(app.safe("DJ Name"), "DJ Name")


class Cookies(unittest.TestCase):
    def setUp(self):
        self.c = app.CookieFile(Path(tempfile.mkdtemp()) / "cookies.txt")

    def test_import_keeps_only_cratez_sites_and_httponly(self):
        text = "\n".join([
            "# Netscape HTTP Cookie File",
            "#HttpOnly_.bandcamp.com\tTRUE\t/\tTRUE\t0\tidentity\tabcdefghijklmnopqrstuvwxyz",
            ".soundcloud.com\tTRUE\t/\tTRUE\t0\toauth_token\t2-123-456-abc",
            ".mybank.com\tTRUE\t/\tTRUE\t0\tsession\tsecret",
            ".notsoundcloud.com\tTRUE\t/\tTRUE\t0\toauth_token\tnope",
        ])
        self.c.merge(text)
        saved = self.c.path.read_text()
        self.assertNotIn("mybank", saved)
        self.assertNotIn("notsoundcloud", saved)
        self.assertEqual(self.c.value("bandcamp.com", "identity"), "abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(self.c.value("soundcloud.com", "oauth_token"), "2-123-456-abc")

    def test_logout_drops_dotless_domain_too(self):
        self.c.merge("soundcloud.com\tFALSE\t/\tTRUE\t0\toauth_token\t2-1-2-x")
        self.c.set(".soundcloud.com", "oauth_token", "2-9-9-y")
        self.assertEqual(len(self.c.lines()), 1)
        self.c.drop(".soundcloud.com")
        self.assertFalse(self.c.exists())

    def test_no_other_sites_is_an_error(self):
        with self.assertRaises(ValueError):
            self.c.merge(".google.com\tTRUE\t/\tTRUE\t0\tSID\tx")


class SeratoCrates(unittest.TestCase):
    def test_blank_library_path_writes_nothing(self):
        s = app.Settings()
        s.update({"serato_dir": "", "serato_enabled": True})
        lib = app.SeratoLibrary(s)
        cwd = os.getcwd()
        work = tempfile.mkdtemp()
        os.chdir(work)
        try:
            crates = app.Serato.__new__(app.Serato)
            crates.settings, crates.library = s, lib
            self.assertIsNone(crates.crate_dir(Path.home() / "Music" / "x.mp3"))
            self.assertEqual(lib.databases(), [])
            self.assertFalse((Path(work) / "Subcrates").exists())
        finally:
            os.chdir(cwd)

    def test_crate_round_trip(self):
        lib_dir = Path(tempfile.mkdtemp()) / "_Serato_"
        lib_dir.mkdir()
        s = app.Settings()
        s.update({"serato_dir": str(lib_dir), "serato_enabled": True})
        crates = app.Serato.__new__(app.Serato)
        crates.settings, crates.lock = s, threading.Lock()
        sub = lib_dir / "Subcrates"
        sub.mkdir()
        self.assertEqual(crates.write_crate(sub, "House", ["Music/a.mp3", "Music/b.mp3"]), 2)
        self.assertEqual(crates.write_crate(sub, "House", ["music/A.mp3"]), 0)    # same file, any case
        _, tracks = app.Serato.parse((sub / "Cratez%%House.crate").read_bytes())
        self.assertEqual(tracks, ["Music/a.mp3", "Music/b.mp3"])


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.App()
        cls.srv = app.ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(cls.app))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, path, body=None, headers=None):
        h = {"X-Cratez": "1", "Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=h,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_state_only_resends_downloads_after_a_change(self):
        _, s = self.call("/api/state")
        self.assertIsInstance(s["downloads"], list)
        _, again = self.call(f"/api/state?since={s['downloads_rev']}")
        self.assertIsNone(again["downloads"])
        self.call("/api/clear", {})
        _, changed = self.call(f"/api/state?since={s['downloads_rev']}")
        self.assertIsInstance(changed["downloads"], list)

    def test_foreign_host_is_refused(self):
        self.assertEqual(self.call("/api/state", headers={"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.call("/api/settings", {"out_dir": "/tmp/x"}, {"Host": f"evil.example:{self.port}"})[0], 403)

    def test_posts_need_the_cratez_header(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/clear", data=b"{}")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 403)

    def get(self, path, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_preview_plays_a_finished_download_with_ranges(self):
        f = Path(tempfile.mkdtemp()) / "Track.mp3"
        f.write_bytes(bytes(range(256)) * 40)
        rec = {"id": "rec1", "track": {"key": "x", "url": "", "title": "T"}, "status": "done", "path": str(f)}
        self.app.downloads.records.append(rec)
        try:
            code, r = self.call("/api/preview", {"id": "rec1"})
            self.assertEqual(code, 200)
            self.assertTrue(r["seekable"])
            code, h, data = self.get(r["src"])
            self.assertEqual((code, len(data)), (200, 10240))
            code, h, data = self.get(r["src"], {"Range": "bytes=100-199"})
            self.assertEqual((code, data), (206, (bytes(range(256)) * 40)[100:200]))
            self.assertEqual(h["Content-Range"], "bytes 100-199/10240")
            self.assertEqual(self.get(r["src"], {"Host": f"evil.example:{self.port}"})[0], 403)
        finally:
            self.app.downloads.records.remove(rec)

    def test_preview_needs_a_token_and_a_known_site(self):
        self.assertEqual(self.get("/api/preview/made-up")[0], 404)
        code, r = self.call("/api/preview", {"track": {"url": "http://127.0.0.1:22/"}})
        self.assertEqual(code, 400)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/preview", data=b'{"id":"rec1"}')
        with self.assertRaises(urllib.error.HTTPError) as e:     # no X-Cratez: no token
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 403)

    def test_byte_ranges(self):
        br = app.Previews.byte_range
        self.assertEqual(br("bytes=0-", 100), (0, 99))
        self.assertEqual(br("bytes=-10", 100), (90, 99))
        self.assertEqual(br("bytes=50-500", 100), (50, 99))
        self.assertIsNone(br("bytes=200-", 100))
        self.assertIsNone(br("items=1-2", 100))


if __name__ == "__main__":
    unittest.main()
