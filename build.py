"""
Build di Video Downloader.

    python build.py              -> dist/VideoDownloader-Setup-<versione>.exe  (installer)
    python build.py --portable   -> dist/VideoDownloader.exe                   (file unico)

Richiede: pip install pyinstaller PySide6 yt-dlp yt-dlp-ejs truststore  ·  Inno Setup 6 (per l'installer)
"""
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

import common  # noqa: E402
import engine  # noqa: E402
import icons  # noqa: E402

BUILD = HERE / "build"
DIST = HERE / "dist"


def make_icon(path: Path):
    QGuiApplication.instance() or QGuiApplication([])
    pngs = []
    for s in (256, 128, 64, 48, 32, 24, 16):
        img = QImage(s, s, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(icons.ICON_SVG.encode())).render(p)
        p.end()
        buf = QByteArray()
        b = QBuffer(buf)
        b.open(QBuffer.WriteOnly)
        img.save(b, "PNG")
        pngs.append((s, bytes(buf)))
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, data = b"", b""
    for s, png in pngs:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    path.write_bytes(head + entries + data)


def make_version_file(path: Path):
    v = [int(x) for x in common.APP_VERSION.split(".")] + [0, 0, 0]
    v = tuple(v[:4])
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041004B0', [
      StringStruct('CompanyName', 'Cesa028'),
      StringStruct('FileDescription', 'Video Downloader'),
      StringStruct('FileVersion', '{common.APP_VERSION}'),
      StringStruct('InternalName', 'VideoDownloader'),
      StringStruct('LegalCopyright', '© 2026 Cesa028 — MIT License'),
      StringStruct('OriginalFilename', 'VideoDownloader.exe'),
      StringStruct('ProductName', 'Video Downloader'),
      StringStruct('ProductVersion', '{common.APP_VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [0x0410, 1200])])
  ]
)
""", encoding="utf-8")


def find_iscc() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base and (p := Path(base) / "Inno Setup 6" / "ISCC.exe").is_file():
            return str(p)
    return shutil.which("ISCC")


def pyinstaller(onefile: bool, ffmpeg: str, node: str, ico: Path, ver: Path):
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--onefile" if onefile else "--onedir",
        "--name", "VideoDownloader", "--icon", str(ico), "--version-file", str(ver),
        "--add-binary", f"{ffmpeg}{os.pathsep}.", "--add-binary", f"{node}{os.pathsep}.",
        "--collect-all", "yt_dlp", "--collect-all", "yt_dlp_ejs", "--hidden-import", "truststore",
        "--distpath", str(DIST), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
    ]
    for m in ("tkinter", "unittest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtPdf", "PySide6.QtOpenGL", "PySide6.QtWebEngineCore"):
        args += ["--exclude-module", m]
    subprocess.run(args + [str(HERE / "video_downloader.py")], check=True)


def main():
    portable = "--portable" in sys.argv
    ffmpeg = engine.find_ffmpeg()
    node = engine.find_node()
    if not ffmpeg or not node:
        sys.exit("ffmpeg o node non trovati (servono per includerli nel pacchetto)")
    BUILD.mkdir(exist_ok=True)
    ico, ver = BUILD / "icon.ico", BUILD / "version.txt"
    make_icon(ico)
    make_version_file(ver)

    if portable:
        pyinstaller(True, ffmpeg, node, ico, ver)
        exe = DIST / "VideoDownloader.exe"
        print(f"\nFatto: {exe}  ({exe.stat().st_size / 1_048_576:.0f} MB)")
        return

    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup 6 non trovato: installalo da https://jrsoftware.org/isdl.php "
                 "(oppure: winget install JRSoftware.InnoSetup)")
    # Versione "a cartella": avvio immediato, meno falsi positivi antivirus, DLL Qt sostituibili (LGPL)
    pyinstaller(False, ffmpeg, node, ico, ver)
    pkg = BUILD / "package"
    shutil.rmtree(pkg, ignore_errors=True)
    shutil.copytree(DIST / "VideoDownloader", pkg)
    shutil.copy2(HERE / "LICENSE.txt", pkg / "LICENSE.txt")
    shutil.copytree(HERE / "licenses", pkg / "licenses")
    # sorgente dell'app: permette di ricompilarla con un'altra versione di Qt (LGPL v3, sez. 4)
    src = pkg / "source"
    (src / "installer").mkdir(parents=True)
    # TUTTI i moduli .py del progetto (video_downloader, common, theme, icons, engine, widgets, dialogs, ui, build)
    modules = sorted(HERE.glob("*.py"))
    required = {"video_downloader", "common", "theme", "icons", "engine", "widgets", "dialogs", "ui", "build"}
    missing = required - {m.stem for m in modules}
    if missing:
        sys.exit(f"Moduli mancanti: {sorted(missing)}")
    for m in modules:
        shutil.copy2(m, src / m.name)
    for name in ("Video Downloader.pyw", "LICENSE.txt", "README.md"):
        shutil.copy2(HERE / name, src / name)
    for p in (HERE / "installer").iterdir():
        shutil.copy2(p, src / "installer" / p.name)
    shutil.copytree(HERE / "licenses", src / "licenses")
    subprocess.run([iscc, f"/DAppVersion={common.APP_VERSION}", f"/DSrcDir={pkg}", "/Qp",
                    str(HERE / "installer" / "VideoDownloader.iss")], check=True)
    setup = DIST / f"VideoDownloader-Setup-{common.APP_VERSION}.exe"
    print(f"\nFatto: {setup}  ({setup.stat().st_size / 1_048_576:.0f} MB)")


if __name__ == "__main__":
    main()
