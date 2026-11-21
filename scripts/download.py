#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robust YouTube HD downloader.

Features:
  - Removes NODE_OPTIONS (WorkBuddy sandbox shim) from the child environment.
  - Auto-discovers ffmpeg (imageio_ffmpeg / known path / PATH).
  - Auto-starts the bgutil PO Token server on port 4416 if it is not running.
  - Expands playlists into (index, id, url) entries.
  - Optional --start/--end to download only a range of playlist episodes.
  - Downloads episode by episode: 1080p -> 720p -> best, with retries on 403 /
    "Requested format is not available" / missing-URL errors.
  - Skips already-downloaded files (size based).
  - Verifies real resolution with ffmpeg and prints a summary.

Usage:
  python download.py URL --out DIR [--quality 1080|720|best] [--whole] [--retries 5]
                         [--start N] [--end N]
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# Known-good paths in the verified WorkBuddy environment (used as defaults,
# with automatic discovery as fallback).
# ---------------------------------------------------------------------------
KNOWN_PYTHON = r"C:\Users\Admin\.workbuddy\binaries\python\versions\3.13.12\python.exe"
KNOWN_NODE = r"C:\Users\Admin\.workbuddy\binaries\node\versions\22.22.2-6\node"
KNOWN_FFMPEG = (
    r"C:\Users\Admin\.workbuddy\binaries\python\versions\3.13.12"
    r"\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v9.0.2.exe"
)
KNOWN_POT_SERVER = r"C:\Users\Admin\bgutil-ytdlp-pot-provider\server"

# Errors that are worth retrying.
RETRY_MARKERS = (
    "requested format is not available",
    "missing a url",
    "http error 403",
    "error 403",
    "sign in to confirm",
    "unable to download js",
    "n-challenge",
    "ejs",
    "could not copy",
    "merge",
    "connection reset",
    "timed out",
    "temporary failure",
)

# Errors that are permanent -> do not burn all retries.
FATAL_MARKERS = (
    "video unavailable",
    "private video",
    "this video is not available",
    "has been removed",
    "copyright",
    "geo restricted",
)

MIN_OK_BYTES = 1024 * 1024  # 1 MB


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def clean_env():
    """Return a copy of os.environ with NODE_OPTIONS removed (the critical fix)."""
    env = os.environ.copy()
    removed = env.pop("NODE_OPTIONS", None)
    if removed:
        log("NODE_OPTIONS cleared from child environment (was: %s)" % removed[:120])
    # Also clear it from the current process so any implicit subprocess is clean.
    os.environ.pop("NODE_OPTIONS", None)
    return env


def find_python():
    if os.path.isfile(KNOWN_PYTHON):
        return KNOWN_PYTHON
    return sys.executable or "python"


def find_ffmpeg():
    """Return the path to an ffmpeg executable."""
    try:
        import imageio_ffmpeg

        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    if os.path.isfile(KNOWN_FFMPEG):
        return KNOWN_FFMPEG
    p = shutil.which("ffmpeg")
    if p:
        return p
    return None


def find_node():
    if os.path.isfile(KNOWN_NODE):
        return KNOWN_NODE
    p = shutil.which("node")
    if p:
        return p
    return None


def find_pot_server_dir():
    env_dir = os.environ.get("BGUTIL_POT_SERVER_DIR")
    candidates = [env_dir, KNOWN_POT_SERVER]
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "bgutil-ytdlp-pot-provider", "server"))
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "build", "main.js")):
            return c
    return None


def port_open(port, host="127.0.0.1", timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_pot_server(port, env):
    """Make sure the PO Token server is listening; start it in background if not."""
    if port_open(port):
        log("PO Token server already running on port %d" % port)
        return True

    server_dir = find_pot_server_dir()
    node = find_node()
    if not server_dir or not node:
        log("WARNING: cannot find PO Token server or node. Run scripts/setup.py first.")
        return False

    main_js = os.path.join(server_dir, "build", "main.js")
    logfile = os.path.join(server_dir, "po-server.log")
    log("Starting PO Token server on port %d (node=%s)" % (port, node))
    kwargs = {
        "cwd": server_dir,
        "env": env,
        "stdout": open(logfile, "ab"),
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen([node, main_js, "--port", str(port)], **kwargs)
    except Exception as e:
        log("WARNING: failed to start PO server: %s" % e)
        return False

    for _ in range(30):
        if port_open(port):
            log("PO Token server is up on port %d" % port)
            return True
        time.sleep(1)
    log("WARNING: PO Token server did not become ready; check %s" % logfile)
    return False


def run_yt_dlp(args, env, python):
    """Run yt-dlp with the given argument list. Return (rc, combined_output)."""
    cmd = [python, "-m", "yt_dlp"] + args
    proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors="replace")
    return proc.returncode, proc.stdout or ""


def parse_playlist(url, env, python):
    """Return a list of dicts: {index, id, url, title}. Single videos yield one item."""
    args = [
        "--flat-playlist", "--dump-json",
        "--extractor-args", "youtube:player_client=mweb",
        "--no-warnings",
        url,
    ]
    rc, out = run_yt_dlp(args, env, python)
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
        except ValueError:
            continue
        vid = info.get("id")
        page_url = info.get("url") or ""
        if not vid and page_url:
            m = re.search(r"[?&]v=([\w-]+)", page_url)
            if m:
                vid = m.group(1)
        if not vid:
            continue
        title = info.get("title") or vid
        entries.append({
            "index": info.get("playlist_index") or len(entries) + 1,
            "id": vid,
            "url": "https://www.youtube.com/watch?v=%s" % vid,
            "title": title,
        })

    if not entries:
        # Fallback: treat the input as a single URL.
        m = re.search(r"[?&]v=([\w-]+)", url) or re.search(r"youtu\.be/([\w-]+)", url)
        vid = m.group(1) if m else url
        entries = [{"index": 1, "id": vid, "url": url, "title": vid}]
    log("Parsed %d video(s) from input" % len(entries))
    return entries


def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name))
    name = name.strip().strip(".")
    return name[:120] or "video"


def output_base(out_dir, entry, whole):
    title = sanitize(entry["title"])
    if whole:
        idx = int(entry["index"]) if str(entry["index"]).isdigit() else 0
        return os.path.join(out_dir, "%02d - %s" % (idx, title))
    return os.path.join(out_dir, title)


def file_ready(base):
    path = base + ".mp4"
    return os.path.isfile(path) and os.path.getsize(path) > MIN_OK_BYTES


def get_resolution(ffmpeg, path):
    """Return (width, height) or None by inspecting ffmpeg -i output."""
    if not ffmpeg or not os.path.isfile(path):
        return None
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace",
        )
        m = re.search(r"Video:.*?\b(\d{3,4})x(\d{3,4})\b", proc.stdout)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None


def format_candidates(quality):
    if quality == "1080":
        return ["137+140", "136+140", "bestvideo+bestaudio"]
    if quality == "720":
        return ["136+140", "bestvideo+bestaudio"]
    return ["bestvideo+bestaudio", "137+140", "136+140"]


def should_retry(output):
    low = output.lower()
    if any(m in low for m in FATAL_MARKERS):
        return False
    if any(m in low for m in RETRY_MARKERS):
        return True
    # Empty/partial downloads and generic failures are still worth a try.
    return True


def download_one(entry, base, ffmpeg, quality, retries, env, python, pot_port, restart_cb):
    """Try to download a single video. Return (status, resolution)."""
    if file_ready(base):
        log("  SKIP (already exists): %s" % os.path.basename(base))
        res = get_resolution(ffmpeg, base + ".mp4")
        return "skip", res

    for fmt in format_candidates(quality):
        for attempt in range(1, retries + 1):
            log("  FORMAT %s | attempt %d/%d | %s" % (fmt, attempt, retries, entry["id"]))
            args = [
                "--ffmpeg-location", ffmpeg,
                "--js-runtimes", "node",
                "--extractor-args", "youtube:player_client=mweb",
                "-f", fmt,
                "--merge-output-format", "mp4",
                "--no-part",
                "--no-playlist",
                "-o", base + ".%(ext)s",
                entry["url"],
            ]
            rc, out = run_yt_dlp(args, env, python)
            if rc == 0 and file_ready(base):
                res = get_resolution(ffmpeg, base + ".mp4")
                log("  OK -> %s (resolution=%s)" %
                    (os.path.basename(base), "%dx%d" % res if res else "?"))
                return "ok", res

            last_lines = " | ".join(out.strip().splitlines()[-3:])[:300]
            log("  FAIL (rc=%d): %s" % (rc, last_lines))
            if not should_retry(out):
                log("  Permanent error, stop retrying this format.")
                break
            if "403" in out or "format is not available" in out.lower():
                # PO Token binding/timeouts cause most 403s; refresh the service.
                restart_cb()
            if attempt < retries:
                time.sleep(min(attempt, 3))
        log("  Format %s exhausted, trying next format..." % fmt)
    return "fail", None


def main():
    parser = argparse.ArgumentParser(description="Robust YouTube HD downloader")
    parser.add_argument("url", help="Video or playlist URL")
    parser.add_argument("--out", default=".", help="Output directory")
    parser.add_argument("--quality", choices=["1080", "720", "best"], default="1080")
    parser.add_argument("--whole", action="store_true",
                        help="Treat URL as a whole playlist (numbered filenames)")
    parser.add_argument("--retries", type=int, default=5, help="Retries per format")
    parser.add_argument("--pot-port", type=int, default=4416)
    parser.add_argument("--start", type=int, default=None,
                        help="Only download playlist episodes with index >= N")
    parser.add_argument("--end", type=int, default=None,
                        help="Only download playlist episodes with index <= N")
    args = parser.parse_args()

    env = clean_env()  # critical: drop NODE_OPTIONS
    python = find_python()
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        log("ERROR: ffmpeg not found. Run: python -m pip install imageio-ffmpeg")
        return 1
    log("Python : %s" % python)
    log("ffmpeg : %s" % ffmpeg)

    ensure_pot_server(args.pot_port, env)

    def restart_cb():
        # A light-touch refresh: only restart if the server died.
        if not port_open(args.pot_port):
            log("  PO server appears down, restarting...")
            ensure_pot_server(args.pot_port, env)

    os.makedirs(args.out, exist_ok=True)
    entries = parse_playlist(args.url, env, python)

    # Filter by playlist index range if requested.
    if args.start is not None or args.end is not None:
        lo = args.start if args.start is not None else 0
        hi = args.end if args.end is not None else 10 ** 9
        filtered = []
        for e in entries:
            try:
                idx = int(e["index"])
            except (TypeError, ValueError):
                idx = 0
            if lo <= idx <= hi:
                filtered.append(e)
        log("Range filter %s-%s: %d -> %d video(s)" %
            (lo, hi, len(entries), len(filtered)))
        entries = filtered

    stats = {"ok": 0, "skip": 0, "fail": 0}
    resolutions = []
    for entry in entries:
        base = output_base(args.out, entry, args.whole)
        log("DOWNLOAD [%s] %s" % (entry["index"], entry["title"]))
        status, res = download_one(
            entry, base, ffmpeg, args.quality, args.retries, env, python,
            args.pot_port, restart_cb,
        )
        stats[status] = stats.get(status, 0) + 1
        if res:
            resolutions.append((entry["title"], res))

    log("=" * 60)
    log("SUMMARY: ok=%d skip=%d fail=%d total=%d" %
        (stats.get("ok", 0), stats.get("skip", 0), stats.get("fail", 0), len(entries)))
    for title, (w, h) in resolutions:
        tag = "1080p" if h >= 1080 else ("720p" if h >= 720 else "%dp" % h)
        log("  %s -> %dx%d (%s)" % (title[:50], w, h, tag))
    log("=" * 60)
    return 0 if stats.get("fail", 0) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
