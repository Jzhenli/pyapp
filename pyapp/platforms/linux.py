"""Linux 平台实现"""

import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import List, Dict, Any

from .base import BasePlatform, BuildResult
from ..core.logger import get_logger
from ..core.errors import BuildError, PyAppEnvironmentError


class LinuxPlatform(BasePlatform):
    """Linux 平台"""

    name = "linux"
    description = "Linux 平台 (PBS + systemd)"

    def check_environment(self) -> tuple:
        """检查 Linux 开发环境"""
        missing = []

        # Linux 通常已有 Python，检查其他工具
        for tool in ["tar"]:
            result = subprocess.run(
                ["which", tool] if os.name != "nt" else ["where", tool],
                capture_output=True
            )
            if result.returncode != 0:
                missing.append(f"{tool} not found")

        # 检查 systemctl（仅 Linux）
        if os.name != "nt":
            result = subprocess.run(["which", "systemctl"], capture_output=True)
            if result.returncode != 0:
                missing.append("systemctl not found (optional, for service installation)")

        return len(missing) == 0, missing

    def create(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """创建 Linux 项目结构（Shell 脚本和 systemd 服务）"""
        from jinja2 import Environment, FileSystemLoader

        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        version = self.get_app_version(config)
        port = self.get_port(config)

        service_name = config.get("tool", {}).get("pyapp", {}).get("linux", {}).get(
            "service_name", app_name.replace("_", "-")
        )

        template_dir = Path(__file__).parent.parent / "templates" / "shells" / "linux"
        bundle_dir = project_dir / "bundles" / "linux"

        if bundle_dir.exists():
            self.logger.info(f"Linux project already exists at {bundle_dir}, updating...")
        else:
            self.logger.info(f"Creating Linux project at {bundle_dir}...")

        # Jinja2 渲染
        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        # 获取 Python 版本（提取主版本号，如 3.10）
        python_version = self.get_python_version(config, "linux")
        python_major_minor = ".".join(python_version.split(".")[:2])

        template_vars = {
            "app_name": app_name,
            "app_module": app_module,
            "version": version,
            "port": port,
            "service_name": service_name,
            "install_dir": f"/opt/{service_name}",
            "python_version": python_major_minor,
        }

        # 渲染脚本
        self._render_template(jinja_env, "run.sh.j2", bundle_dir / "run.sh", template_vars)
        self._render_template(jinja_env, "install.sh.j2", bundle_dir / "install.sh", template_vars)
        self._render_template(jinja_env, "app.service.j2", bundle_dir / f"{service_name}.service", template_vars)

        # 设置脚本可执行权限
        for script in ["run.sh", "install.sh"]:
            script_path = bundle_dir / script
            if script_path.exists():
                try:
                    script_path.chmod(0o755)
                except OSError:
                    pass

        self.logger.success(f"Linux project created at {bundle_dir}")

    def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug", arch: str = None) -> BuildResult:
        """
        构建 Linux 安装包

        Args:
            project_dir: 项目目录
            config: 配置
            build_type: 构建类型
            arch: 目标架构 (x86_64, aarch64, armv7l)
        """
        try:
            # 默认架构
            if not arch:
                arch = "x86_64"

            # 1. 创建项目结构（如果不存在）
            bundle_dir = project_dir / "bundles" / "linux"
            if not bundle_dir.exists():
                self.create(project_dir, config)

            app_name = self.get_app_name(config)
            app_module = self.get_app_module(config)
            version = self.get_app_version(config)
            python_version = self.get_python_version(config, "linux")
            version_dir = f"{app_name}-{version}"

            # 清理旧版本目录
            old_version_dir = bundle_dir / "app"
            if old_version_dir.exists():
                self.logger.info(f"Removing old directory: {old_version_dir}")
                self._rmtree_safe(old_version_dir)

            # 清理当前版本目录（确保干净构建）
            current_version_path = bundle_dir / version_dir
            if current_version_path.exists():
                self.logger.info(f"Cleaning version directory: {current_version_path}")
                self._rmtree_safe(current_version_path)

            # 2. 下载 PBS (Python Build Standalone)
            self.logger.step(1, 6, f"Downloading Python runtime for {arch}")
            from ..core.runtime import RuntimeManager
            runtime_manager = RuntimeManager()
            runtime_dir = bundle_dir / "runtime"
            runtime_manager.get_runtime("linux", python_version, runtime_dir, arch=arch)

            # 3. 同步 Python 源码
            self.logger.step(2, 6, "Syncing Python source code")
            self.sync_source_code(project_dir, "linux", config)

            # 4. 同步前端资源
            self.logger.step(3, 6, "Syncing frontend resources")
            self.sync_frontend_dist(project_dir, "linux", config)

            # 5. 安装依赖
            self.logger.step(4, 6, "Installing dependencies")
            self.install_dependencies(project_dir, config, "linux", arch=arch)

            # 6. 生成启动脚本
            self.logger.step(5, 6, "Generating launch scripts")
            python_version = self.get_python_version(config, "linux")
            python_major_minor = ".".join(python_version.split(".")[:2])
            self._generate_run_script(bundle_dir, app_name, app_module, version, python_major_minor)

            # 6. 写入构建元数据
            self.logger.step(6, 6, "Writing build metadata")
            self._write_build_meta(bundle_dir, "linux", config, arch=arch, build_type=build_type)

            self.logger.success(f"Build prepared at {bundle_dir}")

            return BuildResult(success=True, output_path=bundle_dir)

        except Exception as e:
            self.logger.error(f"Build failed: {e}", exc_info=True)
            return BuildResult(success=False, error_message=str(e))

    def run(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """运行 Linux 应用"""
        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        version = self.get_app_version(config)
        version_dir = f"{app_name}-{version}"
        bundle_dir = project_dir / "bundles" / "linux"

        # 使用 PBS Python 运行
        python_version = self.get_python_version(config, "linux")
        python_major_minor = ".".join(python_version.split(".")[:2])
        runtime_python = bundle_dir / "runtime" / "bin" / f"python{python_major_minor}"
        if not runtime_python.exists():
            self.logger.error("Python runtime not found. Run 'pyapp build linux' first.")
            return

        env = self._get_run_env(bundle_dir, version_dir)
        app_dir = bundle_dir / version_dir / "app"

        process = subprocess.Popen(
            [str(runtime_python), "-m", app_module],
            cwd=str(app_dir),
            env=env,
        )
        self.logger.info(f"Started app (PID: {process.pid})")

    def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
        """打包 Linux 分发文件（不再调用 build）"""
        try:
            bundle_dir = project_dir / "bundles" / "linux"

            if not bundle_dir.exists():
                raise BuildError(
                    f"Bundle directory not found: {bundle_dir}",
                    "Run 'pyapp build linux' first"
                )

            # 从 build.meta.json 读取 arch 和元数据
            meta = self._read_build_meta(bundle_dir)
            app_name = meta["app_name"]
            version = meta["version"]
            arch = meta["arch"]

            # 打包 tar.gz
            dist_dir = self.ensure_dist_dir(project_dir)
            tar_path = dist_dir / f"{app_name}-{version}-linux-{arch}.tar.gz"
            self._create_tarball(bundle_dir, tar_path, f"{app_name}-{version}-linux-{arch}")

            self.logger.success(f"Package created: {tar_path}")

            return BuildResult(success=True, output_path=tar_path)

        except Exception as e:
            return BuildResult(success=False, error_message=str(e))

    def _generate_run_script(self, bundle_dir: Path, app_name: str, app_module: str, version: str, python_version: str = "3.10"):
        """生成运行脚本"""
        run_script = bundle_dir / "run.sh"
        if run_script.exists():
            return

        version_dir = f"{app_name}-{version}"
        script_content = f'''#!/bin/bash
cd "$(dirname "$0")"

# 设置环境变量
export PATH="runtime/bin:$PATH"
export PYTHONPATH="{version_dir}/app:{version_dir}/app_packages:$PYTHONPATH"

# 启动应用
exec runtime/bin/python{python_version} -m {app_module}
'''
        # 使用 Unix 行符（LF），确保 Linux 平台兼容
        run_script.write_text(script_content, encoding="utf-8", newline="\n")
        try:
            run_script.chmod(0o755)
        except OSError:
            pass

    def _rmtree_safe(self, path: Path) -> None:
        """安全删除目录，处理文件锁定问题"""
        import time
        import stat

        def on_rm_error(func, path_str, exc_info):
            """处理删除错误"""
            try:
                os.chmod(path_str, stat.S_IWRITE)
                func(path_str)
            except Exception:
                time.sleep(0.5)
                try:
                    func(path_str)
                except Exception as e:
                    self.logger.warning(f"Failed to delete {path_str}: {e}")

        for attempt in range(3):
            try:
                shutil.rmtree(path, onerror=on_rm_error)
                return
            except Exception as e:
                if attempt < 2:
                    self.logger.warning(f"Retry {attempt + 1} to remove {path}")
                    time.sleep(1)
                else:
                    raise

    def _create_tarball(self, source_dir: Path, tar_path: Path, top_dir: str = ""):
        """创建 tar.gz 包"""
        with tarfile.open(tar_path, "w:gz") as tf:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(source_dir)
                    if top_dir:
                        arcname = str(Path(top_dir) / arcname).replace("\\", "/")
                    tf.add(file_path, arcname)

    def _get_run_env(self, bundle_dir: Path, version_dir: str = "app") -> dict:
        """获取运行环境变量"""
        env = os.environ.copy()
        runtime_dir = bundle_dir / "runtime"
        app_packages_dir = bundle_dir / version_dir / "app_packages"
        app_dir = bundle_dir / version_dir / "app"

        path_sep = ":" if os.name != "nt" else ";"
        env["PATH"] = f"{runtime_dir / 'bin'}{path_sep}{env.get('PATH', '')}"
        env["PYTHONPATH"] = f"{app_dir}{path_sep}{app_packages_dir}{path_sep}{env.get('PYTHONPATH', '')}"

        return env

    def _restart_local_app(self, project_dir: Path, config: Dict[str, Any]):
        """重启本地应用"""
        import time

        app_module = self.get_app_module(config)
        bundle_dir = project_dir / "bundles" / "linux"
        port = self.get_port(config)

        # 查找并杀死旧进程
        try:
            subprocess.run(
                ["pkill", "-f", f"python3 -m {app_module}"],
                capture_output=True
            )
        except Exception:
            pass

        # 等待端口释放
        time.sleep(1)

        # 重新启动
        self.run(project_dir, config)

    def _render_template(self, jinja_env, template_name, output_path, variables):
        """渲染 Jinja2 模板"""
        template = jinja_env.get_template(template_name)
        content = template.render(**variables)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 使用 Unix 行符（LF），确保 Linux 平台兼容
        output_path.write_text(content, encoding="utf-8", newline="\n")
