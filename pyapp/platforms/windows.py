"""Windows 平台实现"""

import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import List, Dict, Any

from .base import BasePlatform, BuildResult
from ..core.logger import get_logger
from ..core.errors import BuildError, PyAppEnvironmentError


class WindowsPlatform(BasePlatform):
    """Windows 平台"""

    name = "windows"
    description = "Windows 平台 (Embeddable Python + Stub)"

    def check_environment(self) -> tuple:
        """检查 Windows 开发环境"""
        missing = []

        # 检查 gcc (MinGW-w64) - 仅编译 Stub 时需要
        try:
            result = subprocess.run(
                ["gcc", "--version"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                missing.append("MinGW-w64 not found. Run 'pyapp setup windows'")
        except FileNotFoundError:
            missing.append("MinGW-w64 not found. Run 'pyapp setup windows'")

        return len(missing) == 0, missing

    def create(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """创建 Windows 项目结构（Stub 源码）"""
        from jinja2 import Environment, FileSystemLoader

        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        version = self.get_app_version(config)
        port = self.get_port(config)

        template_dir = Path(__file__).parent.parent / "templates" / "shells" / "windows"
        bundle_dir = project_dir / "bundles" / "windows"

        if bundle_dir.exists():
            self.logger.info(f"Windows project already exists at {bundle_dir}, updating...")
        else:
            self.logger.info(f"Creating Windows project at {bundle_dir}...")

        # Jinja2 渲染
        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        template_vars = {
            "app_name": app_name,
            "app_module": app_module,
            "version": version,
            "port": port,
        }

        # 渲染 Stub 源码
        self._render_template(jinja_env, "app_stub.c.j2", bundle_dir / "app_stub.c", template_vars)
        self._render_template(jinja_env, "app_stub.rc.j2", bundle_dir / "app_stub.rc", template_vars)
        self._render_template(jinja_env, "build.bat.j2", bundle_dir / "build.bat", template_vars)

        self.logger.success(f"Windows project created at {bundle_dir}")

    def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug") -> BuildResult:
        """构建 Windows 安装包"""
        try:
            # 1. 检查环境
            ok, missing = self.check_environment()
            if not ok:
                # Stub 编译可选，给出警告
                self.logger.warning(f"Missing: {', '.join(missing)}")
                self.logger.warning("Stub compilation will be skipped")

            # 2. 创建项目结构（如果不存在）
            bundle_dir = project_dir / "bundles" / "windows"

            # 总是重新渲染 Stub 源码（确保版本号正确）
            self._update_stub_sources(project_dir, config)

            app_name = self.get_app_name(config)
            app_module = self.get_app_module(config)
            version = self.get_app_version(config)
            python_version = self.get_python_version(config, "windows")
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

            # 3. 下载 Embeddable Python
            self.logger.step(1, 6, "Downloading Python runtime")
            from ..core.runtime import RuntimeManager
            runtime_manager = RuntimeManager()
            runtime_dir = bundle_dir / "runtime"
            runtime_manager.get_runtime("windows", python_version, runtime_dir)

            # 修改 _pth 文件以支持自定义导入路径
            self._fix_pth_file(runtime_dir, version_dir, python_version)

            # 4. 同步 Python 源码
            self.logger.step(2, 6, "Syncing Python source code")
            self.sync_source_code(project_dir, "windows", config)

            # 5. 同步前端资源
            self.logger.step(3, 6, "Syncing frontend resources")
            self.sync_frontend_dist(project_dir, "windows", config)

            # 6. 安装依赖
            self.logger.step(4, 6, "Installing dependencies")
            self.install_dependencies(project_dir, config, "windows")

            # 7. 编译 Stub（可选）
            self.logger.step(5, 6, "Compiling Stub")
            exe_path = self._compile_stub(bundle_dir, app_name)
            if not exe_path:
                # 创建启动脚本替代
                exe_path = self._create_launch_script(bundle_dir, app_name, app_module, version_dir)

            # 8. 打包 ZIP
            self.logger.step(6, 6, "Packaging ZIP")
            dist_dir = self.ensure_dist_dir(project_dir)
            zip_filename = f"{app_name}-{version}-windows-x86_64.zip"
            zip_path = dist_dir / zip_filename

            self._create_zip(bundle_dir, zip_path)

            self.logger.success(f"Package: {zip_path}")

            return BuildResult(success=True, output_path=zip_path)

        except Exception as e:
            self.logger.error(f"Build failed: {e}", exc_info=True)
            return BuildResult(success=False, error_message=str(e))

    def run(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """运行 Windows 应用"""
        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        version = self.get_app_version(config)
        version_dir = f"{app_name}-{version}"
        bundle_dir = project_dir / "bundles" / "windows"

        # 查找 exe 或启动脚本
        exe_path = bundle_dir / f"{app_name}.exe"
        bat_path = bundle_dir / f"{app_name}.bat"

        if exe_path.exists():
            subprocess.Popen([str(exe_path)], cwd=str(bundle_dir))
            self.logger.info(f"Started {exe_path}")
            return

        if bat_path.exists():
            subprocess.Popen(["cmd", "/c", str(bat_path)], cwd=str(bundle_dir))
            self.logger.info(f"Started {bat_path}")
            return

        # 使用 Python 直接运行
        runtime_python = bundle_dir / "runtime" / "python.exe"
        if runtime_python.exists():
            app_dir = bundle_dir / version_dir / "app"
            subprocess.Popen(
                [str(runtime_python), "-m", app_module],
                cwd=str(app_dir),
                env=self._get_run_env(bundle_dir, version_dir),
            )
            self.logger.info(f"Started app with {runtime_python}")
            return

        self.logger.error("No executable found. Run 'pyapp build windows' first.")

    def dev(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """开发模式（文件监听 + 热重载）"""
        from ..core.watcher import FileWatcher
        from ..core.device import DeviceManager

        device_manager = DeviceManager()
        app_name = self.get_app_name(config)
        version = self.get_app_version(config)
        version_dir = f"{app_name}-{version}"

        # 先构建
        self.logger.info("Building app for development...")
        result = self.build(project_dir, config)
        if not result.success:
            return

        # 启动应用
        self.run(project_dir, config)

        # 启动文件监听
        src_dir = project_dir / "src"
        bundle_app_dir = project_dir / "bundles" / "windows" / version_dir / "app"

        def on_file_change(file_path: str):
            self.logger.info(f"Change detected: {file_path}")
            local_path = Path(file_path)
            try:
                rel_path = local_path.relative_to(src_dir)
            except ValueError:
                return

            # 复制文件到 bundle 目录
            target_path = bundle_app_dir / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, target_path)

            # 发送重启信号
            port = self.get_port(config)
            if device_manager.restart_windows_app("127.0.0.1", port):
                self.logger.success("App restarted")
            else:
                self.logger.warning("Failed to restart app via API, manual restart may be needed")

        watcher = FileWatcher(src_dir, on_file_change)
        watcher.start()

        self.logger.info("Development mode active. Press Ctrl+C to stop.")
        try:
            watcher.wait()
        except KeyboardInterrupt:
            watcher.stop()

    def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
        """打包发布版 Windows 安装包"""
        # 构建发布版
        result = self.build(project_dir, config, build_type="release")
        if not result.success:
            return result

        # Windows 签名（可选）
        # signtool sign /f cert.pfx /p password app.exe
        self.logger.info("Release package created (unsigned)")
        return result

    def _compile_stub(self, bundle_dir: Path, app_name: str) -> Path:
        """编译 Windows Stub"""
        stub_c = bundle_dir / "app_stub.c"
        stub_rc = bundle_dir / "app_stub.rc"

        if not stub_c.exists():
            return None

        try:
            # 编译资源文件
            stub_res = bundle_dir / "app_stub.res"
            if stub_rc.exists():
                subprocess.run(
                    ["windres", str(stub_rc), "-O", "coff", "-o", str(stub_res)],
                    capture_output=True, check=True,
                )

            # 编译 Stub
            exe_path = bundle_dir / f"{app_name}.exe"
            cmd = [
                "gcc", "-o", str(exe_path),
                str(stub_c),
                "-mwindows", "-O2",
            ]
            if stub_res.exists():
                cmd.append(str(stub_res))

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.logger.success(f"Stub compiled: {exe_path}")
                return exe_path
            else:
                self.logger.warning(f"Stub compilation failed: {result.stderr}")
                return None

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.logger.warning(f"Stub compilation skipped: {e}")
            return None

    def _create_launch_script(self, bundle_dir: Path, app_name: str, app_module: str, version_dir: str) -> Path:
        """创建启动脚本（替代 Stub）"""
        script_path = bundle_dir / f"{app_name}.bat"
        script_content = f'''@echo off
cd /d "%~dp0"
set PATH=runtime;runtime\\Scripts;%PATH%
set PYTHONPATH={version_dir}\\app;{version_dir}\\app_packages;%PYTHONPATH%
python -m {app_module}
pause
'''
        script_path.write_text(script_content, encoding="utf-8")
        self.logger.info(f"Launch script created: {script_path}")
        return script_path

    def _rmtree_safe(self, path: Path) -> None:
        """安全删除目录，处理 Windows 文件锁定问题"""
        import time
        import stat

        def on_rm_error(func, path_str, exc_info):
            """处理删除错误"""
            path_obj = Path(path_str)
            # 尝试移除只读属性
            try:
                os.chmod(path_str, stat.S_IWRITE)
                func(path_str)
            except Exception:
                # 如果还是失败，等待后重试
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

    def _fix_pth_file(self, runtime_dir: Path, version_dir: str, python_version: str = "3.10") -> None:
        """修改 Embeddable Python 的 _pth 文件以支持自定义导入路径"""
        # 查找 _pth 文件
        pth_files = list(runtime_dir.glob("python*._pth"))
        if not pth_files:
            self.logger.warning("No _pth file found in runtime")
            return

        pth_file = pth_files[0]
        self.logger.info(f"Fixing _pth file: {pth_file}")

        # 根据实际 Python 版本生成 zip 文件名
        ver_tag = python_version.replace(".", "")[:3]  # "3.10" -> "310", "3.11" -> "311"
        zip_name = f"python{ver_tag}.zip"

        # 写入新的内容
        content = f"""{zip_name}
.

# Custom paths for PyApp
../{version_dir}/app
../{version_dir}/app_packages

# Uncomment to run site.main() automatically
import site
"""
        pth_file.write_text(content, encoding="utf-8")
        self.logger.success(f"Updated {pth_file.name} with custom import paths")

    def _create_zip(self, source_dir: Path, zip_path: Path):
        """创建 ZIP 包，排除编译源文件"""
        # 排除的文件列表（编译相关的源文件）
        exclude_files = {
            "app_stub.c",
            "app_stub.rc", 
            "app_stub.res",
            "build.bat",
        }
        
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    # 排除编译源文件
                    if file_path.name in exclude_files:
                        continue
                    arcname = file_path.relative_to(source_dir)
                    zf.write(file_path, arcname)

    def _update_stub_sources(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """更新 Stub 源码（确保版本号正确）"""
        from jinja2 import Environment, FileSystemLoader

        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        version = self.get_app_version(config)
        port = self.get_port(config)

        template_dir = Path(__file__).parent.parent / "templates" / "shells" / "windows"
        bundle_dir = project_dir / "bundles" / "windows"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # Jinja2 渲染
        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        template_vars = {
            "app_name": app_name,
            "app_module": app_module,
            "version": version,
            "port": port,
        }

        # 渲染 Stub 源码
        self._render_template(jinja_env, "app_stub.c.j2", bundle_dir / "app_stub.c", template_vars)
        self._render_template(jinja_env, "app_stub.rc.j2", bundle_dir / "app_stub.rc", template_vars)
        self._render_template(jinja_env, "build.bat.j2", bundle_dir / "build.bat", template_vars)

    def _get_run_env(self, bundle_dir: Path, version_dir: str = "app") -> dict:
        """获取运行环境变量"""
        env = os.environ.copy()
        runtime_dir = bundle_dir / "runtime"
        app_packages_dir = bundle_dir / version_dir / "app_packages"
        app_dir = bundle_dir / version_dir / "app"

        # 添加到 PATH
        path_sep = ";" if os.name == "nt" else ":"
        env["PATH"] = f"{runtime_dir}{path_sep}{runtime_dir / 'Scripts'}{path_sep}{env.get('PATH', '')}"
        env["PYTHONPATH"] = f"{app_dir}{path_sep}{app_packages_dir}{path_sep}{env.get('PYTHONPATH', '')}"

        return env

    def _render_template(self, jinja_env, template_name, output_path, variables):
        """渲染 Jinja2 模板"""
        template = jinja_env.get_template(template_name)
        content = template.render(**variables)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
