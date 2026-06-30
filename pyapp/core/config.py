"""配置解析模块 - 从 pyproject.toml 加载项目配置"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

# Python < 3.11 兼容
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        raise ImportError(
            "Python < 3.11 requires the 'tomli' package. "
            "Install it with: pip install tomli"
        )


@dataclass
class ProjectConfig:
    """项目配置"""
    name: str
    version: str
    description: str = ""
    authors: List[Dict[str, str]] = field(default_factory=list)
    requires_python: str = ">=3.10"
    dependencies: List[str] = field(default_factory=list)
    optional_dependencies: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class PyAppConfig:
    """PyApp 工具配置"""
    python_version: str = "3.10"
    app_module: str = ""
    port: int = 18080

    # 公共 pip 配置（三个平台共用，可被平台特定配置覆盖）
    pip_index_url: str = ""
    pip_extra_index_urls: List[str] = field(default_factory=list)
    pip_timeout: int = 120
    pip_proxy: str = ""

    # 平台配置
    android: Dict[str, Any] = field(default_factory=dict)
    windows: Dict[str, Any] = field(default_factory=dict)
    linux: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    """完整应用配置"""
    project: ProjectConfig
    pyapp: PyAppConfig

    @classmethod
    def from_file(cls, path: Path) -> "AppConfig":
        """从 pyproject.toml 加载配置"""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        # 解析 project 段
        project_data = data.get("project", {})
        project = ProjectConfig(
            name=project_data.get("name", ""),
            version=project_data.get("version", "0.1.0"),
            description=project_data.get("description", ""),
            authors=project_data.get("authors", []),
            requires_python=project_data.get("requires-python", ">=3.10"),
            dependencies=project_data.get("dependencies", []),
            optional_dependencies=project_data.get("optional-dependencies", {}),
        )

        # 解析 tool.pyapp 段
        pyapp_data = data.get("tool", {}).get("pyapp", {})

        # 自动检测 app_module（如果未配置）
        app_module = pyapp_data.get("app_module", "")
        if not app_module:
            app_module = cls._detect_app_module(path.parent, project.name)

        pyapp = PyAppConfig(
            python_version=pyapp_data.get("python_version", "3.10"),
            app_module=app_module,
            port=pyapp_data.get("port", 18080),
            pip_index_url=pyapp_data.get("pip_index_url", ""),
            pip_extra_index_urls=pyapp_data.get("pip_extra_index_urls", []),
            pip_timeout=pyapp_data.get("pip_timeout", 120),
            pip_proxy=pyapp_data.get("pip_proxy", ""),
            android=pyapp_data.get("android", {}),
            windows=pyapp_data.get("windows", {}),
            linux=pyapp_data.get("linux", {}),
        )

        config = cls(project=project, pyapp=pyapp)
        config._validate(path.parent)
        return config

    @staticmethod
    def _detect_app_module(project_dir: Path, project_name: str) -> str:
        """自动检测 Python 模块名"""
        src_dir = project_dir / "src"
        if src_dir.exists():
            packages = [d for d in src_dir.iterdir()
                       if d.is_dir() and (d / "__init__.py").exists()]
            if len(packages) == 1:
                return packages[0].name
        return project_name.replace("-", "_")

    def _validate(self, project_dir: Path):
        """验证配置有效性"""
        # 1. 验证模块路径存在（支持 src/ 和根目录布局）
        module_path = project_dir / "src" / self.pyapp.app_module
        if not module_path.exists():
            module_path = project_dir / self.pyapp.app_module
        if not module_path.exists():
            raise ValueError(f"Module '{self.pyapp.app_module}' not found at {project_dir / 'src' / self.pyapp.app_module}")
        if not (module_path / "__main__.py").exists():
            raise ValueError(f"__main__.py not found in {self.pyapp.app_module}")

        # 2. 验证 Python 版本有效性
        self._validate_python_version()

        # 3. 验证平台特定配置
        self._validate_platform_configs()

    def _validate_python_version(self):
        """验证 Python 版本有效性"""
        import re

        python_version = self.pyapp.python_version

        # 验证版本格式（支持 X.Y 或 X.Y.Z）
        pattern = r"^\d+\.\d+(\.\d+)?$"
        if not re.match(pattern, python_version):
            raise ValueError(
                f"Invalid Python version format: {python_version}. "
                "Expected format: X.Y (e.g., 3.10) or X.Y.Z (e.g., 3.10.11)"
            )

        # 验证版本范围
        try:
            from packaging.version import parse as parse_version
            min_version = parse_version("3.8.0")
            max_version = parse_version("3.13.0")

            # 提取主版本号用于验证
            major_minor = ".".join(python_version.split(".")[:2])
            current_version = parse_version(major_minor + ".0")

            if current_version < min_version:
                raise ValueError(
                    f"Python version {python_version} is too old. "
                    f"Minimum supported version is 3.8"
                )

            if current_version >= max_version:
                print(f"Warning: Python version {python_version} may not be fully tested")

            # 验证 Chaquopy 支持的版本（Android 平台）
            if self.pyapp.android:
                chaquopy_versions = ["3.8", "3.9", "3.10", "3.11", "3.12"]
                if major_minor not in chaquopy_versions:
                    raise ValueError(
                        f"Python {major_minor} is not supported by Chaquopy for Android. "
                        f"Supported versions: {', '.join(chaquopy_versions)}"
                    )
        except ImportError:
            # packaging 未安装时跳过版本比较
            pass

    def _validate_platform_configs(self):
        """验证平台特定配置"""
        import re

        # Android 平台配置验证
        if self.pyapp.android:
            package_name = self.pyapp.android.get("package_name", "")
            if not package_name:
                raise ValueError(
                    "Android package_name is required. "
                    "Add 'package_name' to [tool.pyapp.android] in pyproject.toml"
                )

            # 验证包名格式
            if not re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", package_name):
                raise ValueError(
                    f"Invalid Android package name: {package_name}. "
                    "Expected format: com.example.myapp"
                )

            # 验证 SDK 版本
            min_sdk = self.pyapp.android.get("min_sdk", 24)
            target_sdk = self.pyapp.android.get("target_sdk", 34)
            if min_sdk > target_sdk:
                raise ValueError(
                    f"min_sdk ({min_sdk}) cannot be greater than target_sdk ({target_sdk})"
                )

        # Windows 平台配置验证
        if self.pyapp.windows:
            deployment = self.pyapp.windows.get("deployment", "standalone")
            if deployment not in ["standalone", "shared"]:
                raise ValueError(
                    f"Invalid Windows deployment mode: {deployment}. "
                    "Expected: 'standalone' or 'shared'"
                )

        # Linux 平台配置验证
        if self.pyapp.linux:
            deployment = self.pyapp.linux.get("deployment", "shared")
            if deployment not in ["standalone", "shared"]:
                raise ValueError(
                    f"Invalid Linux deployment mode: {deployment}. "
                    "Expected: 'standalone' or 'shared'"
                )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（供模板渲染使用）"""
        return {
            "project": {
                "name": self.project.name,
                "version": self.project.version,
                "description": self.project.description,
                "dependencies": self.project.dependencies,
            },
            "tool": {
                "pyapp": {
                    "python_version": self.pyapp.python_version,
                    "app_module": self.pyapp.app_module,
                    "port": self.pyapp.port,
                    "pip_index_url": self.pyapp.pip_index_url,
                    "pip_extra_index_urls": self.pyapp.pip_extra_index_urls,
                    "pip_timeout": self.pyapp.pip_timeout,
                    "pip_proxy": self.pyapp.pip_proxy,
                    "android": self.pyapp.android,
                    "windows": self.pyapp.windows,
                    "linux": self.pyapp.linux,
                }
            }
        }

    def get_merged_dependencies(self, platform: str) -> List[str]:
        """获取合并后的依赖列表（全局 + 平台特定）"""
        import re

        platform_config = getattr(self.pyapp, platform, {})
        platform_deps = platform_config.get("dependencies", [])

        def _extract_dep_name(dep: str) -> str:
            """从 PEP 508 依赖字符串中提取包名"""
            match = re.match(r'^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)', dep)
            return match.group(1).lower() if match else dep.split("[")[0].split(">=")[0].split("==")[0].split("<")[0].strip().lower()

        merged = {}
        for dep in self.project.dependencies:
            name = _extract_dep_name(dep)
            merged[name] = dep

        for dep in platform_deps:
            name = _extract_dep_name(dep)
            merged[name] = dep  # 覆盖或追加

        return list(merged.values())


def load_config(project_dir: Path) -> AppConfig:
    """加载项目配置"""
    config_file = project_dir / "pyproject.toml"
    if not config_file.exists():
        raise FileNotFoundError(f"pyproject.toml not found in {project_dir}")
    return AppConfig.from_file(config_file)
