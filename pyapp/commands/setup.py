"""pyapp setup 命令 - 安装平台依赖环境"""

import os
import subprocess
import sys
import zipfile
import tarfile
from pathlib import Path
from typing import Optional

import click

from ..core.logger import get_logger


def setup_platform(platform: str):
    """
    安装平台依赖环境

    Args:
        platform: 平台名称 (android/windows/linux)
    """
    logger = get_logger()

    if platform == "android":
        setup_android()
    elif platform == "windows":
        setup_windows()
    elif platform == "linux":
        setup_linux()
    else:
        raise click.ClickException(f"Unknown platform: {platform}")


def setup_android():
    """安装 Android 开发环境"""
    logger = get_logger()

    logger.info("Setting up Android development environment...")

    # 1. 安装 JDK 17
    jdk_dir = Path.home() / ".android-jdk"
    jdk_valid = jdk_dir.exists() and any(jdk_dir.glob("bin/java*"))
    if not jdk_valid:
        if jdk_dir.exists():
            import shutil
            shutil.rmtree(jdk_dir, ignore_errors=True)
        logger.info("Installing JDK 17...")
        _install_jdk(jdk_dir)
    else:
        logger.info(f"JDK already installed at {jdk_dir}")

    # 2. 安装 Android SDK
    sdk_dir = Path.home() / ".android-sdk"
    sdk_has_cmdline = sdk_dir.exists() and (sdk_dir / "cmdline-tools" / "latest").exists()
    sdk_has_packages = (
        (sdk_dir / "platform-tools").exists()
        and (sdk_dir / "platforms").exists()
        and (sdk_dir / "build-tools").exists()
    )
    if not sdk_has_cmdline:
        if sdk_dir.exists():
            import shutil
            shutil.rmtree(sdk_dir, ignore_errors=True)
        logger.info("Installing Android SDK...")
        _install_android_sdk(sdk_dir)
    elif not sdk_has_packages:
        logger.info("Installing missing SDK packages...")
        _install_sdk_packages(sdk_dir)
    else:
        logger.info(f"Android SDK already installed at {sdk_dir}")

    # 3. 预下载 Gradle 发行版
    # 从模板的 gradle-wrapper.properties 读取版本，避免硬编码不同步
    template_props = Path(__file__).parent.parent / "templates" / "shells" / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties"
    gradle_url = None
    if template_props.exists():
        for line in template_props.read_text(encoding="utf-8").splitlines():
            if line.startswith("distributionUrl="):
                # distributionUrl 使用 \: 转义冒号，需要还原
                gradle_url = line.split("=", 1)[1].strip().replace("\\:", ":")
                break

    if not gradle_url:
        gradle_url = "https://services.gradle.org/distributions/gradle-8.13-bin.zip"

    gradle_filename = gradle_url.split("/")[-1]
    gradle_cache_dir = Path.home() / ".gradle" / "pyapp-cache"
    local_zip = gradle_cache_dir / gradle_filename

    # 检查 Gradle wrapper 自身缓存是否已有该版本
    # wrapper 缓存目录名格式：gradle-8.13-bin（去掉 .zip 后缀）
    gradle_version_name = gradle_filename.replace(".zip", "")
    wrapper_dists = Path.home() / ".gradle" / "wrapper" / "dists"
    gradle_in_wrapper_cache = False
    if wrapper_dists.exists():
        dist_dir = wrapper_dists / gradle_version_name
        if dist_dir.exists():
            for hash_dir in dist_dir.iterdir():
                if hash_dir.is_dir():
                    for uuid_dir in hash_dir.iterdir():
                        if uuid_dir.is_dir() and (uuid_dir / "bin").exists():
                            gradle_in_wrapper_cache = True
                            break
                    if gradle_in_wrapper_cache:
                        break

    if gradle_in_wrapper_cache:
        logger.info(f"Gradle {gradle_version_name} already in wrapper cache")
    elif not local_zip.exists():
        logger.info("Pre-downloading Gradle distribution...")
        _download_gradle(gradle_url, local_zip)
    else:
        logger.info(f"Gradle distribution already cached at {local_zip}")

    # 4. 设置环境变量
    logger.info("")
    logger.info("Environment variables (add to your shell profile):")
    logger.info(f'  JAVA_HOME = "{jdk_dir}"')
    logger.info(f'  ANDROID_HOME = "{sdk_dir}"')

    if os.name == "nt":
        logger.info("")
        logger.info("PowerShell commands:")
        logger.info(f'  $env:JAVA_HOME = "{jdk_dir}"')
        logger.info(f'  $env:ANDROID_HOME = "{sdk_dir}"')
    else:
        logger.info("")
        logger.info("Bash commands:")
        logger.info(f'  export JAVA_HOME="{jdk_dir}"')
        logger.info(f'  export ANDROID_HOME="{sdk_dir}"')

    logger.success("Android environment setup complete")


def setup_windows():
    """安装 Windows 开发环境"""
    logger = get_logger()

    logger.info("Setting up Windows development environment...")

    # 检查 MinGW-w64
    try:
        result = subprocess.run(["g++", "--version"], capture_output=True, text=True)
        gpp_found = result.returncode == 0
    except FileNotFoundError:
        gpp_found = False

    if gpp_found:
        logger.info("MinGW-w64 (g++) is already installed")
    else:
        logger.info("MinGW-w64 not found")
        logger.info("")
        logger.info("To install MinGW-w64:")
        if os.name == "nt":
            logger.info("  Option 1: winget install -e --id MSYS2.MSYS2")
            logger.info("  Option 2: Download from https://www.mingw-w64.org/")
            logger.info("  Option 3: choco install mingw")
        else:
            logger.info("  sudo apt install gcc-mingw-w64-x86-64")

    logger.success("Windows environment setup complete")


def setup_linux():
    """检查 Linux 开发环境"""
    logger = get_logger()

    logger.info("Checking Linux development environment...")

    # 检查常用工具
    tools = ["python3", "pip", "tar", "systemctl"]
    for tool in tools:
        result = subprocess.run(
            ["which", tool] if os.name != "nt" else ["where", tool],
            capture_output=True
        )
        if result.returncode == 0:
            logger.info(f"  {tool}: OK")
        else:
            logger.warning(f"  {tool}: not found")

    logger.success("Linux environment check complete")


def _install_jdk(jdk_dir: Path):
    """安装 JDK"""
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    logger = get_logger()

    if os.name == "nt":
        # Windows: 下载 Adoptium/Temurin JDK 17 (包含完整SSL证书)
        url = "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse"
        archive_name = "jdk-17.zip"
    else:
        # Linux: 下载 Adoptium/Temurin JDK 17 (包含完整SSL证书)
        url = "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse"
        archive_name = "jdk-17.tar.gz"

    archive_path = jdk_dir.parent / archive_name

    try:
        logger.info(f"Downloading JDK from {url}...")
        request = Request(url, headers={"User-Agent": "PyApp-CLI/1.0"})
        with urlopen(request, timeout=300) as response:
            with open(archive_path, "wb") as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)

        logger.info("Extracting JDK...")
        if archive_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(jdk_dir.parent)
        else:
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(jdk_dir.parent)

        # 查找解压后的目录 (OpenJDK: jdk-17.x.x, Temurin: jdk-17.x.x+xx)
        jdk_inner = None
        for d in jdk_dir.parent.iterdir():
            if d.is_dir() and d.name.startswith("jdk-17"):
                jdk_inner = d
                break

        if jdk_inner and jdk_inner != jdk_dir:
            # 重命名为标准名称
            if jdk_dir.exists():
                import shutil
                shutil.rmtree(jdk_dir)
            jdk_inner.rename(jdk_dir)

        # 清理
        archive_path.unlink(missing_ok=True)

        logger.success(f"JDK installed at {jdk_dir}")

    except URLError as e:
        logger.error(f"Failed to download JDK: {e}")
        logger.info("Please install JDK 17 manually:")
        logger.info("  https://adoptium.net/temurin/releases/?version=17")


def _install_android_sdk(sdk_dir: Path):
    """安装 Android SDK"""
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    logger = get_logger()

    # 下载 Android command-line tools
    if os.name == "nt":
        url = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
    elif sys.platform == "darwin":
        url = "https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip"
    else:
        url = "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"

    archive_path = sdk_dir.parent / "cmdline-tools.zip"

    try:
        logger.info(f"Downloading Android command-line tools...")
        request = Request(url, headers={"User-Agent": "PyApp-CLI/1.0"})
        with urlopen(request, timeout=300) as response:
            with open(archive_path, "wb") as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)

        logger.info("Extracting Android SDK...")
        cmdline_dir = sdk_dir / "cmdline-tools" / "latest"
        cmdline_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(sdk_dir / "cmdline-tools")

        # 重新组织目录结构
        extracted = sdk_dir / "cmdline-tools" / "cmdline-tools"
        if extracted.exists():
            import shutil
            for item in extracted.iterdir():
                shutil.move(str(item), str(cmdline_dir / item.name))
            shutil.rmtree(extracted)

        # 安装必要组件
        _install_sdk_packages(sdk_dir)

        # 清理
        archive_path.unlink(missing_ok=True)

        logger.success(f"Android SDK installed at {sdk_dir}")

    except URLError as e:
        logger.error(f"Failed to download Android SDK: {e}")
        logger.info("Please install Android SDK manually:")
        logger.info("  https://developer.android.com/studio#command-tools")


def _install_sdk_packages(sdk_dir: Path):
    """安装 Android SDK 组件"""
    logger = get_logger()

    if os.name == "nt":
        sdkmanager = sdk_dir / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat"
    else:
        sdkmanager = sdk_dir / "cmdline-tools" / "latest" / "bin" / "sdkmanager"

    if not sdkmanager.exists():
        logger.warning("sdkmanager not found, skipping package installation")
        return

    packages = [
        "platform-tools",
        "platforms;android-34",
        "build-tools;34.0.0",
    ]

    logger.info("Installing SDK packages...")

    # 设置 JAVA_HOME
    env = os.environ.copy()
    jdk_dir = Path.home() / ".android-jdk"
    if jdk_dir.exists():
        env["JAVA_HOME"] = str(jdk_dir)

    for package in packages:
        logger.info(f"  Installing {package}...")
        cmd = [str(sdkmanager), f"--sdk_root={sdk_dir}", package]
        if os.name == "nt" and str(sdkmanager).endswith(".bat"):
            cmd = ["cmd", "/c"] + cmd
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            input="y\n",  # Accept license
        )
        if result.returncode != 0:
            error_output = (result.stderr or result.stdout or "unknown error").strip()
            logger.warning(f"  Failed to install {package}: {error_output}")


def _download_gradle(url: str, dest: Path):
    """用 Python 下载 Gradle 发行版（避免 Java SSL 证书问题）"""
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    logger = get_logger()

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        request = Request(url, headers={"User-Agent": "PyApp-CLI/1.0"})
        with urlopen(request, timeout=600) as response:
            total = response.headers.get("Content-Length")
            total_mb = f"{int(total) / 1024 / 1024:.1f}MB" if total else "unknown size"
            logger.info(f"Downloading {dest.name} ({total_mb})...")
            with open(dest, "wb") as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        logger.success(f"Gradle distribution saved to {dest}")
    except URLError as e:
        logger.error(f"Failed to download Gradle: {e}")
        logger.info("Gradle will be downloaded by the wrapper during build (may fail with SSL issues)")
        logger.info("  Manual download: " + url)
        logger.info(f"  Save to: {dest}")
