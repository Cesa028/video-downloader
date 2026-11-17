import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
runpy.run_path(str(Path(__file__).resolve().with_name("video_downloader.py")), run_name="__main__")
