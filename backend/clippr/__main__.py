"""Entry point: `python -m clippr` (dev) or the bundled `clippr-backend` service inside the Vyral app."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watch_parent(pid: int) -> None:
    """Exit when the desktop app is gone, so a force-quit never leaves a second copy monitoring."""
    while True:
        time.sleep(2)
        if not _alive(pid):
            os._exit(0)


def _self_test(audio: Path, data_dir: Path) -> int:
    """Used by the installer build: real transcription + burned-in text inside the packaged app."""
    import json
    import tempfile

    from clippr.media import overlay
    from clippr.media.ffmpeg import probe, run
    from clippr.media.render import OutputFormat, render
    from clippr.media.transcribe import WhisperTranscriber
    from clippr.schemas import OverlaySettings

    import os

    import yt_dlp
    from yt_dlp.downloader.external import FFmpegFD

    from clippr.fetch import use_bundled_ffmpeg

    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        impersonate = bool(ydl._get_available_impersonate_targets())
    path = os.environ.get("PATH", "")
    os.environ["PATH"] = ""  # like a computer with no FFmpeg installed: only the bundled one may count
    try:
        use_bundled_ffmpeg()
        sections = bool(FFmpegFD.available())
    finally:
        os.environ["PATH"] = path
    print(json.dumps({"impersonate": impersonate, "stream_sections": sections}))
    try:  # the facecam layout needs OpenCV and both face models inside the app
        import cv2

        from clippr.media.facecam import MODEL
        cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320))
        facecam = not cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml").empty()
    except Exception as e:
        print(json.dumps({"facecam_error": f"{type(e).__name__}: {e}"}))
        facecam = False
    print(json.dumps({"facecam": facecam}))
    try:  # emoji in titles need the text measured with the bundled fonts
        from clippr.media import emoji, overlay as ovl
        _, placed = emoji.layout("SELF TEST 😂", ovl.FONT_DIR / ovl.FONTS["montserrat"][0], 80, 900, 540, 300)
        emoji_ok = len(placed) == 1 and placed[0].x > 540
    except Exception as e:
        print(json.dumps({"emoji_error": f"{type(e).__name__}: {e}"}))
        emoji_ok = False
    print(json.dumps({"emoji": emoji_ok}))
    words = WhisperTranscriber(data_dir / "models").words(audio)
    print(json.dumps({"words": [w.text for w in words]}))
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # Fixed 3 s test video; the speech audio is padded/cut to fit so the render check never depends on it.
        run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=3", "-i", str(audio), "-af", "apad", "-t", "3",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(d / "src.mp4")])
        ass = overlay.build_ass(1080, 1920, OverlaySettings().model_dump(), "Self test title", words, 3)
        overlay.prepare(d / "ov", ass)
        out = render(d / "src.mp4", d / "out.mp4", OutputFormat(), duration=3, overlay_dir=d / "ov")
        info = probe(out)
        print(json.dumps({"render": [info.width, info.height]}))
    return 0 if impersonate and sections and facecam and emoji_ok and words and info.height == 1920 else 1


def main() -> None:
    # Windowed builds on Windows have no console: give logging somewhere to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    parser = argparse.ArgumentParser(prog="clippr-backend")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLIPPR_PORT", "8765")))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--frontend", default=os.environ.get("CLIPPR_FRONTEND_DIST"), help="path to built frontend (dist/)")
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--self-test", metavar="SPEECH_AUDIO", default=None,
                        help="check speech-to-text and text rendering work in this build, then exit")
    args = parser.parse_args()
    if args.self_test:
        sys.exit(_self_test(Path(args.self_test), Path(args.data_dir or ".")))

    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(args.parent_pid,), daemon=True).start()
    if args.data_dir:
        os.environ["CLIPPR_DATA_DIR"] = args.data_dir
    import uvicorn

    from clippr.app import create_app
    from clippr.config import Config

    cfg = Config(port=args.port)
    if args.frontend:
        cfg.frontend_dist = Path(args.frontend).resolve()
    else:
        guess = Path(__file__).resolve().parents[2] / "frontend" / "dist"
        cfg.frontend_dist = guess if guess.exists() else None
    app = create_app(cfg)
    print(f"CLIPPR_READY url={cfg.base_url}/", flush=True)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning", access_log=False, log_config=None)


if __name__ == "__main__":
    main()
