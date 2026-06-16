"""Python 运行时管理模块 - 下载和管理各平台 Python 运行时"""

import shutil
import tarfile
import zipfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict
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
# 支持多架构：x86_64, aarch64 (ARM64), armv7l (ARM32)
# Linux 使用 stripped 版本，体积更小
# 注意：PBS 已迁移到 astral-sh，文件名格式为 install_only_stripped.tar.gz
RUNTIME_SOURCES: Dict[str, RuntimeSource] = {
    "windows": RuntimeSource(
        url_template="https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
    ),
    "linux-x86_64": RuntimeSource(
        url_template=(
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
            "{build}/cpython-{version}+{build}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
        ),
        strip_components=1,
    ),
    "linux-aarch64": RuntimeSource(
        url_template=(
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
            "{build}/cpython-{version}+{build}-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz"
        ),
        strip_components=1,
    ),
    "linux-armv7l": RuntimeSource(
        url_template=(
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
            "{build}/cpython-{version}+{build}-armv7-unknown-linux-gnueabihf-install_only_stripped.tar.gz"
        ),
        strip_components=1,
    ),
}

# 已知的 PBS 版本映射 (Python 版本 -> PBS Release Tag)
# 格式: "Python版本": "PBS Release Tag"
PBS_VERSIONS = {
    # Python 3.10
    "3.10.20": "20260610",
    "3.10.14": "20240713",
    "3.10.13": "20240107",
    "3.10.11": "20240107",  # 兼容旧配置
    # Python 3.11
    "3.11.9": "20240713",
    "3.11.7": "20240107",
    # Python 3.12
    "3.12.4": "20240713",
    "3.12.1": "20240107",
}

# 默认 Python 版本（当配置的版本不存在时使用）
PBS_DEFAULT_VERSION = "3.10.20"
PBS_DEFAULT_BUILD = "20260610"


class RuntimeManager:
    """Python 运行时管理器"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache = CacheManager(cache_dir)
        self.logger = get_logger()

    def get_runtime(self, platform: str, version: str, target_dir: Path, arch: str = None) -> Path:
        """
        获取 Python 运行时

        Args:
            platform: 平台名称 (windows, linux)
            version: Python 版本
            target_dir: 目标目录
            arch: 架构 (x86_64, aarch64, armv7l)，仅 Linux 需要
        """
        # 构建 runtime key
        if platform == "linux" and arch:
            runtime_key = f"linux-{arch}"
        else:
            runtime_key = platform

        # 解析 PBS 版本
        actual_version = version
        build = None
        if platform == "linux":
            if version in PBS_VERSIONS:
                build = PBS_VERSIONS[version]
            else:
                # 版本不存在，使用默认版本
                self.logger.warning(
                    f"Python {version} not found in PBS releases, "
                    f"using default version {PBS_DEFAULT_VERSION}"
                )
                actual_version = PBS_DEFAULT_VERSION
                build = PBS_DEFAULT_BUILD

        cache_key = f"runtime-{runtime_key}-{actual_version}"
        cached_path = self.cache.get(cache_key)

        if cached_path:
            self.logger.info(f"Using cached runtime: {cached_path}")
            self.logger.info(f"Extracting to: {target_dir}")
            return self._extract_runtime(cached_path, target_dir, runtime_key)

        # 显示下载详情
        source = RUNTIME_SOURCES.get(runtime_key)
        if not source:
            raise ValueError(f"Unsupported platform/arch: {runtime_key}")

        if platform == "linux":
            url = source.url_template.format(version=actual_version, build=build)
        else:
            url = source.url_template.format(version=actual_version)

        self.logger.info(f"Downloading Python {actual_version} for {runtime_key}...")
        self.logger.info(f"  URL: {url}")
        self.logger.info(f"  Cache dir: {self.cache.runtimes_dir}")
        self.logger.info(f"  Target dir: {target_dir}")

        downloaded_file = self._download_runtime(runtime_key, actual_version, build)

        if not self._verify_runtime(runtime_key, downloaded_file):
            raise VerificationError(f"Runtime verification failed for {runtime_key}")

        cached_path = self.cache.put(cache_key, downloaded_file)
        return self._extract_runtime(cached_path, target_dir, runtime_key)

    def _download_runtime(self, runtime_key: str, version: str, build: str = None) -> Path:
        """下载运行时文件"""
        source = RUNTIME_SOURCES.get(runtime_key)
        if not source:
            raise ValueError(f"Unsupported platform/arch: {runtime_key}")

        if runtime_key.startswith("linux"):
            url = source.url_template.format(version=version, build=build)
        else:
            url = source.url_template.format(version=version)

        temp_file = self.cache.temp_dir / f"python-{runtime_key}-{version}.tmp"

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

    def _verify_runtime(self, runtime_key: str, file_path: Path) -> bool:
        """验证运行时文件完整性"""
        try:
            if runtime_key == "windows":
                with zipfile.ZipFile(file_path, "r") as zf:
                    return "python.exe" in zf.namelist()
            else:
                with tarfile.open(file_path, "r:gz") as tf:
                    return any("bin/python" in n for n in tf.getnames())
        except Exception as e:
            self.logger.error(f"Runtime verification error: {e}")
            return False

    def _extract_runtime(self, archive_path: Path, target_dir: Path, runtime_key: str) -> Path:
        """解压运行时"""
        target_dir.mkdir(parents=True, exist_ok=True)

        if runtime_key == "windows":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(target_dir)
        else:
            source = RUNTIME_SOURCES[runtime_key]
            with tarfile.open(archive_path, "r:gz") as tf:
                for member in tf.getmembers():
                    parts = member.name.split("/")
                    if len(parts) > source.strip_components:
                        member.name = "/".join(parts[source.strip_components:])
                        tf.extract(member, target_dir)

        self.logger.success(f"Runtime extracted to {target_dir}")
        return target_dir
