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

    # rcedit 版本（用于修改 exe 的 VERSIONINFO 和图标）
    RCEDIT_VERSION = "2.0.0"
    RCEDIT_URL = "https://github.com/electron/rcedit/releases/download/v{version}/rcedit-x64.exe"

    # 预编译 Stub 版本
    STUB_VERSION = "1.0.0"
    STUB_COMPATIBLE_VERSIONS = ["1.0.0"]  # 兼容的旧版本列表（用于回滚）

    # GitHub 配置（可通过环境变量覆盖）
    GITHUB_OWNER_ENV = "PYAPP_GITHUB_OWNER"

    def _get_stub_download_url(self) -> str:
        """获取 stub 下载 URL（运行时求值，支持环境变量覆盖）"""
        owner = os.environ.get(self.GITHUB_OWNER_ENV, "your-github-user")
        return (
            f"https://github.com/{owner}/pyapp/releases/download/"
            f"stub-v{self.STUB_VERSION}/pyapp-stub-x64.exe"
        )

    def check_environment(self) -> tuple:
        """检查 Windows 开发环境"""
        # 预编译 stub 模式下无需编译器
        return True, []

    def create(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """创建 Windows 项目结构（配置文件）"""
        bundle_dir = project_dir / "bundles" / "windows"

        if bundle_dir.exists():
            self.logger.info(f"Windows project already exists at {bundle_dir}, updating...")
        else:
            self.logger.info(f"Creating Windows project at {bundle_dir}...")

        self._render_all_templates(project_dir, config)

        self.logger.success(f"Windows project created at {bundle_dir}")

    def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug", arch=None) -> BuildResult:
        """构建 Windows 安装包"""
        try:
            bundle_dir = project_dir / "bundles" / "windows"

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

            # 1. 下载 Embeddable Python
            self.logger.step(1, 7, "Downloading Python runtime")
            from ..core.runtime import RuntimeManager
            runtime_manager = RuntimeManager()
            runtime_dir = bundle_dir / "runtime"
            runtime_manager.get_runtime("windows", python_version, runtime_dir)

            # 修改 _pth 文件以支持自定义导入路径
            self._fix_pth_file(runtime_dir, version_dir, python_version)

            # 2. 复制 python.exe 为 {app_name}-runtime.exe 并修改 VERSIONINFO
            self.logger.step(2, 7, "Creating runtime executable")
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

            # 3. 同步 Python 源码
            self.logger.step(3, 7, "Syncing Python source code")
            self.sync_source_code(project_dir, "windows", config)

            # 4. 同步前端资源
            self.logger.step(4, 7, "Syncing frontend resources")
            self.sync_frontend_dist(project_dir, "windows", config)

            # 5. 安装依赖
            self.logger.step(5, 7, "Installing dependencies")
            self.install_dependencies(project_dir, config, "windows")

            # 6. 创建 Stub exe（复制预编译 stub + rcedit 修改）
            self.logger.step(6, 7, "Creating Stub executable")
            exe_path = self._create_stub_exe(bundle_dir, app_name, version, icon_path)
            if not exe_path:
                return BuildResult(success=False, error_message="Failed to create stub executable")

            # 6.5 下载 WebView2Loader.dll（UI 模式需要）
            self._download_webview2_loader(bundle_dir)

            # 6.6 渲染 app.ini
            self._render_all_templates(project_dir, config)

            # 7. 写入构建元数据
            self.logger.step(7, 7, "Writing build metadata")
            self._write_build_meta(bundle_dir, "windows", config, arch="x86_64", build_type=build_type)

            self.logger.success(f"Build prepared at {bundle_dir}")

            return BuildResult(success=True, output_path=bundle_dir)

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

        # 查找 exe
        exe_path = bundle_dir / f"{app_name}.exe"

        if exe_path.exists():
            subprocess.Popen([str(exe_path)], cwd=str(bundle_dir))
            self.logger.info(f"Started {exe_path}")
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

    def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
        """打包 Windows 分发文件（不再调用 build）"""
        try:
            bundle_dir = project_dir / "bundles" / "windows"

            if not bundle_dir.exists():
                raise BuildError(
                    f"Bundle directory not found: {bundle_dir}",
                    "Run 'pyapp build windows' first"
                )

            # 从 build.meta.json 读取 arch 和元数据
            meta = self._read_build_meta(bundle_dir)
            app_name = meta["app_name"]
            version = meta["version"]
            arch = meta["arch"]

            # 打包 ZIP
            dist_dir = self.ensure_dist_dir(project_dir)
            zip_filename = f"{app_name}-{version}-windows-{arch}.zip"
            zip_path = dist_dir / zip_filename

            self._create_zip(bundle_dir, zip_path, zip_filename.replace(".zip", ""))

            self.logger.success(f"Package created: {zip_path}")

            # 签名（可选，后续实现）
            # if sign_config:
            #     self._sign_exe(bundle_dir / f"{app_name}.exe")

            return BuildResult(success=True, output_path=zip_path)

        except Exception as e:
            return BuildResult(success=False, error_message=str(e))

    # ========== Stub 管理（预编译模式） ==========

    def _get_stub_exe(self) -> Optional[Path]:
        """获取预编译 stub exe（内置优先，远程 fallback，支持回滚）"""
        import urllib.request
        from ..core.cache import CacheManager

        cache_manager = CacheManager()
        tools_dir = cache_manager.cache_dir / "tools"

        # 优先级 1：内置 stub（零网络依赖）
        builtin_stub = Path(__file__).parent.parent / "stubs" / "windows" / "pyapp-stub-x64.exe"
        if builtin_stub.exists() and builtin_stub.stat().st_size > 0:
            self.logger.info(f"Using builtin stub: {builtin_stub}")
            return builtin_stub

        # 优先级 2：缓存 stub（当前版本）
        stub_dir = tools_dir / f"pyapp-stub-v{self.STUB_VERSION}"
        stub_exe = stub_dir / "pyapp-stub.exe"
        if stub_exe.exists() and stub_exe.stat().st_size > 0:
            self.logger.info(f"Using cached stub v{self.STUB_VERSION}: {stub_exe}")
            return stub_exe

        # 优先级 3：从 GitHub Release 下载
        self.logger.info(f"Downloading stub v{self.STUB_VERSION}...")
        try:
            stub_dir.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(self._get_stub_download_url(), str(stub_exe))

            if stub_exe.exists() and stub_exe.stat().st_size > 0:
                self.logger.success(f"Stub downloaded: {stub_exe}")
                return stub_exe
            else:
                stub_exe.unlink(missing_ok=True)
                self.logger.error("Stub download failed or file is empty")
        except Exception as e:
            self.logger.error(f"Failed to download stub: {e}")

        # 优先级 4：回滚到兼容的旧版本
        for old_version in self.STUB_COMPATIBLE_VERSIONS:
            if old_version == self.STUB_VERSION:
                continue  # 跳过当前版本（已尝试）
            old_stub_dir = tools_dir / f"pyapp-stub-v{old_version}"
            old_stub_exe = old_stub_dir / "pyapp-stub.exe"
            if old_stub_exe.exists() and old_stub_exe.stat().st_size > 0:
                self.logger.warning(f"Using fallback stub v{old_version}: {old_stub_exe}")
                return old_stub_exe

        self.logger.error("No stub available")
        return None

    def _create_stub_exe(self, bundle_dir: Path, app_name: str, version: str,
                         icon_path: Optional[Path] = None) -> Optional[Path]:
        """复制预编译 stub 并用 rcedit 修改图标和版本信息"""
        stub_src = self._get_stub_exe()
        if not stub_src:
            self.logger.error("Pre-built stub not available")
            return None

        exe_path = bundle_dir / f"{app_name}.exe"

        # 清理旧的 stub exe（app_name 变更时残留）
        for old_exe in bundle_dir.glob("*.exe"):
            if old_exe.name != f"{app_name}.exe" and not old_exe.name.endswith("-runtime.exe"):
                old_exe.unlink(missing_ok=True)

        # 复制预编译 stub
        shutil.copy2(stub_src, exe_path)
        self.logger.info(f"Copied stub -> {exe_path.name}")

        # 用 rcedit 修改 VERSIONINFO 和图标
        rcedit_path = self._get_rcedit()
        if rcedit_path:
            try:
                cmd = [
                    str(rcedit_path),
                    str(exe_path),
                    "--set-version-string", "FileDescription", app_name,
                    "--set-version-string", "ProductName", app_name,
                    "--set-version-string", "OriginalFilename", f"{app_name}.exe",
                    "--set-version-string", "InternalName", app_name,
                    "--set-file-version", version,
                    "--set-product-version", version,
                ]
                if icon_path and icon_path.exists():
                    cmd.extend(["--set-icon", str(icon_path)])
                subprocess.run(cmd, capture_output=True, text=True, check=True)
                self.logger.success(f"VERSIONINFO updated for {exe_path.name}")
            except (subprocess.CalledProcessError, OSError) as e:
                self.logger.warning(f"rcedit failed for stub: {e}")
        else:
            self.logger.warning("rcedit not available, stub VERSIONINFO not modified")

        return exe_path

    # ========== WebView2 ==========

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

    # ========== Runtime 管理 ==========

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

    # ========== 工具方法 ==========

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
        """创建 ZIP 包，排除不需要分发的文件"""
        exclude_files = {
            "app_icon.ico",     # 图标资源，已通过 rcedit 嵌入 exe
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

    def _render_all_templates(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """渲染 Jinja2 模板（仅 app.ini）"""
        from jinja2 import Environment, FileSystemLoader

        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        version = self.get_app_version(config)
        port = self.get_port(config)

        template_dir = Path(__file__).parent.parent / "templates" / "shells" / "windows"
        bundle_dir = project_dir / "bundles" / "windows"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        template_vars = {
            "app_name": app_name,
            "app_module": app_module,
            "version": version,
            "port": port,
            "stub_version": self.STUB_VERSION,
        }

        # 只渲染 app.ini 模板
        self._render_template(jinja_env, "app.ini.j2", bundle_dir / "app.ini", template_vars)

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
