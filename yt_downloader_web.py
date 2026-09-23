#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import threading
import webbrowser
from pathlib import Path

from flask import Flask, request, jsonify, Response, stream_with_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_internal"))

import yt_dlp
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
DEFAULT_DIR = str(Path.home() / "Downloads")
os.makedirs(DEFAULT_DIR, exist_ok=True)

app = Flask(__name__, template_folder=None)
_progress = {"status": "idle", "message": "Ready.", "done": False, "error": None}
_lock = threading.Lock()

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YT Downloader</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f5f5f7; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; padding: 20px; }
  .card { background: white; border-radius: 16px; padding: 40px;
          width: 100%; max-width: 560px;
          box-shadow: 0 4px 24px rgba(0,0,0,0.10); }
  h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; color: #1d1d1f; }
  .sub { font-size: 13px; color: #6e6e73; margin-bottom: 28px; }
  label { font-size: 13px; font-weight: 600; color: #1d1d1f;
          display: block; margin-bottom: 6px; }
  input[type=text] { width: 100%; padding: 10px 14px; border: 1px solid #d2d2d7;
                     border-radius: 10px; font-size: 15px; outline: none;
                     transition: border 0.2s; margin-bottom: 16px; }
  input[type=text]:focus { border-color: #0071e3; }
  .row { display: flex; gap: 10px; align-items: center; margin-bottom: 24px; }
  .row input[type=text] { margin-bottom: 0; flex: 1; }
  button.browse { padding: 10px 16px; background: #f5f5f7; border: 1px solid #d2d2d7;
                  border-radius: 10px; font-size: 13px; cursor: pointer;
                  white-space: nowrap; }
  button.browse:hover { background: #e8e8ed; }
  button#dl { width: 100%; padding: 14px; background: #0071e3; color: white;
              border: none; border-radius: 10px; font-size: 16px; font-weight: 600;
              cursor: pointer; transition: background 0.2s; }
  button#dl:hover:not(:disabled) { background: #0077ed; }
  button#dl:disabled { background: #a1c4f5; cursor: not-allowed; }
  .progress-wrap { margin-top: 20px; display: none; }
  .bar-bg { background: #e8e8ed; border-radius: 999px; height: 8px; overflow: hidden; }
  .bar { height: 8px; border-radius: 999px; background: #0071e3;
         width: 0%; transition: width 0.3s; }
  .status { font-size: 13px; color: #6e6e73; margin-top: 8px; }
  .success { color: #1d8348; font-weight: 600; }
  .err { color: #c0392b; font-weight: 600; }
</style>
</head>
<body>
<div class="card">
  <h1>YT Downloader</h1>
  <p class="sub">Downloads a single video as a PowerPoint-compatible MP4</p>

  <label for="url">YouTube URL</label>
  <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=...">

  <label>Save to</label>
  <div class="row">
    <input type="text" id="outdir" value="{DEFAULT_DIR}">
  </div>

  <button id="dl" onclick="startDownload()">Download MP4</button>

  <div class="progress-wrap" id="pw">
    <div class="bar-bg"><div class="bar" id="bar"></div></div>
    <div class="status" id="status">Starting...</div>
  </div>
</div>
<script>
function startDownload() {
  const url = document.getElementById('url').value.trim();
  const dir = document.getElementById('outdir').value.trim();
  if (!url) { alert('Paste a YouTube URL first.'); return; }

  document.getElementById('dl').disabled = true;
  document.getElementById('dl').textContent = 'Downloading...';
  document.getElementById('pw').style.display = 'block';
  document.getElementById('status').className = 'status';
  document.getElementById('bar').style.width = '5%';

  fetch('/download', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url, dir})
  });

  pollProgress();
}

function pollProgress() {
  fetch('/progress').then(r => r.json()).then(data => {
    document.getElementById('status').textContent = data.message;

    if (data.percent) {
      document.getElementById('bar').style.width = data.percent + '%';
    }

    if (data.done) {
      document.getElementById('bar').style.width = '100%';
      document.getElementById('dl').disabled = false;
      document.getElementById('dl').textContent = 'Download MP4';
      if (data.error) {
        document.getElementById('status').className = 'status err';
        document.getElementById('status').textContent = 'Error: ' + data.error;
      } else {
        document.getElementById('status').className = 'status success';
        document.getElementById('status').textContent = '✓ Saved: ' + data.message;
      }
    } else {
      setTimeout(pollProgress, 800);
    }
  }).catch(() => setTimeout(pollProgress, 1500));
}
</script>
</body>
</html>
""".replace("{DEFAULT_DIR}", DEFAULT_DIR.replace("\\", "\\\\"))


@app.route("/")
def index():
    return HTML


def find_browser_cookies():
    is_windows = sys.platform == "win32"
    browsers = (
        ["chrome", "edge", "firefox"]
        if is_windows
        else ["safari", "chrome", "firefox"]
    )
    for browser in browsers:
        try:
            with yt_dlp.YoutubeDL({"cookiesfrombrowser": (browser,), "quiet": True}) as ydl:
                ydl.cookiejar
            return (browser,)
        except Exception:
            continue
    return None


def run_download(url, out_dir):
    def set_progress(msg, percent=None, done=False, error=None):
        with _lock:
            _progress["message"] = msg
            _progress["done"] = done
            _progress["error"] = error
            if percent is not None:
                _progress["percent"] = percent

    def progress_hook(d):
        if d["status"] == "downloading":
            pct_str = d.get("_percent_str", "").strip().replace("%", "")
            try:
                pct = float(pct_str) * 0.7  # scale to 70% — leave room for convert
            except Exception:
                pct = None
            set_progress(f"Downloading: {d.get('_percent_str','').strip()}", pct)
        elif d["status"] == "finished":
            set_progress("Merging...", 72)

    set_progress("Starting download...", 5)
    cookies = find_browser_cookies()
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "ffmpeg_location": FFMPEG_PATH,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
        "nopart": True,
        "noplaylist": True,
    }
    if cookies:
        ydl_opts["cookiesfrombrowser"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            raise RuntimeError(f"File not found after download: {filename}")

        set_progress("Converting to PowerPoint-compatible format...", 75)
        final_path = make_ppt_compatible(filename, set_progress)
        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        set_progress(
            f"{os.path.basename(final_path)}  ({size_mb:.1f} MB)",
            100, done=True
        )
    except Exception as e:
        set_progress(str(e), done=True, error=str(e))


def make_ppt_compatible(filename, set_progress):
    root, _ = os.path.splitext(filename)
    out = root + "_ppt.mp4"
    # Scale to even dimensions (required by libx264), cap at 1080p
    scale_filter = (
        "scale='if(gt(iw,1920),1920,trunc(iw/2)*2)'"
        ":'if(gt(ih,1080),1080,trunc(ih/2)*2)'"
        ":force_original_aspect_ratio=decrease"
        ",pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    cmd = [
        FFMPEG_PATH, "-y", "-i", filename,
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-profile:v", "baseline",   # baseline = widest Windows PPT compatibility
        "-level", "3.1",
        "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "26",
        "-c:a", "aac",
        "-ar", "44100",             # standard sample rate Windows expects
        "-ac", "2",                 # stereo
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-brand", "mp42",           # MP4 brand Windows Media Player/PPT prefer
        out,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Conversion failed:\n{result.stderr[-2000:]}")
    if not os.path.exists(out):
        raise RuntimeError("ffmpeg finished but output file not found.")
    os.remove(filename)
    return out


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    out_dir = (data.get("dir") or DEFAULT_DIR).strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    os.makedirs(out_dir, exist_ok=True)
    with _lock:
        _progress.update({"status": "running", "message": "Starting...",
                          "done": False, "error": None, "percent": 0})
    threading.Thread(target=run_download, args=(url, out_dir), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/progress")
def progress():
    with _lock:
        return jsonify(dict(_progress))


def open_browser(port):
    import time
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{port}")


if __name__ == "__main__":
    port = 45678
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
