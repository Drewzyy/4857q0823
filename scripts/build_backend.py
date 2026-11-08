"""Package the Python service for the Vyral app (Mac or Windows) as a ready-to-run folder.

A folder (PyInstaller "onedir") instead of a single self-extracting file: it starts in seconds instead of
unpacking ~250 MB into a temp folder on every launch, and macOS/antivirus don't re-scan it each time.
Bundles FFmpeg, yt-dlp, the speech engine and fonts so users never install anything."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    import imageio_ffmpeg

    triple = next(l.split(": ", 1)[1] for l in subprocess.check_output(["rustc", "-vV"], text=True).splitlines() if l.startswith("host:"))
    build = BACKEND / "build"
    sep = os.pathsep
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "clippr-backend",
           "--distpath", str(build / "dist"), "--workpath", str(build / "work"), "--specpath", str(build),
           "--add-data", f"{BACKEND / 'clippr' / 'migrations'}{sep}clippr/migrations",
           "--add-data", f"{BACKEND / 'clippr' / 'media' / 'fonts'}{sep}clippr/media/fonts",
           "--collect-all", "faster_whisper", "--collect-all", "ctranslate2", "--collect-all", "av",
           "--collect-all", "tokenizers", "--collect-submodules", "huggingface_hub",
           "--add-binary", f"{ffmpeg}{sep}imageio_ffmpeg/binaries",
           "--collect-submodules", "clippr", "--collect-submodules", "keyring", "--collect-submodules", "yt_dlp",
           "--hidden-import", "keyring.backends.macOS", "--hidden-import", "keyring.backends.Windows",
           # Pulled in as optional extras by dependencies; Vyral never uses them.
           "--exclude-module", "pandas", "--exclude-module", "PIL", "--exclude-module", "lxml",
           "--exclude-module", "matplotlib", "--exclude-module", "tkinter", "--exclude-module", "IPython",
           "--exclude-module", "pytest"]
    if sys.platform == "win32":
        cmd.append("--noconsole")
    cmd.append(str(BACKEND / "clippr" / "__main__.py"))
    subprocess.check_call(cmd, cwd=BACKEND)
    out = ROOT / "desktop" / "src-tauri" / "service"
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(build / "dist" / "clippr-backend", out, symlinks=True)
    exe = out / ("clippr-backend.exe" if sys.platform == "win32" else "clippr-backend")
    exe.chmod(0o755)
    print(f"service: {exe} (built for {triple})")


if __name__ == "__main__":
    main()
