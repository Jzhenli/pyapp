"""平台抽象基类"""

import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from ..core.config import load_config
from ..core.logger import get_logger


@dataclass
class BuildResult:
    """构建结果"""
    success: bool
    output_path: Optional[Path] = None
    error_message: str = ""


class BasePlatform(ABC):
    """平台基类"""

    name: str = ""
    description: str = ""

    def __init__(self):
        self.logger = get_logger()

    @abstractmethod
    def check_environment(self) -> tuple:
        """
        检查环境是否满足要求

        Returns:
            (是否满足, 缺失项列表)
        """
        pass

    @abstractmethod
    def create(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """
        创建平台项目结构

        Args:
            project_dir: 项目根目录
            config: 解析后的配置
        """
        pass

    @abstractmethod
    def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug") -> BuildResult:
        """
        构建平台包

        Args:
            project_dir: 项目根目录
            config: 解析后的配置
            build_type: debug 或 release

        Returns:
            构建结果
        """
        pass

    @abstractmethod
    def run(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """
        运行应用
        """
        pass

    @abstractmethod
    def dev(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """
        开发模式（文件监听 + 热重载）
        """
        pass

    @abstractmethod
    def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
        """
        打包发布版
        """
        pass

    # ===== 公共方法 =====

    def install_dependencies(self, project_dir: Path, config: Dict[str, Any], platform: str) -> Path:
        """
        安装 pip 依赖到 bundles/{platform}/{app_name}-{version}/app_packages/

        Args:
            project_dir: 项目根目录
            config: 解析后的配置
            platform: 平台名称 (android/windows/linux)

        Returns:
            app_packages 目录路径
        """
        # 从配置读取依赖
        dependencies = config.get("project", {}).get("dependencies", [])
        platform_config = config.get("tool", {}).get("pyapp", {}).get(platform, {})
        platform_dependencies = platform_config.get("dependencies", [])

        # 合并依赖（平台特定依赖优先）
        all_dependencies = self._merge_dependencies(dependencies, platform_dependencies)

        # 获取版本号目录
        app_name = self.get_app_name(config)
        version = self.get_app_version(config)
        version_dir = f"{app_name}-{version}"

        target = project_dir / "bundles" / platform / version_dir / "app_packages"
        target.mkdir(parents=True, exist_ok=True)

        if not all_dependencies:
            self.logger.info("No dependencies to install")
            return target

        # 根据平台选择不同的安装策略
        if platform == "android":
            self._install_android_dependencies(all_dependencies, target, platform_config)
        else:
            self._install_native_dependencies(all_dependencies, target, platform)

        return target

    def _merge_dependencies(self, global_deps: List[str], platform_deps: List[str]) -> List[str]:
        """合并全局依赖和平台依赖，平台依赖优先"""
        import re

        def _extract_dep_name(dep: str) -> str:
            """从 PEP 508 依赖字符串中提取包名"""
            match = re.match(r'^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)', dep)
            return match.group(1).lower() if match else dep.split("[")[0].split(">=")[0].split("==")[0].split("<")[0].strip().lower()

        merged = {}
        for dep in global_deps:
            name = _extract_dep_name(dep)
            merged[name] = dep

        for dep in platform_deps:
            name = _extract_dep_name(dep)
            merged[name] = dep  # 覆盖或追加

        return list(merged.values())

    def _install_android_dependencies(self, dependencies: list, target: Path, platform_config: dict) -> None:
        """安装 Android 平台依赖（考虑 Chaquopy 兼容性）"""
        # 使用 Chaquopy 的 PyPI 仓库
        extra_index_url = platform_config.get("extra_index_url",
            "https://chaquo.com/chaquopy/maven/org/python/pypi/simple")

        # 安装依赖
        cmd = [
            sys.executable, "-m", "pip", "install"
        ] + dependencies + [
            "--target", str(target),
            "--extra-index-url", extra_index_url,
        ]

        self.logger.info(f"Installing {len(dependencies)} dependencies for Android...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.warning(f"Some dependencies failed to install, trying individually...")
            # 如果安装失败，尝试逐个安装
            for dep in dependencies:
                subprocess.run([
                    sys.executable, "-m", "pip", "install", dep,
                    "--target", str(target),
                    "--extra-index-url", extra_index_url,
                ], check=False)

    def _install_native_dependencies(self, dependencies: list, target: Path, platform: str) -> None:
        """安装 Windows/Linux 平台依赖"""
        current_platform = sys.platform
        is_cross_compile = (
            (platform == "windows" and current_platform != "win32") or
            (platform == "linux" and current_platform != "linux")
        )

        if is_cross_compile:
            self.logger.warning(
                f"Cross-platform compilation detected (building {platform} on {current_platform})"
            )
            self.logger.warning("Some packages with C extensions may not work correctly")
            cmd = [
                sys.executable, "-m", "pip", "install"
            ] + dependencies + [
                "--target", str(target),
                "--only-binary=:all:",
            ]
        else:
            cmd = [
                sys.executable, "-m", "pip", "install"
            ] + dependencies + [
                "--target", str(target),
            ]

        self.logger.info(f"Installing {len(dependencies)} dependencies for {platform}...")
        subprocess.run(cmd, check=True)

    def sync_source_code(self, project_dir: Path, platform: str, config: Dict[str, Any] = None) -> Path:
        """
        同步 Python 源码到 bundles/{platform}/{app_name}-{version}/app/

        源: src/
        目标: bundles/{platform}/{app_name}-{version}/app/

        这样 src/my_app/ 会变成 app/my_app/

        Args:
            project_dir: 项目根目录
            platform: 平台名称
            config: 配置字典（用于获取版本号）

        Returns:
            目标目录路径
        """
        src_dir = project_dir / "src"

        # 获取版本号目录
        if config:
            app_name = self.get_app_name(config)
            version = self.get_app_version(config)
            version_dir = f"{app_name}-{version}"
        else:
            version_dir = "app"

        target_dir = project_dir / "bundles" / platform / version_dir / "app"

        if target_dir.exists():
            shutil.rmtree(target_dir)

        shutil.copytree(src_dir, target_dir)
        self.logger.info(f"Synced source code → {target_dir}")
        return target_dir

    def sync_frontend_dist(self, project_dir: Path, platform: str, config: Dict[str, Any] = None) -> Optional[Path]:
        """
        同步前端编译产物到打包目录

        源: frontend/dist/
        目标: bundles/{platform}/{app_name}-{version}/app/{app_module}/resources/static/

        Args:
            project_dir: 项目根目录
            platform: 平台名称
            config: 配置字典

        Returns:
            目标目录路径，如果源不存在则返回 None
        """
        from ..core.builder import sync_frontend_dist

        try:
            app_config = load_config(project_dir)
            app_module = app_config.pyapp.app_module
            app_name = app_config.project.name
            version = app_config.project.version
        except Exception:
            # 配置加载失败时，尝试从目录结构推断
            src_dir = project_dir / "src"
            packages = [d for d in src_dir.iterdir()
                       if d.is_dir() and (d / "__init__.py").exists()]
            app_module = packages[0].name if packages else "app"
            app_name = config.get("project", {}).get("name", "app") if config else "app"
            version = config.get("project", {}).get("version", "0.1.0") if config else "0.1.0"

        version_dir = f"{app_name}-{version}"
        return sync_frontend_dist(project_dir, platform, app_module, version_dir)

    def get_python_version(self, config: Dict[str, Any]) -> str:
        """获取 Python 版本"""
        return config.get("tool", {}).get("pyapp", {}).get("python_version", "3.12.1")

    def get_app_version(self, config: Dict[str, Any]) -> str:
        """获取应用版本"""
        return config.get("project", {}).get("version", "0.1.0")

    def get_app_name(self, config: Dict[str, Any]) -> str:
        """获取应用名称"""
        return config.get("project", {}).get("name", "app")

    def get_app_module(self, config: Dict[str, Any]) -> str:
        """获取应用模块名"""
        return config.get("tool", {}).get("pyapp", {}).get("app_module", "app")

    def get_port(self, config: Dict[str, Any]) -> int:
        """获取应用端口"""
        return config.get("tool", {}).get("pyapp", {}).get("port", 18080)

    def ensure_dist_dir(self, project_dir: Path) -> Path:
        """确保 dist 目录存在"""
        dist_dir = project_dir / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        return dist_dir
