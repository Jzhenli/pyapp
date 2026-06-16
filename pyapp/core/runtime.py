"""Python 运行时管理模块 - 下载和管理各平台 Python 运行时"""

import shutil
import tarfile
import zipfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from .cache import CacheManager
from .errors import DownloadError, VerificationError
from .logger import get_logger


@dataclass
class RuntimeSource:
    """运行时下载源"""
    url_template: str
    strip_components: int = 1


# 各平台 Python 运行时下载源
RUNTIME_SOURCES = {
    "windows": RuntimeSource(
        url_template="https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
    ),
    "linux": RuntimeSource(
        url_template=(
            "https://github.com/indygreg/python-build-standalone/releases/download/"
            "{version}/cpython-{version}+{build}-x86_64-unknown-linux-gnu-install_only.tar.gz"
        ),
        strip_components=1,
    ),
}

# 已知的 PBS 版本映射
PBS_VERSIONS = {
    "3.12.1": "20240107",
    "3.11.7": "20240107",
    "3.10.13": "20240107",
    "3.12.4": "20240713",
    "3.11.9": "20240713",
    "3.10.14": "20240713",
}


class RuntimeManager:
    """Python 运行时管理器"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache = CacheManager(cache_dir)
        self.logger = get_logger()

    def get_runtime(self, platform: str, version: str, target_dir: Path) -> Path:
        """获取 Python 运行时"""
        cache_key = f"runtime-{platform}-{version}"
        cached_path = self.cache.get(cache_key)

        if cached_path:
            self.logger.info(f"Using cached runtime: {cached_path}")
            self.logger.info(f"Extracting to: {target_dir}")
            return self._extract_runtime(cached_path, target_dir, platform)

        # 显示下载详情
        source = RUNTIME_SOURCES.get(platform)
        if platform == "linux":
            build = PBS_VERSIONS.get(version, "20240107")
            url = source.url_template.format(version=version, build=build)
        else:
            url = source.url_template.format(version=version)

        self.logger.info(f"Downloading Python {version} for {platform}...")
        self.logger.info(f"  URL: {url}")
        self.logger.info(f"  Cache dir: {self.cache.runtimes_dir}")
        self.logger.info(f"  Target dir: {target_dir}")

        downloaded_file = self._download_runtime(platform, version)

        if not self._verify_runtime(platform, downloaded_file):
            raise VerificationError(f"Runtime verification failed for {platform}")

        cached_path = self.cache.put(cache_key, downloaded_file)
        return self._extract_runtime(cached_path, target_dir, platform)

    def _download_runtime(self, platform: str, version: str) -> Path:
        """下载运行时文件"""
        source = RUNTIME_SOURCES.get(platform)
        if not source:
            raise ValueError(f"Unsupported platform: {platform}")

        if platform == "linux":
            build = PBS_VERSIONS.get(version, "20240107")
            url = source.url_template.format(version=version, build=build)
        else:
            url = source.url_template.format(version=version)

        temp_file = self.cache.temp_dir / f"python-{platform}-{version}.tmp"

        try:
            request = Request(url, headers={"User-Agent": "PyApp-CLI/1.0"})
            with urlopen(request, timeout=300) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0

                # 显示文件大小
                if total_size:
                    size_mb = total_size / (1024 * 1024)
                    self.logger.info(f"  File size: {size_mb:.1f} MB")
                self.logger.info(f"  Saving to: {temp_file}")

                with open(temp_file, "wb") as f:
                    last_progress = -1
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            progress = int((downloaded / total_size) * 100)
                            downloaded_mb = downloaded / (1024 * 1024)
                            # 每 10% 输出一次进度
                            if progress >= last_progress + 10:
                                self.logger.info(f"  Progress: {progress}% ({downloaded_mb:.1f}/{size_mb:.1f} MB)")
                                last_progress = progress

                self.logger.success(f"Download complete: {temp_file}")
                return temp_file

        except URLError as e:
            raise DownloadError(f"Failed to download runtime: {e}")

    def _verify_runtime(self, platform: str, file_path: Path) -> bool:
        """验证运行时文件完整性"""
        try:
            if platform == "windows":
                with zipfile.ZipFile(file_path, "r") as zf:
                    return "python.exe" in zf.namelist()
            else:
                with tarfile.open(file_path, "r:gz") as tf:
                    return any("bin/python" in n for n in tf.getnames())
        except Exception as e:
            self.logger.error(f"Runtime verification error: {e}")
            return False

    def _extract_runtime(self, archive_path: Path, target_dir: Path, platform: str) -> Path:
        """解压运行时"""
        target_dir.mkdir(parents=True, exist_ok=True)

        if platform == "windows":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(target_dir)
        else:
            source = RUNTIME_SOURCES[platform]
            with tarfile.open(archive_path, "r:gz") as tf:
                for member in tf.getmembers():
                    parts = member.name.split("/")
                    if len(parts) > source.strip_components:
                        member.name = "/".join(parts[source.strip_components:])
                        tf.extract(member, target_dir)

        self.logger.success(f"Runtime extracted to {target_dir}")
        return target_dir
