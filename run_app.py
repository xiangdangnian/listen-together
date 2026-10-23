import os
import sys
from pathlib import Path


def _prepare_frozen_runtime() -> None:
    if not getattr(sys, "frozen", False):
        return
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for relative in ("", "PySide6", "shiboken6"):
        directory = root / relative
        if directory.is_dir():
            os.add_dll_directory(str(directory))
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get(
                "PATH", ""
            )
    plugin_path = root / "PySide6" / "plugins"
    if plugin_path.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_path))


_prepare_frozen_runtime()

from listen_together.app import main


raise SystemExit(main())

