"""设备管理模块 - adb/ssh 设备操作"""

import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
from .logger import get_logger


class DeviceManager:
    """设备管理器"""

    def __init__(self):
        self.logger = get_logger()

    # ===== Android 设备操作 =====

    def adb_devices(self) -> List[str]:
        """列出已连接的 Android 设备"""
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            self.logger.error("adb devices failed")
            return []

        lines = result.stdout.strip().split("\n")[1:]  # 跳过首行 "List of devices attached"
        devices = []
        for line in lines:
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def adb_install(self, apk_path: Path, device: Optional[str] = None) -> bool:
        """安装 APK 到设备"""
        cmd = ["adb"]
        if device:
            cmd.extend(["-s", device])
        cmd.extend(["install", "-r", str(apk_path)])

        self.logger.info(f"Installing {apk_path.name}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.error(f"Install failed: {result.stderr}")
            return False
        self.logger.success("APK installed successfully")
        return True

    def adb_start_app(self, package_name: str, device: Optional[str] = None) -> bool:
        """启动 Android 应用"""
        cmd = ["adb"]
        if device:
            cmd.extend(["-s", device])
        cmd.extend([
            "shell", "am", "start",
            "-n", f"{package_name}/.MainActivity"
        ])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.error(f"Start app failed: {result.stderr}")
            return False
        self.logger.success(f"App {package_name} started")
        return True

    def adb_force_stop(self, package_name: str, device: Optional[str] = None) -> bool:
        """强制停止 Android 应用"""
        cmd = ["adb"]
        if device:
            cmd.extend(["-s", device])
        cmd.extend(["shell", "am", "force-stop", package_name])

        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0

    def adb_push(self, local_path: Path, remote_path: str, device: Optional[str] = None) -> bool:
        """推送文件到 Android 设备"""
        cmd = ["adb"]
        if device:
            cmd.extend(["-s", device])
        cmd.extend(["push", str(local_path), remote_path])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.error(f"Push failed: {result.stderr}")
            return False
        return True

    def adb_connect(self, address: str) -> bool:
        """通过 WiFi 连接 Android 设备"""
        self.logger.info(f"Connecting to {address}...")
        result = subprocess.run(
            ["adb", "connect", address],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            self.logger.error(f"Connect failed: {result.stderr}")
            return False
        self.logger.success(f"Connected to {address}")
        return True

    def adb_logcat(self, package_name: str, device: Optional[str] = None) -> subprocess.Popen:
        """获取 Android 应用日志"""
        cmd = ["adb"]
        if device:
            cmd.extend(["-s", device])
        cmd.extend(["logcat", "--pid=$(adb shell pidof %s)" % package_name])
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # ===== SSH/Linux 设备操作 =====

    def ssh_exec(self, host: str, command: str, user: str = "root") -> Tuple[bool, str]:
        """通过 SSH 执行远程命令"""
        cmd = ["ssh", f"{user}@{host}", command]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0, result.stderr if result.returncode != 0 else result.stdout

    def scp_push(self, local_path: Path, remote_path: str, host: str, user: str = "root") -> bool:
        """通过 SCP 推送文件"""
        cmd = ["scp", str(local_path), f"{user}@{host}:{remote_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.error(f"SCP failed: {result.stderr}")
            return False
        return True

    def systemctl_start(self, service_name: str, host: str, user: str = "root") -> bool:
        """远程启动 systemd 服务"""
        success, _ = self.ssh_exec(host, f"systemctl start {service_name}", user)
        if success:
            self.logger.success(f"Service {service_name} started on {host}")
        else:
            self.logger.error(f"Failed to start service {service_name}")
        return success

    def systemctl_restart(self, service_name: str, host: str, user: str = "root") -> bool:
        """远程重启 systemd 服务"""
        success, _ = self.ssh_exec(host, f"systemctl restart {service_name}", user)
        return success

    def systemctl_stop(self, service_name: str, host: str, user: str = "root") -> bool:
        """远程停止 systemd 服务"""
        success, _ = self.ssh_exec(host, f"systemctl stop {service_name}", user)
        return success

    # ===== Windows 设备操作 =====

    def restart_windows_app(self, host: str = "127.0.0.1", port: int = 18080) -> bool:
        """通过 HTTP API 重启 Windows 应用"""
        try:
            import requests
        except ImportError:
            # 回退到 urllib
            from urllib.request import urlopen, Request
            from urllib.error import URLError
            try:
                req = Request(f"http://{host}:{port}/api/restart", method="POST", data=b"")
                with urlopen(req, timeout=5) as response:
                    return response.status == 200
            except Exception as e:
                self.logger.error(f"Failed to restart app: {e}")
                return False

        try:
            response = requests.post(f"http://{host}:{port}/api/restart", timeout=5)
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Failed to restart app: {e}")
            return False
