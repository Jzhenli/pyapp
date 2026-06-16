"""缓存管理模块"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class CacheManager:
    """缓存管理器"""

    DEFAULT_CACHE_DIR = Path.home() / ".pyapp" / "cache"
    CACHE_EXPIRE_DAYS = 30

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or self.DEFAULT_CACHE_DIR
        self.runtimes_dir = self.cache_dir / "runtimes"
        self.packages_dir = self.cache_dir / "packages"
        self.temp_dir = self.cache_dir / "temp"
        self.metadata_file = self.cache_dir / "metadata.json"

        self.runtimes_dir.mkdir(parents=True, exist_ok=True)
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict[str, Any]:
        if self.metadata_file.exists():
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"entries": {}}

    def _save_metadata(self):
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

    def get(self, key: str) -> Optional[Path]:
        """获取缓存项"""
        entry = self.metadata["entries"].get(key)
        if not entry:
            return None

        cached_time = datetime.fromisoformat(entry["timestamp"])
        if datetime.now() - cached_time > timedelta(days=self.CACHE_EXPIRE_DAYS):
            self.delete(key)
            return None

        cached_path = Path(entry["path"])
        return cached_path if cached_path.exists() else None

    def put(self, key: str, source_path: Path) -> Path:
        """添加缓存项"""
        target_dir = self.runtimes_dir if key.startswith("runtime-") else self.packages_dir
        target_path = target_dir / source_path.name

        if target_path.exists():
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()
        shutil.move(str(source_path), str(target_path))

        self.metadata["entries"][key] = {
            "path": str(target_path),
            "timestamp": datetime.now().isoformat(),
            "size": target_path.stat().st_size,
        }
        self._save_metadata()

        return target_path

    def delete(self, key: str) -> bool:
        """删除缓存项"""
        entry = self.metadata["entries"].get(key)
        if not entry:
            return False

        cached_path = Path(entry["path"])
        if cached_path.exists():
            if cached_path.is_dir():
                shutil.rmtree(cached_path)
            else:
                cached_path.unlink()

        del self.metadata["entries"][key]
        self._save_metadata()
        return True

    def clear_all(self):
        """清空所有缓存"""
        for key in list(self.metadata["entries"].keys()):
            self.delete(key)

    def get_cache_size(self) -> int:
        """获取缓存总大小"""
        return sum(e.get("size", 0) for e in self.metadata["entries"].values())
