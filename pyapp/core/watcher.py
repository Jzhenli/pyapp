"""文件监听模块 - 基于 watchdog 的文件变化监听"""

import time
from pathlib import Path
from typing import Callable, Optional, Set
from .logger import get_logger

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


class SourceChangeHandler(FileSystemEventHandler if HAS_WATCHDOG else object):
    """Python 源码变化处理器"""

    def __init__(self, callback: Callable[[str], None], watch_extensions: Optional[Set[str]] = None):
        if HAS_WATCHDOG:
            super().__init__()
        self.callback = callback
        self.watch_extensions = watch_extensions or {".py", ".yaml", ".yml", ".json", ".toml"}
        self.logger = get_logger()
        self._last_trigger = 0
        self._debounce_seconds = 0.5

    def on_any_event(self, event: "FileSystemEvent"):
        """处理文件变化事件"""
        if event.is_directory:
            return

        src_path = Path(event.src_path)
        if src_path.suffix not in self.watch_extensions:
            return

        # 防抖：避免短时间内多次触发
        now = time.time()
        if now - self._last_trigger < self._debounce_seconds:
            return
        self._last_trigger = now

        self.logger.info(f"File changed: {src_path}")
        self.callback(str(src_path))


class FileWatcher:
    """文件监听器"""

    def __init__(self, watch_dir: Path, callback: Callable[[str], None],
                 watch_extensions: Optional[Set[str]] = None):
        """
        初始化文件监听器

        Args:
            watch_dir: 监听目录
            callback: 文件变化回调函数
            watch_extensions: 监听的文件扩展名集合
        """
        self.watch_dir = watch_dir
        self.callback = callback
        self.watch_extensions = watch_extensions
        self.logger = get_logger()
        self._observer = None

    def start(self):
        """启动文件监听"""
        if not HAS_WATCHDOG:
            self.logger.warning("watchdog not installed, file watching disabled")
            self.logger.warning("Install with: pip install watchdog")
            return

        handler = SourceChangeHandler(self.callback, self.watch_extensions)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_dir), recursive=True)
        self._observer.start()
        self.logger.info(f"Watching {self.watch_dir} for changes...")

    def stop(self):
        """停止文件监听"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self.logger.info("File watcher stopped")

    def is_running(self) -> bool:
        """检查监听器是否在运行"""
        return self._observer is not None and self._observer.is_alive()

    def wait(self):
        """阻塞等待（用于主线程）"""
        if self._observer:
            try:
                while self._observer.is_alive():
                    self._observer.join(1)
            except KeyboardInterrupt:
                self.logger.info("File watcher interrupted by user")
                self.stop()
        else:
            # 无 watchdog 时，使用简单阻塞保持进程存活
            self.logger.info("File watching not available. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.logger.info("Stopped by user")
