#!/usr/bin/env python3
"""Fetches ffmpeg + ffprobe for this OS into vendor/ffmpeg/, so the build can ship them inside Cratez
(tags, cover art, the best SoundCloud streams). Static builds from github.com/eugeneware/ffmpeg-static,
pinned to one release and checked against known SHA-256 sums.

    python installer/get_ffmpeg.py
"""
import gzip
import hashlib
import os
import platform
import sys
import urllib.request
from pathlib import Path

RELEASE = "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/"
SHA256 = {
    "ffmpeg-win32-x64.gz": "8883a3dffbd0a16cf4ef95206ea05283f78908dbfb118f73c83f4951dcc06d77",
    "ffprobe-win32-x64.gz": "f309e6223ad89d2fe54bccd420a7709b66fd27540674e92309578ed491a43c8d",
    "ffmpeg-darwin-arm64.gz": "8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa",
    "ffprobe-darwin-arm64.gz": "d986a8ec7b030899fe66a8a288ed809a3543338705a3ce178cfb85869c5d80be",
    "ffmpeg-darwin-x64.gz": "929b375c1182d956c51f7ac25e0b2b0411fb01f6f407aa15c9758efeb4242106",
    "ffprobe-darwin-x64.gz": "d4da574d6e2e197bd259b47d69cf262df9e312af24ad960444f6d806d3d4c186",
}
OUT = Path(__file__).resolve().parent.parent / "vendor" / "ffmpeg"


def target() -> tuple[str, str]:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        return "win32-x64", ".exe"
    if system == "Darwin":
        return ("darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x64"), ""
    sys.exit("Cratez only bundles ffmpeg for Windows and macOS")


def main() -> int:
    plat, ext = target()
    OUT.mkdir(parents=True, exist_ok=True)
    for tool in ("ffmpeg", "ffprobe"):
        dest = OUT / f"{tool}{ext}"
        if dest.exists():
            print(f"{dest.name} already in {OUT}")
            continue
        name = f"{tool}-{plat}.gz"
        print(f"Downloading {name}...")
        with urllib.request.urlopen(RELEASE + name, timeout=300) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != SHA256[name]:
            sys.exit(f"{name} doesn't match its known checksum - not using it")
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(gzip.decompress(data))
        os.chmod(tmp, 0o755)
        tmp.replace(dest)
    print(f"ffmpeg ready in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
