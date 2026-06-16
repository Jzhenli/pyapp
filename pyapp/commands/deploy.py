"""pyapp deploy 命令 - 部署到目标设备"""

from pathlib import Path

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..core.device import DeviceManager
from ..core.errors import BuildError


def deploy_platform(platform: str, target: str, project_dir: Path = None,
                    update_only: bool = False, rollback: str = None):
    """
    部署到目标设备

    Args:
        platform: 平台名称 (android/windows/linux)
        target: 目标设备地址
        project_dir: 项目目录，默认为当前目录
        update_only: 仅推送增量更新
        rollback: 回滚到指定版本
    """
    logger = get_logger()

    if project_dir is None:
        project_dir = Path.cwd()

    # 加载配置
    try:
        config = load_config(project_dir)
        config_dict = config.to_dict()
    except FileNotFoundError:
        raise click.ClickException(
            "pyproject.toml not found. Run 'pyapp init' to create a new project."
        )
    except ValueError as e:
        raise click.ClickException(f"Configuration error: {e}")

    device_manager = DeviceManager()
    app_name = config_dict.get("project", {}).get("name", "app")
    version = config_dict.get("project", {}).get("version", "0.1.0")
    port = config_dict.get("tool", {}).get("pyapp", {}).get("port", 18080)

    try:
        if platform == "android":
            _deploy_android(device_manager, target, project_dir, app_name, version)
        elif platform == "windows":
            _deploy_windows(device_manager, target, project_dir, app_name, version, port)
        elif platform == "linux":
            _deploy_linux(device_manager, target, project_dir, app_name, version, config_dict,
                         update_only, rollback)
        else:
            raise click.ClickException(f"Unknown platform: {platform}")
    except Exception as e:
        logger.error(f"Deploy failed: {e}")
        raise click.ClickException(f"Deploy failed: {e}")


def _deploy_android(device_manager: DeviceManager, target: str, project_dir: Path,
                    app_name: str, version: str):
    """部署到 Android 设备"""
    logger = get_logger()

    # 连接设备
    if not device_manager.adb_connect(target):
        raise click.ClickException(f"Failed to connect to {target}")

    # 查找 APK
    apk_path = project_dir / "dist" / f"{app_name}-{version}.apk"
    if not apk_path.exists():
        raise click.ClickException(f"APK not found: {apk_path}. Run 'pyapp build android' first.")

    # 安装 APK
    # 获取连接后的设备序列号
    devices = device_manager.adb_devices()
    device_serial = devices[0] if devices else None

    if not device_manager.adb_install(apk_path, device=device_serial):
        raise click.ClickException("Failed to install APK")

    logger.success(f"Deployed to Android device at {target}")


def _deploy_windows(device_manager: DeviceManager, target: str, project_dir: Path,
                    app_name: str, version: str, port: int):
    """部署到 Windows 设备"""
    logger = get_logger()

    # 查找 ZIP 包
    zip_path = project_dir / "dist" / f"{app_name}-{version}-windows-x86_64.zip"
    if not zip_path.exists():
        raise click.ClickException(f"Package not found: {zip_path}. Run 'pyapp build windows' first.")

    # SCP 推送到目标
    remote_dir = f"C:/Apps/{app_name}"
    if not device_manager.scp_push(zip_path, remote_dir, target):
        raise click.ClickException(f"Failed to push package to {target}")

    logger.success(f"Deployed to Windows device at {target}")


def _deploy_linux(device_manager: DeviceManager, target: str, project_dir: Path,
                  app_name: str, version: str, config_dict: dict,
                  update_only: bool = False, rollback: str = None):
    """部署到 Linux 设备"""
    logger = get_logger()
    service_name = config_dict.get("tool", {}).get("pyapp", {}).get("linux", {}).get(
        "service_name", app_name.replace("_", "-")
    )

    if rollback:
        # 回滚到指定版本
        logger.info(f"Rolling back to version {rollback} on {target}...")
        success, output = device_manager.ssh_exec(
            target,
            f"curl -X POST http://localhost:18080/api/rollback -d 'version={rollback}'"
        )
        if success:
            logger.success(f"Rolled back to version {rollback}")
        else:
            raise click.ClickException(f"Rollback failed: {output}")
        return

    if update_only:
        # 增量更新
        logger.info(f"Pushing incremental update to {target}...")
        # 创建更新包
        import tempfile
        import zipfile
        from ..core.builder import sync_frontend_dist

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            update_zip = Path(tmp.name)

        with zipfile.ZipFile(update_zip, "w") as zf:
            src_dir = project_dir / "src"
            for py_file in src_dir.rglob("*.py"):
                arcname = str(py_file.relative_to(project_dir / "src"))
                zf.write(py_file, arcname)

        # 推送更新包
        if not device_manager.scp_push(update_zip, f"/tmp/{app_name}-update.zip", target):
            raise click.ClickException("Failed to push update package")

        # 触发更新
        success, output = device_manager.ssh_exec(
            target,
            f"curl -X POST http://localhost:18080/api/update -F 'file=@/tmp/{app_name}-update.zip'"
        )
        if success:
            logger.success("Incremental update deployed")
        else:
            raise click.ClickException(f"Update failed: {output}")

        # 清理临时文件
        update_zip.unlink(missing_ok=True)
        return

    # 完整部署
    tar_path = project_dir / "dist" / f"{app_name}-{version}-linux-x86_64.tar.gz"
    if not tar_path.exists():
        raise click.ClickException(f"Package not found: {tar_path}. Run 'pyapp build linux' first.")

    # SCP 推送
    remote_dir = f"/opt/{service_name}"
    if not device_manager.scp_push(tar_path, f"/tmp/{tar_path.name}", target):
        raise click.ClickException(f"Failed to push package to {target}")

    # 解压和安装
    commands = [
        (f"mkdir -p {remote_dir}", "Failed to create remote directory"),
        (f"tar xzf /tmp/{tar_path.name} -C {remote_dir}", "Failed to extract package"),
        (f"cd {remote_dir} && chmod +x install.sh && ./install.sh", "Failed to run install script"),
        (f"systemctl restart {service_name}", "Failed to restart service"),
    ]

    for cmd, error_msg in commands:
        success, output = device_manager.ssh_exec(target, cmd)
        if not success:
            raise click.ClickException(f"{error_msg}: {output}")

    logger.success(f"Deployed to Linux device at {target}")
