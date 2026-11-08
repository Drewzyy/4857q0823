"""Package the Python service as one self-contained executable for the Vyral app (Mac or Windows).
Bundles FFmpeg and yt-dlp so users never install anything. Run on the OS you're building for."""
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
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", "clippr-backend",
           "--distpath", str(build / "dist"), "--workpath", str(build / "work"), "--specpath", str(build),
           "--add-data", f"{BACKEND / 'clippr' / 'migrations'}{sep}clippr/migrations",
           "--add-data", f"{BACKEND / 'clippr' / 'media' / 'fonts'}{sep}clippr/media/fonts",
           "--collect-all", "faster_whisper", "--collect-all", "ctranslate2", "--collect-all", "av",
           "--collect-all", "tokenizers", "--collect-submodules", "huggingface_hub",
           "--add-binary", f"{ffmpeg}{sep}imageio_ffmpeg/binaries",
           "--collect-submodules", "clippr", "--collect-submodules", "keyring", "--collect-submodules", "yt_dlp",
           "--hidden-import", "keyring.backends.macOS", "--hidden-import", "keyring.backends.Windows"]
    if sys.platform == "win32":
        cmd.append("--noconsole")
    cmd.append(str(BACKEND / "clippr" / "__main__.py"))
    subprocess.check_call(cmd, cwd=BACKEND)
    exe = ".exe" if sys.platform == "win32" else ""
    out = ROOT / "desktop" / "src-tauri" / "binaries"
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"clippr-backend-{triple}{exe}"
    shutil.copyfile(build / "dist" / f"clippr-backend{exe}", target)
    target.chmod(0o755)
    print(f"sidecar: {target}")


if __name__ == "__main__":
    main()
