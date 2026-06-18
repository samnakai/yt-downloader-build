#!/usr/bin/env python3
import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import yt_dlp
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
os.makedirs(DEFAULT_DIR, exist_ok=True)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.geometry("520x220")
        self.resizable(False, False)

        tk.Label(self, text="YouTube URL:", anchor="w").pack(fill="x", padx=12, pady=(14, 2))
        self.url_entry = tk.Entry(self, width=60)
        self.url_entry.pack(padx=12, fill="x")

        dir_frame = tk.Frame(self)
        dir_frame.pack(padx=12, pady=10, fill="x")
        tk.Label(dir_frame, text="Save to:").pack(side="left")
        self.dir_var = tk.StringVar(value=DEFAULT_DIR)
        tk.Entry(dir_frame, textvariable=self.dir_var, width=40).pack(side="left", padx=6)
        tk.Button(dir_frame, text="Choose...", command=self.choose_dir).pack(side="left")

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(self, textvariable=self.status_var, fg="gray").pack(padx=12, pady=(4, 0), anchor="w")

        self.download_btn = tk.Button(self, text="Download MP4", command=self.start_download, height=2)
        self.download_btn.pack(padx=12, pady=14, fill="x")

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(d)

    def start_download(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a YouTube URL first.")
            return
        out_dir = self.dir_var.get().strip()
        os.makedirs(out_dir, exist_ok=True)
        self.download_btn.config(state="disabled", text="Downloading...")
        self.status_var.set("Starting...")
        threading.Thread(target=self.run_download, args=(url, out_dir), daemon=True).start()

    def progress_hook(self, d):
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "").strip()
            self.status_var.set(f"Downloading: {pct}")
        elif d["status"] == "finished":
            self.status_var.set("Merging...")

    def run_download(self, url, out_dir):
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
            "ffmpeg_location": FFMPEG_PATH,
            "progress_hooks": [self.progress_hook],
            "quiet": True,
            "no_warnings": True,
            "overwrites": True,
            "nopart": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    raise RuntimeError(f"yt-dlp reported success but file not found: {filename}")

            self.after(0, lambda: self.status_var.set("Converting to PowerPoint-compatible format..."))
            final_path = self.make_ppt_compatible(filename)

            self.after(0, lambda: self.finish_success(final_path, out_dir))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self.finish_error(err))

    def make_ppt_compatible(self, filename):
        root, _ext = os.path.splitext(filename)
        compatible_path = root + "_ppt.mp4"
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", filename,
            "-vf", "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease",
            "-c:v", "libx264",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "26",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            compatible_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Conversion failed:\n{result.stderr[-2000:]}")
        if not os.path.exists(compatible_path):
            raise RuntimeError(f"ffmpeg reported success but output file not found: {compatible_path}")
        os.remove(filename)
        return compatible_path

    def finish_success(self, filename, out_dir):
        self.status_var.set("Done.")
        self.download_btn.config(state="normal", text="Download MP4")
        size_mb = os.path.getsize(filename) / (1024 * 1024)
        mtime = os.path.getmtime(filename)
        import datetime
        ts = datetime.datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
        messagebox.showinfo(
            "Download complete",
            f"Saved:\n{filename}\n\nSize: {size_mb:.1f} MB\nModified: {ts}",
        )

    def finish_error(self, err):
        self.status_var.set("Error.")
        self.download_btn.config(state="normal", text="Download MP4")
        messagebox.showerror("Download failed", err)


if __name__ == "__main__":
    App().mainloop()
