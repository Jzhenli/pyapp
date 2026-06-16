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
    if not jdk_dir.exists():
        logger.info("Installing JDK 17...")
        _install_jdk(jdk_dir)
    else:
        logger.info(f"JDK already installed at {jdk_dir}")

    # 2. 安装 Android SDK
    sdk_dir = Path.home() / ".android-sdk"
    if not sdk_dir.exists():
        logger.info("Installing Android SDK...")
        _install_android_sdk(sdk_dir)
    else:
        logger.info(f"Android SDK already installed at {sdk_dir}")

    # 3. 设置环境变量
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
        result = subprocess.run(["gcc", "--version"], capture_output=True, text=True)
        gcc_found = result.returncode == 0
    except FileNotFoundError:
        gcc_found = False

    if gcc_found:
        logger.info("MinGW-w64 (gcc) is already installed")
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

    jdk_dir.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        # Windows: 下载 JDK zip
        url = "https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_windows-x64_bin.zip"
        archive_name = "jdk-17.zip"
    else:
        # Linux: 下载 JDK tar.gz
        url = "https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz"
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

        # 查找解压后的目录
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

    sdk_dir.mkdir(parents=True, exist_ok=True)

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
        result = subprocess.run(
            [str(sdkmanager), "--sdk_root=" + str(sdk_dir), package],
            capture_output=True,
            text=True,
            env=env,
            input="y\n",  # Accept license
        )
        if result.returncode != 0:
            logger.warning(f"  Failed to install {package}: {result.stderr}")
