#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Idempotent bootstrap for the YouTube HD downloader environment.

Checks / installs:
  1. pip packages: yt-dlp[default] (includes yt-dlp-ejs),
     bgutil-ytdlp-pot-provider, imageio-ffmpeg
  2. ffmpeg binary (via imageio_ffmpeg)
  3. node / npm / npx
  4. bgutil PO Token server: git clone (2.0.2) + npm ci + npx tsc

All subprocesses run with NODE_OPTIONS removed (WorkBuddy sandbox shim fix).

Usage:
  python setup.py [--upgrade]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

REPO_URL = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"
REPO_TAG = "2.0.2"
PIP_SPECS = [
    "yt-dlp[default]",
    "bgutil-ytdlp-pot-provider",
    "imageio-ffmpeg",
]

HOME = os.path.expanduser("~")
DEFAULT_REPO = os.path.join(HOME, "bgutil-ytdlp-pot-provider")
KNOWN_NODE_DIR = r"C:\Users\Admin\.workbuddy\binaries\node\versions\22.22.2-6"


def log(msg):
    print("[setup] %s" % msg, flush=True)


def clean_env():
    env = os.environ.copy()
    removed = env.pop("NODE_OPTIONS", None)
    if removed:
        log("NODE_OPTIONS cleared: %s" % removed[:100])
    os.environ.pop("NODE_OPTIONS", None)
    return env


def run(cmd, env, cwd=None, capture=False):
    log("RUN: %s%s" % (" ".join(cmd), (" (cwd=%s)" % cwd) if cwd else ""))
    if capture:
        p = subprocess.run(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, errors="replace")
        if p.stdout:
            print(p.stdout.rstrip(), flush=True)
        return p.returncode
    return subprocess.run(cmd, env=env, cwd=cwd).returncode


def pip_show(pkg_name, env, python):
    p = subprocess.run([python, "-m", "pip", "show", pkg_name],
                       env=env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    return p.returncode == 0


def pkg_base(spec):
    return re.split(r"[\[<>=!~]", spec)[0].strip().lower().replace("_", "-")


def ensure_pip_packages(env, python, upgrade):
    for spec in PIP_SPECS:
        base = pkg_base(spec)
        installed = pip_show(base, env, python)
        if installed and not upgrade:
            log("OK: %s already installed" % base)
            continue
        cmd = [python, "-m", "pip", "install"] + (["-U"] if upgrade else []) + [spec]
        rc = run(cmd, env)
        if rc != 0:
            log("WARNING: failed to install %s" % spec)
        else:
            log("Installed: %s" % spec)
    # yt-dlp[default] installs yt-dlp-ejs as an extra; verify explicitly.
    if not pip_show("yt-dlp-ejs", env, python):
        log("yt-dlp-ejs missing, installing explicitly...")
        run([python, "-m", "pip", "install", "-U", "yt-dlp-ejs"], env)


def ensure_ffmpeg(env, python):
    code = (
        "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
    )
    p = subprocess.run([python, "-c", code], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    path = (p.stdout or "").strip()
    if path and os.path.isfile(path):
        log("OK: ffmpeg = %s" % path)
        return path
    log("WARNING: ffmpeg not found via imageio_ffmpeg")
    return None


def find_tool(name, node_dir):
    p = shutil.which(name)
    if p:
        return p
    if os.path.isdir(node_dir):
        for ext in (".cmd", ".bat", ".exe", ""):
            cand = os.path.join(node_dir, name + ext)
            if os.path.isfile(cand):
                return cand
    return None


def ensure_pot_server(env):
    node_dir = os.environ.get("NODE_DIR", KNOWN_NODE_DIR)
    npm = find_tool("npm", node_dir)
    npx = find_tool("npx", node_dir)
    node = find_tool("node", node_dir)
    log("node=%s npm=%s npx=%s" % (node, npm, npx))
    if not node or not npm or not npx:
        log("WARNING: node/npm/npx not all available; cannot build PO server.")
        return False

    repo = os.environ.get("BGUTIL_REPO_DIR", DEFAULT_REPO)
    server = os.path.join(repo, "server")
    main_js = os.path.join(server, "build", "main.js")

    if os.path.isfile(main_js):
        log("OK: PO server already built at %s" % main_js)
        return True

    if not os.path.isdir(repo):
        log("Cloning PO provider repo (%s) into %s" % (REPO_TAG, repo))
        rc = run(["git", "clone", "--single-branch", "--branch", REPO_TAG,
                  "--depth", "1", REPO_URL, repo], env)
        if rc != 0 or not os.path.isdir(server):
            log("WARNING: git clone failed")
            return False
    else:
        log("Repo dir exists but build missing: %s" % repo)

    for cmd in ([npm, "ci"], [npx, "tsc"]):
        rc = run(cmd, env, cwd=server)
        if rc != 0:
            log("WARNING: command failed: %s" % " ".join(cmd))
            return False

    if os.path.isfile(main_js):
        log("OK: PO server built at %s" % main_js)
        return True
    log("WARNING: build finished but main.js not found")
    return False


def main():
    ap = argparse.ArgumentParser(description="Bootstrap YouTube HD downloader env")
    ap.add_argument("--upgrade", action="store_true", help="Upgrade pip packages")
    args = ap.parse_args()

    env = clean_env()
    python = sys.executable or "python"
    log("Python: %s" % python)

    ok = True
    ensure_pip_packages(env, python, args.upgrade)
    if not ensure_ffmpeg(env, python):
        ok = False
    if not ensure_pot_server(env):
        ok = False

    if ok:
        log("ALL CHECKS PASSED. Ready to download.")
    else:
        log("SOME CHECKS FAILED. Review warnings above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
