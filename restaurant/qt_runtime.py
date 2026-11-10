"""明确设置 Unicode 插件路径，避免 Qt5 在中文虚拟环境路径中定位失败。"""

from pathlib import Path
import PyQt5
from PyQt5.QtCore import QCoreApplication


def configure_qt():
    plugins = Path(PyQt5.__file__).resolve().parent / "Qt5" / "plugins"
    if plugins.is_dir():
        QCoreApplication.setLibraryPaths([str(plugins)])
