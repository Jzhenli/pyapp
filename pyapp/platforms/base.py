"""平台抽象基类"""

import json
import re
import shutil
import subprocess
import sys
import platform as pf
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from ..core.config import load_config
from ..core.logger import get_logger
from ..core.errors import BuildError


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
    def build(self, project_dir: Path, config: Dict[str, Any],
              build_type: str = "debug", arch=None) -> BuildResult:
        """
        准备平台构建目录（不打包）

        Args:
            project_dir: 项目根目录
            config: 解析后的配置
            build_type: debug 或 release
            arch: 目标架构
                - Windows: 忽略（固定 x86_64）
                - Linux: str (x86_64/aarch64/armv7l)
                - Android: list (["arm64-v8a"])

        Returns:
            BuildResult.output_path: bundles/{platform}/ 目录路径
        """
        pass

    @abstractmethod
    def run(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """
        运行应用
        """
        pass

    @abstractmethod
    def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
        """
        打包分发文件（不再调用 build()）

        从 bundles/{platform}/build.meta.json 读取 arch 和 build_type。
        """
        pass

    # ===== 构建元数据 =====

    def _write_build_meta(self, bundle_dir: Path, platform: str, config: Dict[str, Any],
                          arch, build_type: str) -> None:
        """写入构建元数据，供 package 阶段读取"""
        meta = {
            "platform": platform,
            "arch": arch if isinstance(arch, str) else (arch or []),
            "build_type": build_type,
            "app_name": self.get_app_name(config),
            "version": self.get_app_version(config),
        }
        (bundle_dir / "build.meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _read_build_meta(self, bundle_dir: Path) -> dict:
        """读取构建元数据"""
        meta_path = bundle_dir / "build.meta.json"
        if not meta_path.exists():
            raise BuildError(
                f"Build metadata not found: {meta_path}",
                "Run 'pyapp build' first"
            )
        return json.loads(meta_path.read_text(encoding="utf-8"))

    # ===== 公共方法 =====

    def install_dependencies(self, project_dir: Path, config: Dict[str, Any], platform: str, arch: str = None) -> Path:
        """
        安装 pip 依赖到 bundles/{platform}/{app_name}-{version}/app_packages/

        Args:
            project_dir: 项目根目录
            config: 解析后的配置
            platform: 平台名称 (android/windows/linux)
            arch: 目标架构 (x86_64, aarch64, armv7l)，用于跨架构编译

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
            self._install_android_dependencies(all_dependencies, target, config, platform)
        else:
            self._install_native_dependencies(all_dependencies, target, platform, arch, config)

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

    def _get_pip_config(self, config: Dict[str, Any], platform: str) -> Dict[str, Any]:
        """
        解析 pip 配置：平台特定配置优先于公共 [tool.pyapp] 配置。

        公共配置写在 [tool.pyapp] 中，三个平台共用；
        平台特定配置（[tool.pyapp.android/windows/linux]）可覆盖公共配置。

        Android 平台默认附带 Chaquopy 源以保证二进制兼容性。
        """
        pyapp_config = config.get("tool", {}).get("pyapp", {})
        platform_config = pyapp_config.get(platform, {})

        # pip_index_url: 平台配置 → 公共配置 → 空字符串
        pip_index_url = platform_config.get("pip_index_url") or pyapp_config.get("pip_index_url", "")

        # pip_extra_index_urls: 平台配置完全覆盖；否则公共配置 + Android 默认源
        common_extra = pyapp_config.get("pip_extra_index_urls", [])
        platform_extra = platform_config.get("pip_extra_index_urls")
        if platform_extra is not None:
            pip_extra_index_urls = list(platform_extra)
        elif common_extra:
            pip_extra_index_urls = list(common_extra)
            if platform == "android":
                chaquo = "https://chaquo.com/pypi-13.1"
                if chaquo not in pip_extra_index_urls:
                    pip_extra_index_urls.append(chaquo)
        else:
            if platform == "android":
                pip_extra_index_urls = [
                    "https://chaquo.com/pypi-13.1",
                    "https://pypi.org/simple",
                ]
            else:
                pip_extra_index_urls = []

        pip_timeout = platform_config.get("pip_timeout") or pyapp_config.get("pip_timeout", 120)
        pip_proxy = platform_config.get("pip_proxy") or pyapp_config.get("pip_proxy", "")

        return {
            "pip_index_url": pip_index_url,
            "pip_extra_index_urls": pip_extra_index_urls,
            "pip_timeout": pip_timeout,
            "pip_proxy": pip_proxy,
        }

    def _install_android_dependencies(self, dependencies: list, target: Path, config: Dict[str, Any], platform: str = "android") -> None:
        """安装 Android 平台依赖（考虑 Chaquopy 兼容性）"""
        # 从配置获取 pip 索引设置（支持公共 [tool.pyapp] 配置回退）
        pip_config = self._get_pip_config(config, platform)
        pip_index_url = pip_config["pip_index_url"]
        pip_extra_index_urls = pip_config["pip_extra_index_urls"]
        pip_timeout = pip_config["pip_timeout"]
        pip_proxy = pip_config["pip_proxy"]

        self.logger.info(f"Installing {len(dependencies)} dependencies for Android...")
        self.logger.info(f"Dependencies: {dependencies}")
        self.logger.info(f"Target directory: {target}")

        # 构建 pip 命令
        cmd = [sys.executable, "-m", "pip", "install"]

        # 添加索引配置
        if pip_index_url:
            cmd.extend(["--index-url", pip_index_url])
            self.logger.info(f"Index URL: {pip_index_url}")

        for extra_url in pip_extra_index_urls:
            cmd.extend(["--extra-index-url", extra_url])
            self.logger.info(f"Extra index URL: {extra_url}")

        if pip_timeout:
            cmd.extend(["--timeout", str(pip_timeout)])

        if pip_proxy:
            cmd.extend(["--proxy", pip_proxy])
            self.logger.info(f"Using proxy: {pip_proxy}")

        cmd.extend(dependencies)
        cmd.extend(["--target", str(target)])

        self.logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.stdout:
            self.logger.info(f"pip stdout:\n{result.stdout}")
        if result.stderr:
            self.logger.info(f"pip stderr:\n{result.stderr}")

        if result.returncode != 0:
            self.logger.warning(f"Batch installation failed (exit code: {result.returncode}), trying individually...")
            # 如果安装失败，尝试逐个安装
            failed = []
            for dep in dependencies:
                self.logger.info(f"Installing {dep}...")
                dep_cmd = [sys.executable, "-m", "pip", "install"]

                if pip_index_url:
                    dep_cmd.extend(["--index-url", pip_index_url])
                for extra_url in pip_extra_index_urls:
                    dep_cmd.extend(["--extra-index-url", extra_url])
                if pip_timeout:
                    dep_cmd.extend(["--timeout", str(pip_timeout)])
                if pip_proxy:
                    dep_cmd.extend(["--proxy", pip_proxy])

                dep_cmd.extend([dep, "--target", str(target)])

                self.logger.info(f"Running: {' '.join(dep_cmd)}")
                dep_result = subprocess.run(dep_cmd, capture_output=True, text=True)

                if dep_result.returncode != 0:
                    self.logger.error(f"Failed to install {dep}")
                    if dep_result.stderr:
                        self.logger.error(f"Error: {dep_result.stderr}")
                    failed.append(dep)
                else:
                    self.logger.info(f"Successfully installed {dep}")
                    if dep_result.stdout:
                        self.logger.info(f"Output: {dep_result.stdout}")

            if failed:
                raise BuildError(
                    f"Failed to install {len(failed)} dependencies: {', '.join(failed)}",
                    "Check the pip output for details. Some packages may not be available for Android platform."
                )
        else:
            self.logger.info(f"Successfully installed {len(dependencies)} dependencies")

    def _install_native_dependencies(self, dependencies: list, target: Path, platform: str, arch: str = None, config: Dict[str, Any] = None) -> None:
        """
        安装 Windows/Linux 平台依赖

        Args:
            dependencies: 依赖列表
            target: 目标目录
            platform: 目标平台 (windows, linux)
            arch: 目标架构 (x86_64, aarch64, armv7l)，用于跨架构编译
        """
        from ..core.cache import CacheManager

        # 平台标识配置：映射架构到可能的平台标识和对应的源
        # 格式: [(平台标识, 源URL), ...]
        # None 表示使用默认 PyPI 源
        PLATFORM_CONFIGS = {
            "x86_64": [("manylinux2014_x86_64", None)],
            "aarch64": [("manylinux2014_aarch64", None)],
            "armv7l": [
                ("manylinux2014_armv7l", None),  # PyPI
                ("linux_armv7l", "https://www.piwheels.org/simple"),  # piwheels
            ],
        }

        current_platform = sys.platform
        is_cross_compile = (
            (platform == "windows" and current_platform != "win32") or
            (platform == "linux" and current_platform != "linux")
        )

        # 检测跨架构编译
        is_cross_arch = False
        if platform == "linux" and arch:
            machine = pf.machine().lower()
            # 检测架构不匹配
            if arch == "x86_64" and machine not in ("x86_64", "amd64"):
                is_cross_arch = True
            elif arch == "aarch64" and machine not in ("aarch64", "arm64"):
                is_cross_arch = True
            elif arch == "armv7l" and machine not in ("armv7l", "armv7"):
                is_cross_arch = True

        # 检测跨版本编译：目标 Python 版本与系统 Python 版本不同
        python_version = self.get_python_version(config, platform)
        major_minor = ".".join(python_version.split(".")[:2])
        sys_major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
        is_cross_version = (major_minor != sys_major_minor)

        # 使用 pyapp 的 packages 目录作为 pip 缓存
        cache_manager = CacheManager()
        pip_cache_dir = cache_manager.packages_dir

        # 解析 pip 配置（支持公共 [tool.pyapp] 配置回退）
        pip_config = self._get_pip_config(config, platform)
        user_index_url = pip_config["pip_index_url"]
        user_extra_index_urls = pip_config["pip_extra_index_urls"]
        pip_timeout = pip_config["pip_timeout"]
        pip_proxy = pip_config["pip_proxy"]

        cmd = [
            sys.executable, "-m", "pip", "install"
        ] + dependencies + [
            "--target", str(target),
            "--cache-dir", str(pip_cache_dir),
        ]

        # 添加用户配置的索引源
        if user_index_url:
            cmd.extend(["--index-url", user_index_url])
            self.logger.info(f"Index URL: {user_index_url}")
        for extra_url in user_extra_index_urls:
            cmd.extend(["--extra-index-url", extra_url])
            self.logger.info(f"Extra index URL: {extra_url}")
        if pip_timeout:
            cmd.extend(["--timeout", str(pip_timeout)])
        if pip_proxy:
            cmd.extend(["--proxy", pip_proxy])
            self.logger.info(f"Using proxy: {pip_proxy}")

        if is_cross_compile or is_cross_arch:
            self.logger.warning(
                f"Cross-platform compilation detected (building {platform}/{arch or 'native'} on {current_platform})"
            )

            # 指定目标平台（使用第一个配置）
            if platform == "linux" and arch and arch in PLATFORM_CONFIGS:
                pip_platform, _ = PLATFORM_CONFIGS[arch][0]
                cmd.extend(["--platform", pip_platform])

            # 只使用预编译包
            cmd.extend([
                "--only-binary=:all:",
            ])

            self.logger.warning("Some packages with C extensions may not be available")

        # 跨版本编译或跨平台编译时，指定目标 Python 版本和 ABI
        if is_cross_version or is_cross_compile or is_cross_arch:
            self.logger.info(f"Target Python version: {major_minor} (system: {sys_major_minor})")
            cmd.extend([
                "--python-version", major_minor,
                "--implementation", "cp",
                "--abi", f"cp{major_minor.replace('.', '')}",
            ])

            # 跨版本本平台编译时，也需要指定 platform 和 --only-binary
            if not is_cross_compile and not is_cross_arch and is_cross_version:
                if platform == "windows":
                    cmd.extend(["--platform", "win_amd64"])
                elif platform == "linux":
                    machine = pf.machine().lower()
                    if machine in ("x86_64", "amd64"):
                        cmd.extend(["--platform", "manylinux2014_x86_64"])
                    elif machine in ("aarch64", "arm64"):
                        cmd.extend(["--platform", "manylinux2014_aarch64"])
                cmd.extend(["--only-binary=:all:"])

        self.logger.info(f"Installing {len(dependencies)} dependencies for {platform}{'/' + arch if arch else ''}...")
        self.logger.info(f"Using pip cache: {pip_cache_dir}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        # 显示 pip 安装详情
        if result.stdout:
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if (stripped.startswith("Successfully installed") or
                    stripped.startswith("Downloading ") or
                    stripped.startswith("Collecting ")):
                    self.logger.info(f"  {stripped}")

        if result.returncode != 0:
            self.logger.warning(f"Batch install failed, trying individually...")
            self.logger.debug(f"pip output: {result.stderr}")

            # 逐个安装
            failed = []
            for dep in dependencies:
                # 获取该架构的平台配置
                configs_to_try = []
                if platform == "linux" and arch and arch in PLATFORM_CONFIGS:
                    # armv7l 尝试所有配置（PyPI + piwheels），其他架构只有一个配置
                    configs_to_try = PLATFORM_CONFIGS[arch]

                installed = False
                for pip_platform, index_url in configs_to_try if configs_to_try else [(None, None)]:
                    dep_cmd = [
                        sys.executable, "-m", "pip", "install", dep,
                        "--target", str(target),
                        "--cache-dir", str(pip_cache_dir),
                    ]

                    # 索引源优先级：用户配置的 pip_index_url 作为主源，
                    # 架构特定源（如 piwheels）和用户额外源作为 extra-index-url；
                    # 若用户未配置，则保持原逻辑（架构特定源作为主源）
                    if user_index_url:
                        dep_cmd.extend(["--index-url", user_index_url])
                        seen = {user_index_url}
                        if index_url and index_url not in seen:
                            dep_cmd.extend(["--extra-index-url", index_url])
                            seen.add(index_url)
                        for extra_url in user_extra_index_urls:
                            if extra_url not in seen:
                                dep_cmd.extend(["--extra-index-url", extra_url])
                                seen.add(extra_url)
                    elif index_url:
                        dep_cmd.extend(["--index-url", index_url])
                        for extra_url in user_extra_index_urls:
                            if extra_url != index_url:
                                dep_cmd.extend(["--extra-index-url", extra_url])

                    if pip_timeout:
                        dep_cmd.extend(["--timeout", str(pip_timeout)])
                    if pip_proxy:
                        dep_cmd.extend(["--proxy", pip_proxy])

                    # 指定目标平台
                    if pip_platform:
                        dep_cmd.extend(["--platform", pip_platform])

                    if is_cross_compile or is_cross_arch:
                        dep_cmd.extend(["--only-binary=:all:"])

                    # 跨版本编译时，指定目标 Python 版本和 ABI
                    if is_cross_version or is_cross_compile or is_cross_arch:
                        dep_cmd.extend([
                            "--python-version", major_minor,
                            "--implementation", "cp",
                            "--abi", f"cp{major_minor.replace('.', '')}",
                        ])

                        # 跨版本本平台编译时，也需要指定 platform 和 --only-binary
                        if not is_cross_compile and not is_cross_arch and is_cross_version:
                            if platform == "windows":
                                dep_cmd.extend(["--platform", "win_amd64"])
                            elif platform == "linux":
                                machine = pf.machine().lower()
                                if machine in ("x86_64", "amd64"):
                                    dep_cmd.extend(["--platform", "manylinux2014_x86_64"])
                                elif machine in ("aarch64", "arm64"):
                                    dep_cmd.extend(["--platform", "manylinux2014_aarch64"])
                            dep_cmd.extend(["--only-binary=:all:"])

                    r = subprocess.run(dep_cmd, capture_output=True, text=True)

                    if r.returncode == 0:
                        installed = True
                        if r.stdout:
                            for line in r.stdout.splitlines():
                                stripped = line.strip()
                                if (stripped.startswith("Successfully installed") or
                                    stripped.startswith("Downloading ") or
                                    stripped.startswith("Collecting ")):
                                    self.logger.info(f"  {stripped}")
                        break  # 成功安装，跳出平台尝试循环

                if not installed:
                    failed.append(dep)
                    self.logger.warning(f"Failed to install {dep}")

            if failed:
                self.logger.error(f"Failed to install {len(failed)} packages: {', '.join(failed)}")
                raise BuildError(f"Failed to install dependencies: {failed}")

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

        # 获取版本号目录与主包名
        version = app_module = None
        if config:
            app_name = self.get_app_name(config)
            version = self.get_app_version(config)
            app_module = self.get_app_module(config)
            version_dir = f"{app_name}-{version}"
        else:
            version_dir = "app"

        target_dir = project_dir / "bundles" / platform / version_dir / "app"

        if target_dir.exists():
            shutil.rmtree(target_dir)

        shutil.copytree(src_dir, target_dir)
        self.logger.info(f"Synced source code → {target_dir}")

        # 将版本号注入到主包 __init__.py 的 __version__
        if version:
            self._inject_version(target_dir, version, app_module=app_module)

        return target_dir

    def _inject_version(self, target_dir: Path, version: str, app_module: str = None) -> None:
        """将版本号注入到 __init__.py 的 __version__ 变量，避免手动维护两处版本号

        Args:
            target_dir: 目标目录
            version: 版本号
            app_module: 主包名。提供时只注入 target_dir/app_module/__init__.py；
                        为 None 时只注入 target_dir/__init__.py（不递归，避免误改第三方包）
        """
        pattern = re.compile(r'__version__\s*=\s*["\'][^"\']*["\']')
        init_files = (
            [target_dir / app_module / "__init__.py"]
            if app_module
            else [target_dir / "__init__.py"]
        )
        for init_file in init_files:
            if not init_file.exists():
                continue
            try:
                content = init_file.read_text(encoding="utf-8")
                if pattern.search(content):
                    init_file.write_text(
                        pattern.sub(lambda m: f'__version__ = "{version}"', content),
                        encoding="utf-8",
                    )
                    self.logger.info(f"Injected version {version} → {init_file.relative_to(target_dir)}")
            except Exception as e:
                self.logger.warning(f"Inject version failed for {init_file.relative_to(target_dir)}: {e}")

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

    def get_python_version(self, config: Dict[str, Any], platform: str = None) -> str:
        """
        获取 Python 版本，支持平台级别覆盖

        Args:
            config: 配置字典
            platform: 平台名称 (windows, linux, android)，可选

        Returns:
            str: 平台特定的 Python 版本号
        """
        from ..core.runtime import RuntimeManager

        base_version = config.get("tool", {}).get("pyapp", {}).get("python_version", "3.10")

        if platform:
            version, _ = RuntimeManager.get_platform_version(base_version, platform)
            return version

        return base_version

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

    def get_icon(self, config: Dict[str, Any], platform: str = "windows") -> str:
        """获取应用图标路径（从平台配置中读取）"""
        return config.get("tool", {}).get("pyapp", {}).get(platform, {}).get("icon", "")

    def ensure_dist_dir(self, project_dir: Path) -> Path:
        """确保 dist 目录存在"""
        dist_dir = project_dir / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        return dist_dir
