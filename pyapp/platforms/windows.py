"""Windows 平台实现 (Parent-Child Process + WebView2)"""

import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from .base import BasePlatform, BuildResult
from ..core.logger import get_logger
from ..core.errors import BuildError, PyAppEnvironmentError


class WindowsPlatform(BasePlatform):
    """Windows 平台 (Embeddable Python + Stub + WebView2)"""

    name = "windows"
    description = "Windows 平台 (Embeddable Python + Stub + WebView2)"

    # WebView2 SDK 版本（用于下载 WebView2Loader.dll）
    # 更新此版本时需验证 NuGet 包内 x64 DLL 路径未变
    WEBVIEW2_SDK_VERSION = "1.0.2792.45"

    # rcedit 版本（用于修改 python.exe 的 VERSIONINFO）
    RCEDIT_VERSION = "2.0.0"
    RCEDIT_URL = "https://github.com/electron/rcedit/releases/download/v{version}/rcedit-x64.exe"

    def check_environment(self) -> tuple:
        """检查 Windows 开发环境（MinGW）"""
        if self._check_mingw():
            self.logger.info("Available compiler: MinGW-w64 (g++)")
            return True, []
        else:
            return False, ["MinGW-w64 (g++) not found. Run 'pyapp setup windows'"]

    def _check_mingw(self) -> bool:
        """检查 MinGW 是否可用"""
        try:
            result = subprocess.run(
                ["g++", "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def create(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """创建 Windows 项目结构（Stub 源码 + 配置文件）"""
        bundle_dir = project_dir / "bundles" / "windows"

        if bundle_dir.exists():
            self.logger.info(f"Windows project already exists at {bundle_dir}, updating...")
        else:
            self.logger.info(f"Creating Windows project at {bundle_dir}...")

        self._render_all_templates(project_dir, config)

        self.logger.success(f"Windows project created at {bundle_dir}")

    def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug") -> BuildResult:
        """构建 Windows 安装包"""
        try:
            # 1. 检查环境
            ok, missing = self.check_environment()
            if not ok:
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
            self.logger.step(1, 8, "Downloading Python runtime")
            from ..core.runtime import RuntimeManager
            runtime_manager = RuntimeManager()
            runtime_dir = bundle_dir / "runtime"
            runtime_manager.get_runtime("windows", python_version, runtime_dir)

            # 修改 _pth 文件以支持自定义导入路径
            self._fix_pth_file(runtime_dir, version_dir, python_version)

            # 3.5 复制 python.exe 为 {{app_name}}-runtime.exe 并修改 VERSIONINFO
            self.logger.step(2, 8, "Creating runtime executable")
            icon_str = self.get_icon(config, "windows")
            icon_path = None
            if icon_str:
                icon_candidate = project_dir / icon_str
                # 如果路径没有 .ico 后缀，自动尝试添加
                if not icon_candidate.exists() and not icon_str.lower().endswith('.ico'):
                    icon_candidate = project_dir / f"{icon_str}.ico"
                if icon_candidate.exists():
                    icon_path = icon_candidate
                else:
                    self.logger.warning(f"Icon file not found: {icon_candidate}")
            self._create_runtime_exe(runtime_dir, app_name, version, icon_path)

            # 4. 同步 Python 源码
            self.logger.step(3, 8, "Syncing Python source code")
            self.sync_source_code(project_dir, "windows", config)

            # 5. 同步前端资源
            self.logger.step(4, 8, "Syncing frontend resources")
            self.sync_frontend_dist(project_dir, "windows", config)

            # 6. 安装依赖
            self.logger.step(5, 8, "Installing dependencies")
            self.install_dependencies(project_dir, config, "windows")

            # 7. 编译 Stub（可选）
            self.logger.step(6, 8, "Compiling Stub")
            exe_path = self._compile_stub(bundle_dir, app_name)
            if not exe_path:
                # 创建启动脚本替代
                exe_path = self._create_launch_script(bundle_dir, app_name, app_module, version_dir, config)

            # 7.5 下载 WebView2Loader.dll（UI 模式需要）
            self.logger.step(7, 8, "Downloading WebView2Loader.dll")
            self._download_webview2_loader(bundle_dir)

            # 8. 打包 ZIP
            self.logger.step(8, 8, "Packaging ZIP")
            dist_dir = self.ensure_dist_dir(project_dir)
            zip_filename = f"{app_name}-{version}-windows-x86_64.zip"
            zip_path = dist_dir / zip_filename

            self._create_zip(bundle_dir, zip_path, zip_filename.replace(".zip", ""))

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
        runtime_python = bundle_dir / "runtime" / f"{app_name}-runtime.exe"
        if not runtime_python.exists():
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

        # 启动应用（使用 --console 模式方便开发调试）
        exe_path = project_dir / "bundles" / "windows" / f"{app_name}.exe"
        if exe_path.exists():
            subprocess.Popen([str(exe_path), "--console"], cwd=str(exe_path.parent))
            self.logger.info(f"Started {exe_path} --console")
        else:
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

    def _compile_stub(self, bundle_dir: Path, app_name: str) -> Optional[Path]:
        """编译 Windows Stub（使用 MinGW）"""
        stub_cpp = bundle_dir / "app_stub.cpp"
        stub_rc = bundle_dir / "app_stub.rc"

        if not stub_cpp.exists():
            return None

        exe_path = bundle_dir / f"{app_name}.exe"

        # 检查 MinGW 是否可用
        if not self._check_mingw():
            self.logger.warning("MinGW-w64 (g++) not found")
            return None

        self.logger.info("Using MinGW compiler")
        return self._compile_stub_mingw(bundle_dir, exe_path, stub_cpp, stub_rc)

    def _compile_stub_mingw(self, bundle_dir: Path, exe_path: Path,
                            stub_cpp: Path, stub_rc: Path) -> Optional[Path]:
        """使用 MinGW 编译 Stub"""
        try:
            # 编译资源文件
            stub_res = bundle_dir / "app_stub.res"
            if stub_rc.exists():
                result = subprocess.run(
                    ["windres", str(stub_rc), "-O", "coff", "-o", str(stub_res)],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    self.logger.warning(f"Resource compilation failed: {result.stderr}")
                    stub_res = None
                else:
                    # 确保文件确实存在（编译成功但文件可能被意外删除）
                    if stub_res.exists():
                        self.logger.info("Resource file compiled")
                    else:
                        self.logger.warning(f"Resource file not found after compilation: {stub_res}")
                        stub_res = None

            # 编译 Stub (C++)
            cmd = [
                "g++", "-o", str(exe_path),
                str(stub_cpp),
                "-mwindows", "-O2", "-s",
                "-static-libgcc", "-static-libstdc++",  # 静态链接 GCC 运行时（避免依赖 DLL）
                "-lwinhttp", "-lole32", "-loleaut32", "-lshell32", "-lgdi32", "-lws2_32",
            ]
            if stub_res and stub_res.exists():
                cmd.append(str(stub_res))

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # 清理中间文件
                if stub_res and stub_res.exists():
                    stub_res.unlink(missing_ok=True)
                self.logger.success(f"Stub compiled with MinGW: {exe_path}")
                return exe_path
            else:
                self.logger.warning(f"MinGW compilation failed: {result.stderr}")
                return None

        except Exception as e:
            self.logger.warning(f"MinGW compilation failed: {e}")
            return None

    def _create_launch_script(self, bundle_dir: Path, app_name: str, app_module: str, version_dir: str, config: Dict[str, Any]) -> Path:
        """创建启动脚本（替代 Stub，当编译失败时使用）"""
        port = self.get_port(config)
        script_path = bundle_dir / f"{app_name}.bat"
        runtime_exe = f"{app_name}-runtime.exe"
        script_content = f'''@echo off
cd /d "%~dp0"
set PATH=runtime;runtime\\Scripts;%PATH%
set PYTHONPATH={version_dir}\\app;{version_dir}\\app_packages;%PYTHONPATH%
set APP_MODE=production
set APP_PORT={port}
runtime\\{runtime_exe} -m {app_module}
pause
'''
        script_path.write_text(script_content, encoding="utf-8")
        self.logger.info(f"Launch script created: {script_path}")
        return script_path

    def _download_webview2_loader(self, bundle_dir: Path) -> None:
        """下载 WebView2Loader.dll（UI 模式运行时依赖）

        WebView2Loader.dll 是 Microsoft WebView2 SDK 的一部分，
        用于在运行时加载系统已安装的 WebView2 Runtime。
        它很小（约 150KB），需要放在 exe 同目录。
        """
        import urllib.request
        import tempfile
        from ..core.cache import CacheManager

        target_path = bundle_dir / "WebView2Loader.dll"

        # 已存在则跳过
        if target_path.exists() and target_path.stat().st_size > 0:
            self.logger.info(f"WebView2Loader.dll already exists at {target_path}")
            return

        # 从缓存查找
        cache_manager = CacheManager()
        cached = cache_manager.get("webview2-loader-x64")
        if cached and cached.exists():
            shutil.copy2(cached, target_path)
            self.logger.success(f"WebView2Loader.dll restored from cache")
            return

        # 下载 WebView2Loader.dll
        # 来源: Microsoft WebView2 SDK NuGet 包 (x64)
        # 该 DLL 是 BSD-3-Clause 许可的自由分发文件
        loader_url = f"https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/{self.WEBVIEW2_SDK_VERSION}"

        self.logger.info(f"Downloading WebView2Loader.dll...")

        try:
            # 下载 NuGet 包（本质是 zip 文件）
            tmp_zip_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                    urllib.request.urlretrieve(loader_url, tmp_zip.name)
                    tmp_zip_path = tmp_zip.name

                # 从 NuGet 包中提取 WebView2Loader.dll
                with zipfile.ZipFile(tmp_zip_path, "r") as zf:
                    # 收集所有 WebView2Loader.dll 条目，优先选择 x64 版本
                    dll_entries = [
                        n for n in zf.namelist()
                        if n.endswith("WebView2Loader.dll")
                    ]

                    # 优先选择 x64 版本
                    best = None
                    for entry in dll_entries:
                        if "x64" in entry:
                            best = entry
                            break
                    if not best and dll_entries:
                        best = dll_entries[0]

                    if best:
                        with zf.open(best) as src, open(target_path, "wb") as dst:
                            dst.write(src.read())

                        self.logger.success(f"WebView2Loader.dll extracted ({target_path.stat().st_size} bytes)")

                        # 缓存（复制到缓存目录，不移动原文件）
                        cache_dir = cache_manager.packages_dir
                        cache_path = cache_dir / "WebView2Loader.dll"
                        shutil.copy2(target_path, cache_path)
                        cache_manager.register("webview2-loader-x64", cache_path)
                    else:
                        self.logger.warning("WebView2Loader.dll not found in NuGet package")
            finally:
                # 清理临时文件（无论成功或异常）
                if tmp_zip_path:
                    Path(tmp_zip_path).unlink(missing_ok=True)

        except Exception as e:
            self.logger.warning(f"Failed to download WebView2Loader.dll: {e}")
            self.logger.warning("UI mode will not work. Install WebView2 SDK manually or use --console mode.")

    def _rmtree_safe(self, path: Path) -> None:
        """安全删除目录，处理 Windows 文件锁定问题"""
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

    def _create_runtime_exe(self, runtime_dir: Path, app_name: str, version: str, icon_path: Optional[Path] = None) -> None:
        """复制 python.exe 为 {app_name}-runtime.exe 并用 rcedit 修改 VERSIONINFO 和图标

        使任务管理器显示应用名而非 "Python"。
        保留原始 python.exe 以便调试和兼容。
        """
        src_python = runtime_dir / "python.exe"
        dst_runtime = runtime_dir / f"{app_name}-runtime.exe"

        if not src_python.exists():
            self.logger.warning("python.exe not found in runtime, skipping runtime exe creation")
            return

        # 清理旧的 runtime exe（app_name 变更时残留）
        for old_runtime in runtime_dir.glob("*-runtime.exe"):
            if old_runtime.name != f"{app_name}-runtime.exe":
                old_runtime.unlink(missing_ok=True)

        # 复制 python.exe 为应用专属的运行时可执行文件
        shutil.copy2(src_python, dst_runtime)
        self.logger.info(f"Copied {src_python.name} -> {dst_runtime.name}")

        # 用 rcedit 修改 VERSIONINFO
        rcedit_path = self._get_rcedit()
        if rcedit_path:
            try:
                cmd = [
                    str(rcedit_path),
                    str(dst_runtime),
                    "--set-version-string", "FileDescription", app_name,
                    "--set-version-string", "ProductName", app_name,
                    "--set-version-string", "OriginalFilename", f"{app_name}-runtime.exe",
                    "--set-version-string", "InternalName", f"{app_name}-runtime",
                    "--set-file-version", version,
                    "--set-product-version", version,
                ]
                if icon_path and icon_path.exists():
                    cmd.extend(["--set-icon", str(icon_path)])
                subprocess.run(cmd, capture_output=True, text=True, check=True)
                self.logger.success(f"VERSIONINFO updated for {dst_runtime.name}")
            except (subprocess.CalledProcessError, OSError) as e:
                self.logger.warning(f"rcedit failed: {e}")
                self.logger.warning(f"Task Manager may show 'Python' instead of '{app_name}'")
        else:
            self.logger.warning("rcedit not available, VERSIONINFO not modified")
            self.logger.warning(f"Task Manager may show 'Python' instead of '{app_name}'")

    def _get_rcedit(self) -> Optional[Path]:
        """获取 rcedit 可执行文件路径，不存在则下载缓存"""
        from ..core.cache import CacheManager

        cache_manager = CacheManager()
        tools_dir = cache_manager.cache_dir / "tools"
        rcedit_dir = tools_dir / f"rcedit-v{self.RCEDIT_VERSION}"
        rcedit_exe = rcedit_dir / "rcedit.exe"

        # 清理旧版本缓存目录
        if tools_dir.exists():
            for d in tools_dir.iterdir():
                if d.is_dir() and d.name.startswith("rcedit-v") and d.name != f"rcedit-v{self.RCEDIT_VERSION}":
                    self.logger.info(f"Removing old rcedit cache: {d.name}")
                    shutil.rmtree(d, ignore_errors=True)

        # 已存在则验证是否可用
        if rcedit_exe.exists():
            try:
                result = subprocess.run(
                    [str(rcedit_exe), "--help"],
                    capture_output=True, text=True, timeout=5,
                )
                return rcedit_exe
            except (OSError, subprocess.TimeoutExpired):
                self.logger.warning(f"Existing rcedit is not usable, re-downloading...")
                shutil.rmtree(rcedit_dir, ignore_errors=True)

        # 下载 rcedit
        self.logger.info(f"Downloading rcedit v{self.RCEDIT_VERSION}...")
        try:
            import urllib.request

            url = self.RCEDIT_URL.format(version=self.RCEDIT_VERSION)
            rcedit_dir.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, str(rcedit_exe))

            if rcedit_exe.exists() and rcedit_exe.stat().st_size > 0:
                self.logger.success(f"rcedit downloaded to {rcedit_dir}")
                return rcedit_exe
            else:
                rcedit_exe.unlink(missing_ok=True)
                self.logger.warning("rcedit.exe download failed or file is empty")
                return None
        except Exception as e:
            rcedit_exe.unlink(missing_ok=True)
            self.logger.warning(f"Failed to download rcedit: {e}")
            return None

    def _fix_pth_file(self, runtime_dir: Path, version_dir: str, python_version: str = "3.10") -> None:
        """修改 Embeddable Python 的 _pth 文件以支持自定义导入路径"""
        pth_files = list(runtime_dir.glob("python*._pth"))
        if not pth_files:
            self.logger.warning("No _pth file found in runtime")
            return

        pth_file = pth_files[0]
        self.logger.info(f"Fixing _pth file: {pth_file}")

        ver_tag = python_version.replace(".", "")[:3]  # "3.10" -> "310", "3.11" -> "311"
        zip_name = f"python{ver_tag}.zip"

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

    def _create_zip(self, source_dir: Path, zip_path: Path, top_dir: str = ""):
        """创建 ZIP 包，排除编译源文件和 WebView2 头文件"""
        exclude_files = {
            "app_stub.cpp",
            "app_stub.rc",
            "app_stub.res",
            "build.bat",
            "WebView2.h",       # 编译时头文件，不需要分发
            "app_icon.ico",     # 编译时图标资源，已嵌入 exe
        }

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    if file_path.name in exclude_files:
                        continue
                    arcname = file_path.relative_to(source_dir)
                    if top_dir:
                        arcname = Path(top_dir) / arcname
                    zf.write(file_path, arcname)

    def _update_stub_sources(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """更新 Stub 源码（确保版本号正确）"""
        self._render_all_templates(project_dir, config)

    def _render_all_templates(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """渲染所有 Jinja2 模板并复制静态资源"""
        from jinja2 import Environment, FileSystemLoader

        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        version = self.get_app_version(config)
        port = self.get_port(config)

        template_dir = Path(__file__).parent.parent / "templates" / "shells" / "windows"
        bundle_dir = project_dir / "bundles" / "windows"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        # 处理图标：复制到 bundle 目录供 .rc 编译使用
        icon_resource = ""
        icon_str = self.get_icon(config, "windows")
        if icon_str:
            icon_candidate = project_dir / icon_str
            # 如果路径没有 .ico 后缀，自动尝试添加
            if not icon_candidate.exists() and not icon_str.lower().endswith('.ico'):
                icon_candidate = project_dir / f"{icon_str}.ico"
            if icon_candidate.exists():
                icon_dst = bundle_dir / "app_icon.ico"
                # 先删除已存在的目标文件，避免 Windows 文件锁定问题
                if icon_dst.exists():
                    try:
                        # 移除只读属性（Windows 可能从 Git 或其他来源继承此属性）
                        icon_dst.chmod(stat.S_IWRITE)
                        icon_dst.unlink()
                    except OSError as e:
                        self.logger.warning(f"Could not remove existing icon file: {icon_dst}: {e}")
                shutil.copy2(icon_candidate, icon_dst)
                icon_resource = "app_icon.ico"

        template_vars = {
            "app_name": app_name,
            "app_module": app_module,
            "version": version,
            "port": port,
            "icon_resource": icon_resource,
        }

        # 渲染模板
        self._render_template(jinja_env, "app_stub.cpp.j2", bundle_dir / "app_stub.cpp", template_vars)
        self._render_template(jinja_env, "app_stub.rc.j2", bundle_dir / "app_stub.rc", template_vars)
        self._render_template(jinja_env, "build.bat.j2", bundle_dir / "build.bat", template_vars)
        self._render_template(jinja_env, "app.ini.j2", bundle_dir / "app.ini", template_vars)

        # 复制 WebView2 头文件（非模板，直接复制，总是覆盖以保持最新）
        webview2_h_src = template_dir / "WebView2.h"
        webview2_h_dst = bundle_dir / "WebView2.h"
        if webview2_h_src.exists():
            shutil.copy2(webview2_h_src, webview2_h_dst)

    def _get_run_env(self, bundle_dir: Path, version_dir: str = "app") -> dict:
        """获取运行环境变量"""
        env = os.environ.copy()
        runtime_dir = bundle_dir / "runtime"
        app_packages_dir = bundle_dir / version_dir / "app_packages"
        app_dir = bundle_dir / version_dir / "app"

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
