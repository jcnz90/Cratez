#!/usr/bin/env python3
"""
Cratez - collects edits, blends, bootlegs, remixes & packs from SoundCloud, Bandcamp and
hearthis.at into genre folders (and Serato crates). Backend + launcher for the desktop app.

    python app.py              run (opens the app window)
    python app.py --no-window  run headless at http://127.0.0.1:<port>/ (prints the URL)
    python app.py --port 8765  fixed port

Build with build.bat (Windows) or build.command (macOS). Settings, cookies, download
history and the log live in %APPDATA%\\Cratez (Windows) or ~/Library/Application Support/Cratez.

What it downloads
  SoundCloud   the uploader's original file when "Enable downloads" is on; otherwise the
               stream (Settings > "Save the stream instead")
  hearthis.at  the uploader's download file when downloads are on; stream otherwise (same setting)
  Bandcamp     free / name-your-price-at-zero downloads, plus everything in your own
               purchases when you sign in (WAV/FLAC/320 as you choose)
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import os
import platform
import random
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlencode

try:
    import yt_dlp
    from yt_dlp.networking import Request
    from yt_dlp.utils import ExtractorError, parse_iso8601, sanitize_filename
except ImportError:  # pragma: no cover
    sys.exit("yt-dlp is required:  pip install -U yt-dlp")

APP_NAME = "Cratez"
VERSION = "1.1.0"
FROZEN = getattr(sys, "frozen", False)
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
UI_DIR = BASE / "ui"
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

DEFAULT_KEYWORDS = ["edit", "bootleg", "vip", "remix", "pack", "blend", "flip", "mashup", "rework", "refix"]
DEFAULT_SEARCHES = ["edit", "remix", "bootleg", "blend", "flip"]
DEFAULT_GENRES = [
    ("House", ["house"]), ("Tech House", ["tech house"]), ("Afro House", ["afro house"]),
    ("Amapiano", ["amapiano"]), ("UK Garage", ["uk garage"]), ("Drum & Bass", ["drum & bass"]),
    ("Hip-Hop", ["hip hop"]), ("RnB", ["r&b"]), ("Dancehall & Afrobeats", ["dancehall", "afrobeats"]),
    ("Disco & Funk", ["disco", "funk"]), ("Techno", ["techno"]),
]
SC_API = "https://api-v2.soundcloud.com/"
HT_API = "https://api-v2.hearthis.at/"
BC_SEARCH = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
BC_SUMMARY = "https://bandcamp.com/api/fan/2/collection_summary"
BC_COLLECTION = "https://bandcamp.com/api/fancollection/1/collection_items"
BC_LOSSLESS = "flac/wav/aiff-lossless/mp3-320/mp3-v0/aac-hi/vorbis"      # never the mp3-128 preview
BC_MP3 = "mp3-320/mp3-v0/flac/wav/aiff-lossless/aac-hi/vorbis"
BC_PREF = {"lossless": ["flac", "wav", "aiff-lossless", "mp3-320", "mp3-v0", "aac-hi", "vorbis", "alac"],
           "mp3-320": ["mp3-320", "mp3-v0", "flac", "wav", "aiff-lossless", "aac-hi", "vorbis", "alac"]}
SC_WINDOWS = [(1, "last_day"), (7, "last_week"), (31, "last_month"), (366, "last_year")]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PLATFORMS = {"soundcloud": "SoundCloud", "bandcamp": "Bandcamp", "hearthis": "hearthis.at"}
LAYOUTS = {"genre/uploader": "Genre / Uploader", "genre": "Genre", "uploader": "Uploader", "flat": "Everything in one folder"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".opus", ".alac"}
EMBEDDABLE = {"mp3", "flac", "m4a", "mp4", "ogg", "opus"}

# ------------------------------------------------------------------------------ app data

def data_dir() -> Path:
    if IS_WIN:
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif IS_MAC:
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    d = root / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA = data_dir()
LOG_FILE = DATA / "cratez.log"
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cratez")


class YDLLogger:
    """Route yt-dlp's chatter to the log file (there is no console in the windowed app)."""
    def debug(self, msg):
        if not msg.startswith("[debug] "):
            log.debug(msg)

    def info(self, msg):
        log.info(msg)

    def warning(self, msg):
        if "impersonat" not in msg:
            log.warning(msg)

    def error(self, msg):
        log.error(msg)


def safe(name: str | None) -> str:
    return sanitize_filename((name or "").strip(), restricted=False).replace("%%", "-") or "Unknown"


def window_for(days: int) -> str | None:
    return next((w for d, w in SC_WINDOWS if 0 < days <= d), None)


def default_serato_dir() -> Path | None:
    for cand in [Path.home() / "Music" / "_Serato_"]:
        if cand.exists():
            return cand
    return None


# ------------------------------------------------------------------------------ settings

class Settings:
    ALLOWED = {"out_dir", "mode", "keywords", "match_keywords", "days", "search_count", "platforms", "genres",
               "sc_user", "bc_user", "tags", "cover_art", "convert_streams", "bc_quality", "layout", "append_id",
               "parallel", "min_seconds", "max_seconds", "serato_enabled", "serato_dir", "serato_crate"}

    def __init__(self):
        self.path = DATA / "settings.json"
        self.lock = threading.Lock()
        self.data = self.defaults()
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update({k: v for k, v in saved.items() if k in self.ALLOWED})
            except Exception as e:
                log.warning("settings unreadable (%s), using defaults", e)

    @staticmethod
    def defaults() -> dict:
        serato = default_serato_dir()
        return {
            "out_dir": str(Path.home() / "Music" / APP_NAME),
            "mode": "original_or_stream",      # or "original_only"
            "keywords": list(DEFAULT_KEYWORDS), "match_keywords": True,
            "days": 30, "search_count": 100,
            "platforms": {"soundcloud": True, "bandcamp": True, "hearthis": True},
            "genres": [{"name": n, "tags": t, "searches": list(DEFAULT_SEARCHES)} for n, t in DEFAULT_GENRES],
            "sc_user": None, "bc_user": None,
            "tags": True, "cover_art": True, "convert_streams": False, "bc_quality": "lossless",
            "layout": "genre/uploader", "append_id": True, "parallel": 1,
            "min_seconds": 45, "max_seconds": 0,
            "serato_enabled": serato is not None, "serato_dir": str(serato) if serato else "", "serato_crate": APP_NAME,
        }

    def get(self, key):
        with self.lock:
            return self.data[key]

    def update(self, changes: dict):
        with self.lock:
            for k, v in changes.items():
                if k not in self.ALLOWED:
                    continue
                if k == "keywords":
                    v = [s.strip().lower() for s in (v if isinstance(v, list) else str(v).split(",")) if s.strip()]
                elif k == "genres":
                    v = [{"name": str(g.get("name", "")).strip() or "Untitled",
                          "tags": [str(s).strip() for s in g.get("tags", []) if str(s).strip()],
                          "searches": [str(s).strip() for s in g.get("searches", []) if str(s).strip()]} for g in v]
                elif k in ("days", "search_count", "min_seconds", "max_seconds"):
                    v = max(0, int(v))
                elif k == "parallel":
                    v = min(4, max(1, int(v)))
                elif k in ("tags", "cover_art", "convert_streams", "append_id", "serato_enabled", "match_keywords"):
                    v = bool(v)
                elif k == "layout" and v not in LAYOUTS:
                    v = "genre/uploader"
                elif k == "bc_quality" and v not in BC_PREF:
                    v = "lossless"
                elif k == "serato_crate":
                    v = safe(str(v)) if str(v).strip() else APP_NAME
                self.data[k] = v
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def reset(self):
        with self.lock:
            keep = {k: self.data.get(k) for k in ("sc_user", "bc_user")}
            self.data = self.defaults()
            self.data.update(keep)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def public(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data))

    def genre(self, name: str) -> dict | None:
        return next((g for g in self.get("genres") if g["name"].lower() == (name or "").lower()), None)


# ------------------------------------------------------------------------------ cookies

class CookieFile:
    """One Netscape cookies.txt holding the SoundCloud oauth_token and the Bandcamp identity cookie."""

    def __init__(self, path: Path):
        self.path = path

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return [l for l in self.path.read_text(encoding="utf-8", errors="replace").splitlines()
                if l.strip() and not l.startswith("#")]

    def write(self, lines: list[str]):
        if lines:
            self.path.write_text("# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n", encoding="utf-8")
        else:
            self.path.unlink(missing_ok=True)

    def set(self, domain: str, name: str, value: str):
        value = value.strip().strip('"')
        if re.search(r"\s", value):             # pasted decoded: put it back into cookie form
            value = quote(value, safe="")
        expiry = int(time.time()) + 10 * 365 * 86400
        kept = [l for l in self.lines() if not (domain in l.split("\t")[0] and l.split("\t")[5:6] == [name])]
        kept.append(f"{domain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}")
        self.write(kept)

    def drop(self, domain: str):
        self.write([l for l in self.lines() if domain not in l.split("\t")[0]])

    def merge(self, text: str):
        new = [l for l in text.splitlines() if l.strip() and not l.startswith("#") and len(l.split("\t")) >= 7]
        if not new:
            raise ValueError("That doesn't look like a Netscape cookies.txt")
        domains = {l.split("\t")[0] for l in new}
        kept = [l for l in self.lines() if l.split("\t")[0] not in domains]
        self.write(kept + new)

    def has(self, domain: str, name: str) -> bool:
        return any(domain in l.split("\t")[0] and l.split("\t")[5:6] == [name] for l in self.lines())

    def exists(self) -> bool:
        return self.path.exists()


# ------------------------------------------------------------------------------ platforms

def sc_track(t: dict) -> dict:
    user = t.get("user") or {}
    art = t.get("artwork_url") or user.get("avatar_url") or ""
    return {
        "key": f"soundcloud:{t.get('id')}", "platform": "soundcloud", "id": t.get("id"),
        "title": t.get("title") or "", "uploader": user.get("username") or "",
        "url": t.get("permalink_url") or "", "artwork": art.replace("-large.", "-t300x300."),
        "created": (t.get("created_at") or "")[:10], "ts": parse_iso8601(t.get("created_at") or "") or 0,
        "duration": (t.get("duration") or 0) // 1000, "tag": t.get("genre") or "",
        "downloadable": bool(t.get("downloadable") and t.get("has_downloads_left", True)),
    }


def ht_track(t: dict) -> dict:
    user = t.get("user") or {}
    created = (t.get("created_at") or "").replace(" ", "T")
    return {
        "key": f"hearthis:{t.get('id')}", "platform": "hearthis", "id": t.get("id"),
        "title": t.get("title") or "", "uploader": user.get("username") or "",
        "url": t.get("permalink_url") or "", "artwork": t.get("artwork_url") or user.get("avatar_url") or "",
        "created": created[:10], "ts": parse_iso8601(created + "Z") if created else 0,
        "duration": int(t.get("duration") or 0), "tag": t.get("genre") or "",
        "downloadable": str(t.get("downloadable")) == "1" and bool(t.get("download_url")),
        "download_url": t.get("download_url") or "", "download_filename": t.get("download_filename") or "",
    }


def bc_track(r: dict) -> dict:
    return {
        "key": f"bandcamp:{r.get('id')}", "platform": "bandcamp", "id": r.get("id"),
        "title": r.get("name") or "", "uploader": r.get("band_name") or "",
        "url": r.get("item_url_path") or "", "artwork": (r.get("img") or "").replace("_3.jpg", "_7.jpg"),
        "created": "", "ts": 0, "duration": 0, "tag": r.get("album_name") or "",
        "downloadable": None,   # only known once the track page is opened
    }


def bc_purchase(item: dict, redownload: dict) -> dict | None:
    key = f"{item.get('sale_item_type')}{item.get('sale_item_id')}"
    page = redownload.get(key)
    if not page:
        return None
    art = item.get("item_art_url") or ((item.get("item_art") or {}).get("url")) or ""
    purchased = item.get("purchased") or ""
    return {
        "key": f"bandcamp-purchase:{key}", "platform": "bandcamp", "id": item.get("sale_item_id"),
        "title": item.get("item_title") or "", "uploader": item.get("band_name") or "",
        "url": item.get("item_url") or "", "artwork": art.replace("_9.jpg", "_7.jpg").replace("_2.jpg", "_7.jpg"),
        "created": purchased[:11].strip(), "ts": 0, "duration": 0,
        "tag": "album" if item.get("item_type") == "album" else "track",
        "downloadable": True, "purchase": True, "download_page": page, "album": item.get("item_type") == "album",
    }


class Sites:
    """All network access, through yt-dlp's networking stack (so cookies/login apply)."""

    def __init__(self, cookies: CookieFile):
        self.cookies = cookies
        self.lock = threading.Lock()
        self._ydl = None
        self._sc = None

    def reset(self):
        with self.lock:
            if self._sc is not None:   # yt-dlp keeps the OAuth header on the extractor class
                self._sc._HEADERS.pop("Authorization", None)
            self._ydl = None
            self._sc = None

    def ydl_opts(self) -> dict:
        opts = {"quiet": True, "no_warnings": True, "logger": YDLLogger()}
        if self.cookies.exists():
            opts["cookiefile"] = str(self.cookies.path)
        return opts

    def ydl(self):
        with self.lock:
            if self._ydl is None:
                self._ydl = yt_dlp.YoutubeDL({**self.ydl_opts(), "extract_flat": "in_playlist"})
            return self._ydl

    def sc(self):
        ydl = self.ydl()
        with self.lock:
            if self._sc is None:
                ie = ydl.get_info_extractor("SoundcloudSearch")
                ie.initialize()
                self._sc = ie
            return self._sc

    def sc_api(self, path: str, query: dict | None = None, note: str = "api"):
        ie = self.sc()
        url = path if path.startswith("http") else SC_API + path
        return ie._call_api(url, None, note=note, query=query or {}, headers=ie._HEADERS)

    def open(self, url: str, data: bytes | None = None, headers: dict | None = None):
        h = {"User-Agent": UA}
        if data is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        return self.ydl().urlopen(Request(url, data=data, headers=h))

    def get_json(self, url: str, data: bytes | None = None, headers: dict | None = None):
        with self.open(url, data, {"Accept": "application/json", **(headers or {})}) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def get_text(self, url: str) -> str:
        with self.open(url) as r:
            return r.read().decode("utf-8", "replace")

    # --- SoundCloud
    def sc_me(self) -> dict | None:
        me = self.sc_api("me", note="checking login")
        if not me or not me.get("id"):
            return None
        return {"id": me["id"], "username": me.get("username"), "permalink": me.get("permalink"),
                "avatar": me.get("avatar_url") or ""}

    def sc_search(self, q: str, days: int, count: int, tag: str | None = None) -> list[dict]:
        query = {"q": q, "limit": min(50, max(1, count)), "offset": 0, "linked_partitioning": 1}
        if window_for(days):
            query["filter.created_at"] = window_for(days)
        if tag:
            query["filter.genre_or_tag"] = tag
        url, out = SC_API + "search/tracks", []
        while url and len(out) < count:
            data = self.sc_api(url, query, note=f"SoundCloud search {q!r}")
            query = {}
            items = (data or {}).get("collection") or []
            if not items:
                break
            out += [sc_track(t) for t in items if t.get("permalink_url")]
            url = data.get("next_href")
        return out[:count]

    def sc_likes(self, user_id, limit: int = 1000) -> list[dict]:
        url, query, out = SC_API + f"users/{user_id}/likes", {"limit": 50, "offset": 0, "linked_partitioning": 1}, []
        while url and len(out) < limit:
            data = self.sc_api(url, query, note="loading likes")
            query = {}
            for item in (data or {}).get("collection") or []:
                t = item.get("track")
                if t and t.get("permalink_url"):
                    out.append(sc_track(t))
            url = data.get("next_href")
        return out

    def sc_resolve(self, url: str) -> list[dict]:
        obj = self.sc_api("resolve", {"url": url}, note="resolving link")
        kind = obj.get("kind")
        if kind == "track":
            return [sc_track(obj)]
        if kind == "playlist":
            tracks = obj.get("tracks") or []
            stubs = [str(t["id"]) for t in tracks if not t.get("permalink_url")]
            full = [t for t in tracks if t.get("permalink_url")]
            for i in range(0, len(stubs), 50):
                full += self.sc_api("tracks", {"ids": ",".join(stubs[i:i + 50])}, note="loading set") or []
            return [sc_track(t) for t in full if t.get("permalink_url")]
        if kind == "user":
            if url.rstrip("/").endswith("/likes"):
                return self.sc_likes(obj["id"], 500)
            u, query, out = SC_API + f"users/{obj['id']}/tracks", {"limit": 50, "linked_partitioning": 1}, []
            while u and len(out) < 500:
                data = self.sc_api(u, query, note="loading tracks")
                query = {}
                out += [sc_track(t) for t in (data or {}).get("collection") or [] if t.get("permalink_url")]
                u = data.get("next_href")
            return out
        return []

    # --- hearthis.at
    def ht_search(self, q: str, count: int) -> list[dict]:
        out, page = [], 1
        while len(out) < count and page <= 5:
            items = self.get_json(f"{HT_API}search/?t={quote(q)}&page={page}&count=50")
            if not isinstance(items, list) or not items:
                break
            out += [ht_track(t) for t in items if t.get("permalink_url")]
            page += 1
        return out[:count]

    def ht_resolve(self, url: str) -> list[dict]:
        m = re.match(r"https?://(?:www\.)?hearthis\.at/([^/?#]+)/?([^/?#]+)?", url)
        if not m:
            return []
        user, track = m.group(1), m.group(2)
        if track:
            t = self.get_json(f"{HT_API}{user}/{track}/")
            return [ht_track(t)] if isinstance(t, dict) and t.get("permalink_url") else []
        out, page = [], 1
        while page <= 10:
            items = self.get_json(f"{HT_API}{user}/?type=tracks&page={page}&count=50")
            if not isinstance(items, list) or not items:
                break
            out += [ht_track(t) for t in items if t.get("permalink_url")]
            page += 1
        return out

    # --- Bandcamp
    def bc_search(self, q: str, count: int) -> list[dict]:
        body = json.dumps({"search_text": q, "search_filter": "t", "full_page": True, "fan_id": None}).encode()
        data = self.get_json(BC_SEARCH, data=body)
        results = ((data or {}).get("auto") or {}).get("results") or []
        return [bc_track(r) for r in results if r.get("type") == "t" and r.get("item_url_path")][:count]

    def bc_resolve(self, url: str) -> list[dict]:
        info = self.ydl().extract_info(url, download=False)
        if not info:
            return []
        if info.get("_type") in ("playlist", "multi_video"):
            out = []
            for e in info.get("entries") or []:
                if not e:
                    continue
                if e.get("_type") == "playlist":   # artist page -> albums
                    out += self.bc_resolve(e.get("url") or e.get("webpage_url"))
                    continue
                out.append({
                    "key": f"bandcamp:{e.get('id') or e.get('url')}", "platform": "bandcamp", "id": e.get("id"),
                    "title": e.get("title") or "", "uploader": e.get("uploader") or info.get("uploader") or "",
                    "url": e.get("url") or e.get("webpage_url") or "",
                    "artwork": e.get("thumbnail") or info.get("thumbnail") or "",
                    "created": "", "ts": 0, "duration": int(e.get("duration") or 0),
                    "tag": info.get("title") or "", "downloadable": None,
                })
            return out
        return [{
            "key": f"bandcamp:{info.get('id')}", "platform": "bandcamp", "id": info.get("id"),
            "title": info.get("track") or info.get("title") or "", "uploader": info.get("uploader") or "",
            "url": info.get("webpage_url") or url, "artwork": info.get("thumbnail") or "",
            "created": "", "ts": 0, "duration": int(info.get("duration") or 0), "tag": info.get("album") or "",
            "downloadable": any(f.get("format_id") != "mp3-128" for f in info.get("formats") or []),
        }]

    def bc_me(self) -> dict | None:
        data = self.get_json(BC_SUMMARY)
        fan = data.get("fan_id") if isinstance(data, dict) else None
        if not fan:
            return None
        s = data.get("collection_summary") or {}
        return {"id": fan, "username": s.get("username") or str(fan), "url": s.get("url") or "", "avatar": ""}

    def bc_purchases(self, fan_id, limit: int = 2000) -> list[dict]:
        token, out = f"{int(time.time())}::a::", []
        while token and len(out) < limit:
            body = json.dumps({"fan_id": fan_id, "older_than_token": token, "count": 100}).encode()
            data = self.get_json(BC_COLLECTION, data=body)
            redownload = data.get("redownload_urls") or {}
            items = data.get("items") or []
            if not items:
                break
            out += [p for p in (bc_purchase(i, redownload) for i in items) if p]
            token = data.get("last_token") if data.get("more_available") else None
        return out

    def bc_download_link(self, page_url: str, quality: str) -> tuple[str, str]:
        """Turn a Bandcamp download page into a direct file URL: (format_id, url)."""
        page = self.get_text(page_url)
        m = re.search(r'data-blob="([^"]+)"', page)
        if not m:
            raise ValueError("Bandcamp didn't show the download page - sign in again (Settings)")
        blob = json.loads(html.unescape(m.group(1)))
        item = next((x for k in ("digital_items", "download_items") for x in (blob.get(k) or [])[:1]), None)
        downloads = (item or {}).get("downloads") or {}
        for fmt in BC_PREF[quality]:
            d = downloads.get(fmt)
            if not d or not d.get("url"):
                continue
            stat = d["url"].replace("/download/", "/statdownload/")
            stat += ("&" if "?" in stat else "?") + urlencode({".rand": int(time.time() * 1000 * random.random()), ".vrs": 1})
            txt = self.get_text(stat)
            try:
                info = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
            except ValueError:
                continue
            url = info.get("retry_url") or info.get("download_url")
            if url:
                return fmt, url
        raise ValueError("No download formats offered for this purchase")


def platform_of(url: str) -> str | None:
    if re.match(r"https?://(?:[\w-]+\.)?soundcloud\.com/", url):
        return "soundcloud"
    if re.match(r"https?://[\w-]+\.bandcamp\.com/", url):
        return "bandcamp"
    if re.match(r"https?://(?:www\.)?hearthis\.at/", url):
        return "hearthis"
    return None


# ------------------------------------------------------------------------------ Serato crates

class Serato:
    """Writes Serato DJ subcrates (<crate>%%<Genre>.crate) that point at downloaded files.
    Format: 'vrsn' + UTF-16BE version, then tag/len/payload chunks; tracks are 'otrk' > 'ptrk'
    with the path relative to the drive root, forward slashes, no leading slash."""

    VERSION = "1.0/Serato ScratchLive Crate"
    COLUMNS = ["song", "artist", "album", "length", "bpm", "key", "added"]

    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.Lock()

    @staticmethod
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return tag + struct.pack(">I", len(payload)) + payload

    @staticmethod
    def u16(s: str) -> bytes:
        return s.encode("utf-16-be")

    def header(self) -> bytes:
        out = self.chunk(b"vrsn", self.u16(self.VERSION))
        out += self.chunk(b"osrt", self.chunk(b"tvcn", self.u16("song")) + self.chunk(b"brev", b"\x00"))
        for c in self.COLUMNS:
            out += self.chunk(b"ovct", self.chunk(b"tvcn", self.u16(c)) + self.chunk(b"tvcw", self.u16("0")))
        return out

    @staticmethod
    def parse(data: bytes) -> tuple[list[bytes], list[str]]:
        """Returns (non-track chunks as raw bytes, track paths)."""
        other, tracks, pos = [], [], 0
        while pos + 8 <= len(data):
            tag, ln = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
            payload = data[pos + 8:pos + 8 + ln]
            if tag == b"otrk":
                p = 0
                while p + 8 <= len(payload):
                    t2, l2 = payload[p:p + 4], struct.unpack(">I", payload[p + 4:p + 8])[0]
                    if t2 == b"ptrk":
                        tracks.append(payload[p + 8:p + 8 + l2].decode("utf-16-be", "replace"))
                    p += 8 + l2
            else:
                other.append(data[pos:pos + 8 + ln])
            pos += 8 + ln
        return other, tracks

    def root_and_rel(self, path: Path) -> tuple[Path, str]:
        p = path.resolve()
        if IS_WIN:
            root = Path(p.anchor)
            rel = p.relative_to(root).as_posix()
        elif IS_MAC and len(p.parts) > 3 and p.parts[1] == "Volumes":
            root = Path(*p.parts[:3])
            rel = p.relative_to(root).as_posix()
        else:
            root, rel = Path("/"), p.relative_to("/").as_posix()
        return root, rel

    def crate_dir(self, path: Path) -> Path | None:
        """The _Serato_/Subcrates folder that owns a file: the configured library for the boot
        drive, <drive>/_Serato_ for external drives (that's where Serato keeps them)."""
        root, _ = self.root_and_rel(path)
        home_root = self.root_and_rel(Path.home())[0]
        if root == home_root:
            lib = Path(self.settings.get("serato_dir") or "")
            if not lib.is_dir():
                return None
        else:
            lib = root / "_Serato_"
            if not lib.is_dir():
                lib.mkdir(parents=True, exist_ok=True)
        sub = lib / "Subcrates"
        sub.mkdir(exist_ok=True)
        return sub

    def add(self, files: list[Path], genre: str) -> int:
        if not self.settings.get("serato_enabled") or not files:
            return 0
        crate = self.settings.get("serato_crate") or APP_NAME
        added = 0
        with self.lock:
            by_dir: dict[Path, list[str]] = {}
            for f in files:
                sub = self.crate_dir(f)
                if sub is None:
                    continue
                by_dir.setdefault(sub, []).append(self.root_and_rel(f)[1])
            for sub, rels in by_dir.items():
                parent = sub / f"{crate}.crate"
                if not parent.exists():
                    parent.write_bytes(self.header())
                target = sub / f"{crate}%%{safe(genre or 'Ungrouped')}.crate"
                if target.exists():
                    other, tracks = self.parse(target.read_bytes())
                    if not other:
                        other = [self.header()]
                else:
                    other, tracks = [self.header()], []
                have = {t.lower() for t in tracks}
                new = [r for r in rels if r.lower() not in have]
                added += len(new)
                data = b"".join(other) + b"".join(self.chunk(b"otrk", self.chunk(b"ptrk", self.u16(t))) for t in tracks + new)
                target.write_bytes(data)
        return added


# ------------------------------------------------------------------------------ downloads

class Downloads:
    def __init__(self, settings: Settings, sites: Sites, serato: Serato):
        self.settings, self.sites, self.serato = settings, sites, serato
        self.path = DATA / "downloads.json"
        self.lock = threading.Lock()
        self.records: list[dict] = []
        self.running: set[str] = set()
        self.wake = threading.Event()
        self.ffmpeg = shutil.which("ffmpeg")
        if self.path.exists():
            try:
                self.records = json.loads(self.path.read_text(encoding="utf-8"))
                for r in self.records:   # anything cut off last time goes back in the queue
                    if r["status"] in ("downloading", "queued"):
                        r.update(status="queued", pct=0)
            except Exception as e:
                log.warning("download history unreadable: %s", e)
        threading.Thread(target=self.dispatcher, name="dispatcher", daemon=True).start()

    def save(self):
        with self.lock:
            self.path.write_text(json.dumps(self.records), encoding="utf-8")

    def snapshot(self) -> list[dict]:
        with self.lock:
            return json.loads(json.dumps(self.records))

    def active(self) -> bool:
        with self.lock:
            return any(r["status"] in ("queued", "downloading") for r in self.records)

    def add(self, tracks: list[dict], genre: str) -> int:
        added = 0
        with self.lock:
            have = {r["track"]["key"] for r in self.records if r["status"] != "failed"}
            for t in tracks:
                if t.get("key") in have or not (t.get("url") or t.get("download_page")):
                    continue
                self.records.insert(0, {"id": uuid.uuid4().hex, "track": t, "genre": genre or "", "status": "queued",
                                        "pct": 0, "path": None, "error": None, "quality": None,
                                        "added": time.time(), "finished": None})
                have.add(t["key"])
                added += 1
        self.save()
        self.wake.set()
        return added

    def find(self, rec_id: str) -> dict | None:
        return next((r for r in self.records if r["id"] == rec_id), None)

    def remove(self, rec_id: str):
        with self.lock:
            self.records = [r for r in self.records if r["id"] != rec_id]
        self.save()

    def retry(self, rec_id: str):
        with self.lock:
            r = self.find(rec_id)
            if r:
                r.update(status="queued", pct=0, error=None, finished=None)
        self.save()
        self.wake.set()

    def clear_finished(self):
        with self.lock:
            self.records = [r for r in self.records if r["status"] in ("queued", "downloading")]
        self.save()

    def clear_all(self):
        with self.lock:
            self.records = [r for r in self.records if r["status"] == "downloading"]
        self.save()

    def done_files(self) -> list[tuple[Path, str]]:
        with self.lock:
            return [(Path(r["path"]), r["genre"]) for r in self.records if r["status"] == "done" and r.get("path")]

    # --- workers
    def dispatcher(self):
        while True:
            with self.lock:
                free = self.settings.get("parallel") - len(self.running)
                todo = [r for r in reversed(self.records) if r["status"] == "queued"][:max(0, free)]
                for r in todo:
                    r["status"] = "downloading"
                    self.running.add(r["id"])
            for r in todo:
                threading.Thread(target=self.run_one, args=(r,), daemon=True).start()
            self.wake.wait(timeout=2)
            self.wake.clear()

    def run_one(self, rec: dict):
        try:
            self.download(rec)
        except Exception as e:
            log.exception("download failed: %s", rec["track"].get("title"))
            self.fail(rec, e)
        finally:
            with self.lock:
                self.running.discard(rec["id"])
            self.save()
            time.sleep(1)
            self.wake.set()

    def set(self, rec, **kw):
        with self.lock:
            rec.update(kw)

    def fail(self, rec, err: Exception):
        msg = str(err)
        t = rec["track"]
        if "Requested format is not available" in msg:
            if t["platform"] == "bandcamp":
                self.set(rec, status="paid", error="Not a free download - open it on Bandcamp to buy", finished=time.time())
            else:
                self.set(rec, status="unavailable", error="Uploader hasn't enabled downloads (turn on "
                         "'Save the stream instead' in Settings to save the stream)", finished=time.time())
        else:
            msg = re.sub(r"^ERROR:\s*", "", msg.splitlines()[0] if msg else "download failed")
            self.set(rec, status="failed", error=msg[:300], finished=time.time())

    def folder_for(self, rec: dict) -> Path:
        t = rec["track"]
        out = Path(self.settings.get("out_dir")).expanduser()
        layout = self.settings.get("layout")
        parts = []
        if "genre" in layout:
            parts.append(safe(rec["genre"] or "Ungrouped"))
        if "uploader" in layout:
            parts.append(safe(t.get("uploader")))
        folder = out.joinpath(*parts)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def format_for(self, t: dict) -> str:
        mode = self.settings.get("mode")
        if t["platform"] == "bandcamp":
            return BC_LOSSLESS if self.settings.get("bc_quality") == "lossless" else BC_MP3
        if t["platform"] == "soundcloud":
            if mode == "original_only":
                return "download"
            return "download/bestaudio/best" if self.ffmpeg else "download/bestaudio[protocol!*=m3u8]/bestaudio/best"
        return "bestaudio/best"   # hearthis stream (the original file is fetched directly)

    def finish(self, rec: dict, path: str | None, quality: str, files: list[Path] | None = None):
        self.set(rec, status="done", pct=100, path=path, quality=quality, finished=time.time(), error=None)
        try:
            n = self.serato.add(files or ([Path(path)] if path else []), rec["genre"])
            if n:
                log.info("Serato: %d track(s) added to crate %s", n, rec["genre"])
        except Exception:
            log.exception("Serato crate update failed")

    def download(self, rec: dict):
        t = rec["track"]
        folder = self.folder_for(rec)
        if t.get("purchase"):
            return self.purchase(rec, folder)
        if t["platform"] == "hearthis":
            if t.get("downloadable") and t.get("download_url"):
                return self.direct(rec, folder)
            if self.settings.get("mode") == "original_only":
                raise yt_dlp.utils.DownloadError("Requested format is not available")

        def hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total:
                    self.set(rec, pct=round(100 * (d.get("downloaded_bytes") or 0) / total, 1))
            elif d.get("status") == "finished":
                self.set(rec, pct=100)

        name = "%(title).150B" + (" [%(id)s]" if self.settings.get("append_id") else "") + ".%(ext)s"
        base = {
            **self.sites.ydl_opts(), "format": self.format_for(t), "outtmpl": str(folder / name),
            "noprogress": True, "noplaylist": True, "retries": 5, "fragment_retries": 10,
            "sleep_interval_requests": 0.5, "windowsfilenames": IS_WIN,
        }
        # pass 1: find out what we're getting; pass 2: download with the matching post-processing
        with yt_dlp.YoutubeDL(base) as probe:
            info = probe.extract_info(t["url"], download=False)
        if not info:
            raise yt_dlp.utils.DownloadError("nothing found at that link")
        fid = info.get("format_id") or ""
        is_stream = fid != "download" and t["platform"] != "bandcamp"
        if rec["genre"]:
            info["genre"] = rec["genre"]          # ends up in the file's genre tag
        pps, ext = [], info.get("ext") or ""
        if self.ffmpeg:
            if is_stream and self.settings.get("convert_streams"):
                pps.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"})
                ext = "mp3"
            if self.settings.get("tags"):
                pps.append({"key": "FFmpegMetadata", "add_metadata": True})
            if self.settings.get("cover_art") and ext in EMBEDDABLE and info.get("thumbnail"):
                base["writethumbnail"] = True
                pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
        with yt_dlp.YoutubeDL({**base, "postprocessors": pps, "progress_hooks": [hook]}) as ydl:
            info = ydl.process_ie_result(info, download=True)
        path = None
        for d in (info or {}).get("requested_downloads") or []:
            path = d.get("filepath") or d.get("filename")
        quality = ("original" if fid == "download" else fid if t["platform"] == "bandcamp"
                   else "stream " + fid.replace("hls_", "").replace("_", " ") + (" → mp3 320" if ext == "mp3" and is_stream and self.settings.get("convert_streams") else ""))
        self.finish(rec, path, quality)

    def fetch(self, rec: dict, url: str, target: Path):
        tmp = target.with_name(target.name + ".part")
        with self.sites.open(url) as r:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        self.set(rec, pct=round(100 * got / total, 1))
            disp = r.headers.get("Content-Disposition") or ""
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disp)
        tmp.replace(target)
        return html.unescape(m.group(1)) if m else None

    def tag_file(self, path: Path, rec: dict):
        """Title / artist / genre (+ cover) for files we fetched ourselves, via ffmpeg."""
        if not self.ffmpeg or not self.settings.get("tags") or path.suffix.lower() not in AUDIO_EXT:
            return
        t = rec["track"]
        out = path.with_name(path.stem + ".tagged" + path.suffix)
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(path)]
        cover = None
        if self.settings.get("cover_art") and t.get("artwork") and path.suffix.lower() in (".mp3", ".flac", ".m4a"):
            try:
                cover = path.with_suffix(".cover.jpg")
                with self.sites.open(t["artwork"]) as r, open(cover, "wb") as fh:
                    fh.write(r.read())
                cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic",
                        "-metadata:s:v", "title=Album cover"]
            except Exception:
                cover = None
                cmd += ["-map", "0:a"]
        else:
            cmd += ["-map", "0:a"]
        cmd += ["-c:a", "copy", "-id3v2_version", "3", "-metadata", f"title={t.get('title') or path.stem}",
                "-metadata", f"artist={t.get('uploader') or ''}", "-metadata", f"genre={rec['genre'] or ''}", str(out)]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
            out.replace(path)
        except Exception as e:
            log.warning("tagging failed for %s: %s", path.name, e)
            out.unlink(missing_ok=True)
        finally:
            if cover:
                cover.unlink(missing_ok=True)

    def direct(self, rec: dict, folder: Path):
        """hearthis.at hands out the uploader's file at a plain URL - fetch it ourselves."""
        t = rec["track"]
        name = re.sub(r"\s*\(hearthis\.at\)", "", t.get("download_filename") or f"{t['title']}.mp3")
        stem, ext = os.path.splitext(safe(name))
        target = folder / f"{stem}{' [' + str(t['id']) + ']' if self.settings.get('append_id') else ''}{ext or '.mp3'}"
        self.fetch(rec, t["download_url"], target)
        self.tag_file(target, rec)
        self.finish(rec, str(target), "original")

    def purchase(self, rec: dict, folder: Path):
        """A Bandcamp purchase: download page -> chosen format -> file (albums arrive zipped)."""
        t = rec["track"]
        fmt, url = self.sites.bc_download_link(t["download_page"], self.settings.get("bc_quality"))
        tmp = folder / f".cratez-{uuid.uuid4().hex}.download"
        name = self.fetch(rec, url, tmp) or f"{t['uploader']} - {t['title']}"
        if zipfile.is_zipfile(tmp):
            dest = folder / safe(f"{t['uploader']} - {t['title']}")
            dest.mkdir(exist_ok=True)
            files = []
            with zipfile.ZipFile(tmp) as z:
                for member in z.infolist():
                    if member.is_dir():
                        continue
                    outp = dest / safe(Path(member.filename).name)
                    with z.open(member) as src, open(outp, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if outp.suffix.lower() in AUDIO_EXT:
                        files.append(outp)
            tmp.unlink(missing_ok=True)
            self.finish(rec, str(dest), f"{fmt} · {len(files)} tracks", files)
        else:
            ext = Path(name).suffix or {"flac": ".flac", "wav": ".wav", "aiff-lossless": ".aiff"}.get(fmt, ".mp3")
            target = folder / (safe(Path(name).stem) + ext)
            tmp.replace(target)
            self.finish(rec, str(target), fmt)


# ------------------------------------------------------------------------------ collecting

class Collector:
    """Runs a genre's searches on every enabled site and queues everything that matches."""

    def __init__(self, settings: Settings, sites: Sites, downloads: Downloads):
        self.settings, self.sites, self.downloads = settings, sites, downloads
        self.lock = threading.Lock()
        self.state = {"running": False, "genre": None, "step": "", "found": 0, "queued": 0, "log": []}

    def status(self):
        with self.lock:
            return dict(self.state)

    def note(self, msg: str):
        with self.lock:
            self.state["step"] = msg
            self.state["log"] = (self.state["log"] + [msg])[-40:]

    def ok(self, t: dict, keywords: list[str]) -> bool:
        if keywords:
            hay = (t.get("title", "") + " " + (t.get("tag", "") if t["platform"] == "bandcamp" else "")).lower()
            if not any(k in hay for k in keywords):
                return False
        d = t.get("duration") or 0
        if d:
            lo, hi = self.settings.get("min_seconds"), self.settings.get("max_seconds")
            if (lo and d < lo) or (hi and d > hi):
                return False
        return True

    def search(self, q: str, days: int, count: int, platforms: dict, sc_tags: list[str] | None = None,
               prefix: str = "") -> list[dict]:
        results, seen = [], set()

        def take(items):
            for t in items:
                if t["key"] not in seen:
                    seen.add(t["key"])
                    results.append(t)

        cutoff = time.time() - days * 86400 if days > 0 else None
        if platforms.get("soundcloud", True):
            for tag in (sc_tags or [None]):
                try:
                    take(self.sites.sc_search(q, days, count, tag))
                except Exception as e:
                    log.warning("SoundCloud search failed: %s", e)
                    self.note(f"SoundCloud search failed: {str(e)[:80]}")
        text = f"{prefix} {q}".strip()
        if platforms.get("hearthis", True):
            try:
                take([t for t in self.sites.ht_search(text, count) if not cutoff or not t["ts"] or t["ts"] >= cutoff])
            except Exception as e:
                log.warning("hearthis search failed: %s", e)
        if platforms.get("bandcamp", True):
            try:
                take(self.sites.bc_search(text, count))
            except Exception as e:
                log.warning("Bandcamp search failed: %s", e)
        return results

    def run(self, genre_names: list[str] | None):
        with self.lock:
            if self.state["running"]:
                return False
            self.state.update(running=True, genre=None, step="starting", found=0, queued=0, log=[])
        threading.Thread(target=self._run, args=(genre_names,), daemon=True).start()
        return True

    def _run(self, genre_names):
        try:
            genres = self.settings.get("genres")
            if genre_names:
                wanted = {g.lower() for g in genre_names}
                genres = [g for g in genres if g["name"].lower() in wanted]
            days, count = self.settings.get("days"), self.settings.get("search_count")
            platforms = self.settings.get("platforms")
            keywords = self.settings.get("keywords") if self.settings.get("match_keywords") else []
            for g in genres:
                with self.lock:
                    self.state["genre"] = g["name"]
                matches, seen = [], set()
                for term in g["searches"] or DEFAULT_SEARCHES:
                    self.note(f"{g['name']}: searching \"{term}\"")
                    for t in self.search(term, days, count, platforms, g["tags"], " ".join(g["tags"][:1])):
                        if t["key"] in seen or not self.ok(t, keywords):
                            continue
                        seen.add(t["key"])
                        matches.append(t)
                queued = self.downloads.add(matches, g["name"])
                with self.lock:
                    self.state["found"] += len(matches)
                    self.state["queued"] += queued
                self.note(f"{g['name']}: {len(matches)} matches, {queued} new queued")
            self.note("finished")
        except Exception as e:
            log.exception("collect failed")
            self.note(f"stopped: {e}")
        finally:
            with self.lock:
                self.state["running"] = False


# ------------------------------------------------------------------------------ the app

class App:
    def __init__(self):
        self.settings = Settings()
        self.cookies = CookieFile(DATA / "cookies.txt")
        self.sites = Sites(self.cookies)
        self.serato = Serato(self.settings)
        self.downloads = Downloads(self.settings, self.sites, self.serato)
        self.collector = Collector(self.settings, self.sites, self.downloads)
        self.last_ping = time.time()
        self.quit = threading.Event()

    # --- accounts
    def login_soundcloud(self, token: str) -> dict:
        if not re.match(r"^[\w-]{10,}$", token.strip().strip('"')):
            raise ValueError("That doesn't look like a SoundCloud oauth_token value")
        self.cookies.set(".soundcloud.com", "oauth_token", token)
        return self.verify("soundcloud")

    def login_bandcamp(self, identity: str) -> dict:
        if len(identity.strip()) < 20:
            raise ValueError("That doesn't look like a Bandcamp identity cookie value")
        self.cookies.set(".bandcamp.com", "identity", identity)
        return self.verify("bandcamp")

    def import_cookies(self, text: str) -> dict:
        self.cookies.merge(text)
        out = {}
        if self.cookies.has("soundcloud.com", "oauth_token"):
            try:
                out["soundcloud"] = self.verify("soundcloud")
            except ValueError as e:
                out["soundcloud_error"] = str(e)
        if self.cookies.has("bandcamp.com", "identity"):
            try:
                out["bandcamp"] = self.verify("bandcamp")
            except ValueError as e:
                out["bandcamp_error"] = str(e)
        if not out:
            raise ValueError("No SoundCloud oauth_token or Bandcamp identity cookie in that file")
        return out

    def verify(self, site: str) -> dict:
        self.sites.reset()
        user = None
        try:
            user = self.sites.sc_me() if site == "soundcloud" else self.sites.bc_me()
        except Exception as e:
            log.warning("%s login check failed: %s", site, e)
        if not user:
            self.cookies.drop(".soundcloud.com" if site == "soundcloud" else ".bandcamp.com")
            self.sites.reset()
            self.settings.update({"sc_user" if site == "soundcloud" else "bc_user": None})
            raise ValueError(f"{PLATFORMS[site]} rejected that token - copy the cookie value again while signed in")
        self.settings.update({"sc_user" if site == "soundcloud" else "bc_user": user})
        return user

    def logout(self, site: str):
        self.cookies.drop(".soundcloud.com" if site == "soundcloud" else ".bandcamp.com")
        self.sites.reset()
        self.settings.update({"sc_user" if site == "soundcloud" else "bc_user": None})

    # --- state
    def state(self) -> dict:
        s = self.settings.public()
        serato_dir = s.get("serato_dir") or ""
        return {"version": VERSION, "settings": s, "user": s.get("sc_user"), "bc_user": s.get("bc_user"),
                "ffmpeg": bool(self.downloads.ffmpeg), "downloads": self.downloads.snapshot(),
                "collect": self.collector.status(), "log_file": str(LOG_FILE), "platforms": PLATFORMS,
                "layouts": LAYOUTS, "os": platform.system(),
                "serato_found": bool(serato_dir and Path(serato_dir).is_dir())}

    # --- search box
    def search(self, q: str, genre: str | None, days: int | None, only_keywords: bool, platforms: dict | None):
        q = (q or "").strip()
        if not q and not genre:
            return {"results": [], "from_url": False}
        days = self.settings.get("days") if days is None else max(0, int(days))
        platforms = platforms or self.settings.get("platforms")
        if platform_of(q):
            site = platform_of(q)
            tracks = {"soundcloud": self.sites.sc_resolve, "bandcamp": self.sites.bc_resolve,
                      "hearthis": self.sites.ht_resolve}[site](q)
            return {"results": tracks, "from_url": True}
        g = self.settings.genre(genre) if genre else None
        results = self.collector.search(q or (g["tags"][0] if g and g["tags"] else genre), days,
                                        self.settings.get("search_count"), platforms,
                                        g["tags"] if g else None, g["tags"][0] if g and g["tags"] else "")
        keywords = self.settings.get("keywords") if only_keywords else []
        results = [t for t in results if self.collector.ok(t, keywords)]
        results.sort(key=lambda t: t["ts"], reverse=True)
        return {"results": results, "from_url": False}

    # --- OS bits
    def open_path(self, rec_id: str | None):
        path = None
        if rec_id:
            r = self.downloads.find(rec_id)
            path = r and r.get("path")
        if path and Path(path).exists():
            p = Path(path)
            if IS_WIN:
                subprocess.Popen(["explorer", "/select,", str(p)] if p.is_file() else ["explorer", str(p)])
            elif IS_MAC:
                subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
            return
        folder = Path(self.settings.get("out_dir")).expanduser()
        if rec_id and (r := self.downloads.find(rec_id)):
            cand = self.downloads.folder_for(r)
            folder = cand if cand.exists() else folder
        folder.mkdir(parents=True, exist_ok=True)
        self.open_folder(folder)

    @staticmethod
    def open_folder(folder: Path):
        if IS_WIN:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    @staticmethod
    def pick_folder(start: str) -> str | None:
        try:
            if IS_WIN:
                ps = ("Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
                      "$d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'Choose the Cratez download folder';"
                      f"$d.SelectedPath = '{start}'; if ($d.ShowDialog($f) -eq 'OK') {{ Write-Output $d.SelectedPath }}")
                out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True, timeout=600)
                return out.stdout.strip() or None
            if IS_MAC:
                out = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose the Cratez download folder")'],
                                     capture_output=True, text=True, timeout=600)
                return out.stdout.strip().rstrip("/") or None
            if shutil.which("zenity"):
                out = subprocess.run(["zenity", "--file-selection", "--directory"], capture_output=True, text=True, timeout=600)
                return out.stdout.strip() or None
        except Exception as e:
            log.warning("folder picker failed: %s", e)
        return None

    def export_csv(self) -> str:
        out = Path(self.settings.get("out_dir")).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        path = out / "not_downloaded.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["genre", "title", "uploader", "platform", "status", "reason", "link"])
            for r in self.downloads.snapshot():
                if r["status"] in ("unavailable", "paid", "failed"):
                    t = r["track"]
                    w.writerow([r["genre"], t["title"], t["uploader"], PLATFORMS.get(t["platform"], t["platform"]),
                                r["status"], r.get("error") or "", t["url"]])
        return str(path)

    def rebuild_serato(self) -> int:
        n = 0
        by_genre: dict[str, list[Path]] = {}
        for p, genre in self.downloads.done_files():
            if p.is_dir():
                by_genre.setdefault(genre, []).extend(x for x in p.iterdir() if x.suffix.lower() in AUDIO_EXT)
            elif p.exists():
                by_genre.setdefault(genre, []).append(p)
        for genre, files in by_genre.items():
            n += self.serato.add(files, genre)
        return n


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"{APP_NAME}/{VERSION}"

        def log_message(self, fmt, *args):
            if "/api/ping" not in (args[0] if args else ""):
                log.debug("http " + fmt, *args)

        def send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/ping":
                app.last_ping = time.time()
                return self.send_json({"ok": True})
            if path == "/api/state":
                app.last_ping = time.time()
                return self.send_json(app.state())
            if path in ("/", "/index.html"):
                page = (UI_DIR / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(page)
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            if self.headers.get("X-Cratez") != "1":   # only our own page may drive the API
                return self.send_json({"error": "forbidden"}, 403)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.send_json({"error": "bad json"}, 400)
            route = self.path.split("?")[0]
            try:
                result = self.dispatch(route, body)
            except (ValueError, ExtractorError, yt_dlp.utils.DownloadError) as e:
                msg = re.sub(r"^ERROR:\s*", "", str(e).splitlines()[0]) if str(e) else "error"
                return self.send_json({"error": msg[:300]}, 400)
            except Exception as e:
                log.exception("api %s failed", route)
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:200]}"}, 500)
            self.send_json(result if result is not None else {"ok": True})

        def dispatch(self, route, body):
            d, s = app.downloads, app.settings
            if route == "/api/search":
                return app.search(body.get("q"), body.get("genre"), body.get("days"),
                                  bool(body.get("only_keywords", True)), body.get("platforms"))
            if route == "/api/download":
                return {"added": d.add(body.get("tracks") or [], body.get("genre") or "")}
            if route == "/api/collect":
                return {"started": app.collector.run(body.get("genres"))}
            if route == "/api/likes":
                user = s.get("sc_user")
                if not user:
                    raise ValueError("Sign in to SoundCloud first (Settings > Accounts)")
                return {"results": app.sites.sc_likes(user["id"], int(body.get("limit") or 1000))}
            if route == "/api/purchases":
                user = s.get("bc_user")
                if not user:
                    raise ValueError("Sign in to Bandcamp first (Settings > Accounts)")
                return {"results": app.sites.bc_purchases(user["id"])}
            if route == "/api/login":
                site = body.get("site") or "soundcloud"
                fn = app.login_soundcloud if site == "soundcloud" else app.login_bandcamp
                return {"user": fn(body.get("token") or "")}
            if route == "/api/cookies":
                return app.import_cookies(body.get("text") or "")
            if route == "/api/logout":
                app.logout(body.get("site") or "soundcloud")
                return {"ok": True}
            if route == "/api/settings":
                s.update(body)
                return {"settings": s.public()}
            if route == "/api/reset_settings":
                s.reset()
                return {"settings": s.public()}
            if route == "/api/pick_folder":
                return {"path": app.pick_folder(body.get("start") or s.get("out_dir"))}
            if route == "/api/open":
                app.open_path(body.get("id"))
                return {"ok": True}
            if route == "/api/open_file":   # a known path: the log or the CSV
                p = Path(body.get("path") or "")
                if p.exists():
                    app.open_folder(p.parent if p.is_file() else p)
                return {"ok": True}
            if route == "/api/export":
                path = app.export_csv()
                app.open_folder(Path(path).parent)
                return {"path": path}
            if route == "/api/serato_rebuild":
                return {"added": app.rebuild_serato()}
            if route == "/api/remove":
                d.remove(body.get("id"))
                return {"ok": True}
            if route == "/api/retry":
                d.retry(body.get("id"))
                return {"ok": True}
            if route == "/api/clear":
                d.clear_finished()
                return {"ok": True}
            if route == "/api/clear_all":
                d.clear_all()
                return {"ok": True}
            if route == "/api/quit":
                app.quit.set()
                return {"ok": True}
            raise ValueError(f"unknown route {route}")

    return Handler


# ------------------------------------------------------------------------------ window

def open_window(url: str) -> bool:
    """Open the UI as an app window in Edge/Chrome/Brave; fall back to the default browser."""
    candidates = []
    if IS_WIN:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [Path(pf86) / "Microsoft/Edge/Application/msedge.exe", Path(pf) / "Microsoft/Edge/Application/msedge.exe",
                       Path(pf) / "Google/Chrome/Application/chrome.exe", Path(pf86) / "Google/Chrome/Application/chrome.exe",
                       Path(local) / "Google/Chrome/Application/chrome.exe", Path(pf) / "BraveSoftware/Brave-Browser/Application/brave.exe"]
    elif IS_MAC:
        candidates += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                       Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                       Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                       Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    else:
        candidates += [Path(p) for p in map(shutil.which, ["google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"]) if p]
    for exe in candidates:
        if exe.exists():
            try:
                subprocess.Popen([str(exe), f"--app={url}", "--window-size=1500,940", "--disable-features=TranslateUI"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
    return webbrowser.open(url)   # Safari etc.: a normal tab, same app


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} {VERSION}")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-window", action="store_true", help="don't open a window; print the URL")
    args = ap.parse_args()

    app = App()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    server.daemon_threads = True
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("%s %s listening on %s (data in %s)", APP_NAME, VERSION, url, DATA)
    if args.no_window:
        print(f"{APP_NAME} running at {url}  (Ctrl+C to stop)", flush=True)
    else:
        open_window(url)

    started = time.time()
    try:
        while not app.quit.is_set():
            time.sleep(2)
            idle = time.time() - app.last_ping
            if not args.no_window and idle > 30 and time.time() - started > 90 and not app.downloads.active():
                log.info("no window for %.0fs and nothing downloading - exiting", idle)
                break
    except KeyboardInterrupt:
        pass
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
