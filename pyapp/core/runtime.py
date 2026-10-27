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

# 各平台 Python 运行时版本映射
# 格式: 基础版本 -> {平台: (具体版本, 额外信息)}
# Windows: 完整版本号，用于下载 python.org 的 embeddable 包
# Linux: (版本号, PBS build tag)，用于下载 Python Build Standalone
# Android: 只需主版本号，由 Chaquopy 管理
PYTHON_VERSIONS = {
    "3.10": {
        "windows": "3.10.11",
        "linux": ("3.10.20", "20260610"),
        "android": "3.10",
    },
    "3.11": {
        "windows": "3.11.9",
        "linux": ("3.11.15", "20260610"),
        "android": "3.11",
    },
    "3.12": {
        "windows": "3.12.10",
        "linux": ("3.12.13", "20260610"),
        "android": "3.12",
    },
}

# 默认 Python 版本（当配置的版本不存在时使用）
DEFAULT_PYTHON_VERSION = "3.10"

# PBS install_only 运行时中分发场景不需要的目录（相对 runtime 根目录）
# 仅编译期使用的头文件、man 文档和 pkg-config 描述
RUNTIME_PRUNE_DIRS = (
    "include",
    "share",
    "lib/pkgconfig",
)

# Tcl/Tk 原生运行时（与 tkinter 纯 Python 包配套裁剪，glob 模式，相对 runtime 根目录）
RUNTIME_PRUNE_GLOBS = (
    "lib/tcl*",     # Tcl 脚本库 (tcl9.0, tcl9)
    "lib/tk*",      # Tk 脚本库 (tk9.0)
    "lib/libtcl*",  # Tcl 动态库
    "lib/libtk*",   # Tk 动态库
    "lib/itcl*",    # itcl（Tcl OO 扩展）
    "lib/thread*",  # thread（Tcl 线程扩展）
)

# 标准库中分发场景不需要的模块目录（相对 lib/python3.x/）
# 注意：不触碰 encodings 等运行核心；lib-dynload 仅按下方模式选择性移除测试/Tk 扩展
STDLIB_PRUNE_DIRS = (
    "test",        # CPython 自带测试套件（体积最大）
    "idlelib",     # IDLE
    "tkinter",     # GUI，服务端/无头场景不需要
    "turtledemo",
    "lib2to3",
    "ensurepip",
    "venv",
    "pydoc_data",  # pydoc 离线文档数据（pydoc 命令已裁剪）
)

# lib-dynload 中分发场景不需要的扩展模块（glob 模式）
LIB_DYNLOAD_PRUNE_PATTERNS = (
    "_tkinter*",       # Tk C 绑定（tkinter 包已裁剪时为死重）
    "_test*",          # CPython 构建测试扩展
    "_ctypes_test*",   # ctypes 测试扩展
    "xxlimited*",      # C-API 示例扩展（x86_64/aarch64 构建中存在）
    "xxsubtype*",      # C-API 示例扩展
    "_xxtestfuzz*",    # fuzz 测试扩展
)

# 标准库中分发场景不需要的单文件模块（相对 lib/python3.x/）
STDLIB_PRUNE_FILES = (
    "turtle.py",
)

# 标准库中仅编译期使用的目录（glob 模式，相对 lib/python3.x/）
STDLIB_PRUNE_GLOBS = (
    "config-*",    # libpython*.a 静态库 + Makefile
)

# bin 目录中分发场景不需要的辅助脚本（python 本体不动）
BIN_PRUNE_PATTERNS = (
    "idle*",
    "pydoc*",
    "2to3*",
    "python*-config",
    "pip*",        # pip 启动脚本（pip 包已在 site-packages 中裁剪，脚本为死脚本）
)

# site-packages 中可能残留的包管理器（install_only 通常不自带，防御性清理）
SITE_PACKAGES_PRUNE_PATTERNS = (
    "pip*",
    "setuptools*",
    "pkg_resources*",
    "wheel*",
)


class RuntimeManager:
    """Python 运行时管理器"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache = CacheManager(cache_dir)
        self.logger = get_logger()

    @staticmethod
    def get_platform_version(base_version: str, platform: str) -> tuple:
        """
        根据基础版本和平台获取具体的版本信息

        Args:
            base_version: 基础版本号，如 "3.10" 或 "3.10.11"
            platform: 平台名称 (windows, linux, android)

        Returns:
            tuple: (version, extra_info)
                - windows: ("3.10.11", None)
                - linux: ("3.10.20", "20260610")
                - android: ("3.10", None)
        """
        # 提取主版本号 (如 "3.10.11" -> "3.10")
        major_minor = ".".join(base_version.split(".")[:2])

        # 查找映射表
        if major_minor in PYTHON_VERSIONS:
            platform_info = PYTHON_VERSIONS[major_minor].get(platform)
            if platform_info:
                if isinstance(platform_info, tuple):
                    return platform_info  # (version, build_tag)
                return (platform_info, None)  # (version, None)

        # 未找到映射，返回原始版本
        return (base_version, None)

    def _get_default_linux_version(self) -> tuple:
        """
        获取默认的 Linux 版本信息

        Returns:
            tuple: (version, build) 或 None
        """
        default_info = PYTHON_VERSIONS.get(DEFAULT_PYTHON_VERSION, {}).get("linux")
        if isinstance(default_info, tuple):
            return default_info
        return None

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

        # 解析版本信息
        actual_version = version
        build = None
        if platform == "linux":
            # 从 PYTHON_VERSIONS 获取版本和 build tag
            major_minor = ".".join(version.split(".")[:2])
            if major_minor in PYTHON_VERSIONS:
                linux_info = PYTHON_VERSIONS[major_minor].get("linux")
                if isinstance(linux_info, tuple):
                    actual_version, build = linux_info
                else:
                    # 未找到 Linux 配置，使用默认版本
                    self.logger.warning(
                        f"Python {major_minor} Linux runtime not found, "
                        f"using default version {DEFAULT_PYTHON_VERSION}"
                    )
                    default_info = self._get_default_linux_version()
                    if default_info:
                        actual_version, build = default_info
            else:
                # 版本不在映射表中，使用默认版本
                self.logger.warning(
                    f"Python {version} not in version mapping, "
                    f"using default version {DEFAULT_PYTHON_VERSION}"
                )
                default_info = self._get_default_linux_version()
                if default_info:
                    actual_version, build = default_info

        cache_key = f"runtime-{runtime_key}-{actual_version}"
        cached_path = self.cache.get(cache_key)

        if cached_path:
            self.logger.info(f"Using cached runtime: {cached_path}")
            self.logger.info(f"Extracting to: {target_dir}")
            return self._extract_runtime(cached_path, target_dir, runtime_key)

        # 检查 runtimes 目录是否有手动放置的文件
        expected_filename = self._get_runtime_filename(runtime_key, actual_version, build)
        manual_file = self.cache.runtimes_dir / expected_filename
        if manual_file.exists() and manual_file.stat().st_size > 1_000_000:
            self.logger.info(f"Found manually placed runtime: {manual_file}")
            self.logger.info(f"File size: {manual_file.stat().st_size / (1024*1024):.1f} MB")
            # 注册缓存条目（不移动文件）
            cached_path = self.cache.register(cache_key, manual_file)
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

        # 移动到 runtimes 目录，创建缓存条目
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

        # 使用原始文件名 + .tmp 后缀作为 temp 文件名
        filename = self._get_runtime_filename(runtime_key, version, build)
        temp_file = self.cache.temp_dir / f"{filename}.tmp"

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

    def _get_runtime_filename(self, runtime_key: str, version: str, build: str = None) -> str:
        """
        获取运行时文件的预期文件名

        Args:
            runtime_key: 运行时标识 (windows, linux-x86_64, linux-aarch64, linux-armv7l)
            version: Python 版本
            build: PBS build tag（仅 Linux 需要）

        Returns:
            str: 预期的文件名
        """
        if runtime_key == "windows":
            return f"python-{version}-embed-amd64.zip"
        elif runtime_key.startswith("linux"):
            # Linux 使用 PBS，文件名格式: cpython-{version}+{build}-{arch}-install_only_stripped.tar.gz
            arch_map = {
                "linux-x86_64": "x86_64-unknown-linux-gnu",
                "linux-aarch64": "aarch64-unknown-linux-gnu",
                "linux-armv7l": "armv7-unknown-linux-gnueabihf",
            }
            arch = arch_map.get(runtime_key, runtime_key.replace("linux-", ""))
            return f"cpython-{version}+{build}-{arch}-install_only_stripped.tar.gz"
        else:
            return f"python-{runtime_key}-{version}.tar.gz"

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

    def prune_runtime(self, runtime_dir: Path) -> float:
        """
        裁剪 PBS install_only 运行时中分发场景不需要的内容

        仅删除 test/idlelib/tkinter/头文件/静态库等明确的非必需项，
        不触碰 lib-dynload、encodings、libpython 动态库等运行核心。

        Args:
            runtime_dir: 运行时根目录 (bundles/linux/runtime)

        Returns:
            float: 释放的空间（MB），无可裁剪内容时为 0
        """
        runtime_dir = Path(runtime_dir)
        if not runtime_dir.is_dir():
            return 0.0

        freed_bytes = 0

        def _size(path: Path) -> int:
            try:
                if path.is_symlink():
                    return 0
                if path.is_file():
                    return path.stat().st_size
                return sum(
                    f.stat().st_size
                    for f in path.rglob("*")
                    if f.is_file() and not f.is_symlink()
                )
            except OSError:
                return 0

        def _remove(path: Path) -> None:
            nonlocal freed_bytes
            try:
                if not path.exists() and not path.is_symlink():
                    return
                freed_bytes += _size(path)
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError as e:
                self.logger.warning(f"Failed to prune {path}: {e}")

        # 1. 根目录级别：头文件 / man 文档 / pkgconfig / Tcl-Tk 原生运行时
        for rel in RUNTIME_PRUNE_DIRS:
            _remove(runtime_dir / rel)
        for pattern in RUNTIME_PRUNE_GLOBS:
            for p in runtime_dir.glob(pattern):
                _remove(p)

        # 2. 标准库级别
        lib_root = runtime_dir / "lib"
        for stdlib_dir in lib_root.glob("python3.*"):
            if not stdlib_dir.is_dir():
                continue
            for name in STDLIB_PRUNE_DIRS:
                _remove(stdlib_dir / name)
            for name in STDLIB_PRUNE_FILES:
                _remove(stdlib_dir / name)
            for pattern in STDLIB_PRUNE_GLOBS:
                for p in stdlib_dir.glob(pattern):
                    _remove(p)
            # lib-dynload 中的 Tk 绑定与测试扩展
            lib_dynload = stdlib_dir / "lib-dynload"
            if lib_dynload.is_dir():
                for pattern in LIB_DYNLOAD_PRUNE_PATTERNS:
                    for p in lib_dynload.glob(pattern):
                        _remove(p)
            # site-packages 中可能残留的包管理器
            site_packages = stdlib_dir / "site-packages"
            if site_packages.is_dir():
                for pattern in SITE_PACKAGES_PRUNE_PATTERNS:
                    for p in site_packages.glob(pattern):
                        _remove(p)

        # 3. bin 目录中的辅助脚本（python 本体不动）
        bin_dir = runtime_dir / "bin"
        if bin_dir.is_dir():
            for pattern in BIN_PRUNE_PATTERNS:
                for p in bin_dir.glob(pattern):
                    _remove(p)

        freed_mb = freed_bytes / (1024 * 1024)
        if freed_mb > 0:
            self.logger.success(f"Runtime pruned, saved {freed_mb:.1f} MB")
        return freed_mb
