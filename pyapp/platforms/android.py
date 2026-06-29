"""Android 平台实现"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any

from .base import BasePlatform, BuildResult
from ..core.logger import get_logger
from ..core.errors import BuildError, PyAppEnvironmentError


class AndroidPlatform(BasePlatform):
    """Android 平台"""

    name = "android"
    description = "Android 平台 (Chaquopy + Gradle)"

    def check_environment(self) -> tuple:
        """检查 Android 开发环境"""
        missing = []

        # 检查 JAVA_HOME
        java_home = os.environ.get("JAVA_HOME")
        if not java_home:
            jdk_base_dir = Path.home() / ".android-jdk"
            if jdk_base_dir.exists():
                # 查找实际的 JDK 目录（可能在子目录中）
                for d in jdk_base_dir.iterdir():
                    if d.is_dir() and (d / "bin" / "java.exe").exists() or (d / "bin" / "java").exists():
                        java_home = str(d)
                        os.environ["JAVA_HOME"] = java_home
                        break
                # 如果没找到子目录，检查根目录
                if not java_home and (jdk_base_dir / "bin" / "java.exe").exists():
                    java_home = str(jdk_base_dir)
                    os.environ["JAVA_HOME"] = java_home
            if not java_home:
                missing.append("JDK not found. Run 'pyapp setup android'")

        # 检查 ANDROID_HOME
        android_home = os.environ.get("ANDROID_HOME")
        if not android_home:
            sdk_dir = Path.home() / ".android-sdk"
            if sdk_dir.exists():
                os.environ["ANDROID_HOME"] = str(sdk_dir)
            else:
                missing.append("Android SDK not found. Run 'pyapp setup android'")

        return len(missing) == 0, missing

    def create(self, project_dir: Path, config: Dict[str, Any], arch: list = None) -> None:
        """创建 Android 项目结构
        
        Args:
            project_dir: 项目目录
            config: 配置字典
            arch: 目标架构列表，如 ["arm64-v8a"] 或 ["arm64-v8a", "armeabi-v7a"]
                  如果为 None，则使用 pyproject.toml 中的配置
        """
        from jinja2 import Environment, FileSystemLoader

        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        package_name = config.get("tool", {}).get("pyapp", {}).get("android", {}).get(
            "package_name", f"com.example.{app_module.replace('_', '').lower()}"
        )
        min_sdk = config.get("tool", {}).get("pyapp", {}).get("android", {}).get("min_sdk", 24)
        target_sdk = config.get("tool", {}).get("pyapp", {}).get("android", {}).get("target_sdk", 34)
        version = self.get_app_version(config)
        python_version = self.get_python_version(config, "android")
        port = self.get_port(config)

        # pip 索引配置
        android_config = config.get("tool", {}).get("pyapp", {}).get("android", {})
        pip_index_url = android_config.get("pip_index_url", "")
        pip_extra_index_urls = android_config.get("pip_extra_index_urls", [])
        pip_timeout = android_config.get("pip_timeout", 120)
        pip_proxy = android_config.get("pip_proxy", "")
        permissions = android_config.get("permissions", ["INTERNET"])
        
        # CPU 架构配置（命令行参数优先于配置文件）
        if arch is not None:
            abi_filters = arch
        else:
            abi_filters = android_config.get("abi_filters", ["arm64-v8a"])

        # 模板目录
        template_dir = Path(__file__).parent.parent / "templates" / "shells" / "android"
        bundle_dir = project_dir / "bundles" / "android"

        if bundle_dir.exists():
            self.logger.info(f"Android project already exists at {bundle_dir}, updating...")
        else:
            self.logger.info(f"Creating Android project at {bundle_dir}...")

        # Jinja2 渲染
        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        template_vars = {
            "app_name": app_name,
            "app_module": app_module,
            "package_name": package_name,
            "min_sdk": min_sdk,
            "target_sdk": target_sdk,
            "version": version,
            "python_version": python_version,
            "python_major_minor": ".".join(python_version.split(".")[:2]),
            "build_python": self._find_build_python(python_version),
            "pip_index_url": pip_index_url,
            "pip_extra_index_urls": pip_extra_index_urls,
            "pip_timeout": pip_timeout,
            "pip_proxy": pip_proxy,
            "permissions": permissions,
            "abi_filters": abi_filters,
        }

        # 渲染 settings.gradle.kts
        self._render_template(jinja_env, "settings.gradle.kts.j2", bundle_dir / "settings.gradle.kts", template_vars)

        # 渲染根 build.gradle.kts
        self._render_template(jinja_env, "build.gradle.kts.j2", bundle_dir / "build.gradle.kts", template_vars)

        # 渲染 app/build.gradle.kts
        app_dir = bundle_dir / "app"
        app_dir.mkdir(parents=True, exist_ok=True)
        self._render_template(jinja_env, "app/build.gradle.kts.j2", app_dir / "build.gradle.kts", template_vars)

        # 渲染 AndroidManifest.xml
        manifest_dir = app_dir / "src" / "main"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        self._render_template(jinja_env, "app/src/main/AndroidManifest.xml.j2", manifest_dir / "AndroidManifest.xml", template_vars)

        # 创建资源目录和文件
        res_dir = manifest_dir / "res"

        # 处理自定义图标
        icon_base = self.get_icon(config, "android")
        icon_source_dir = project_dir / icon_base if icon_base else None
        has_custom_icons = icon_source_dir and any(icon_source_dir.parent.glob(f"{icon_source_dir.name}-*.png"))

        if has_custom_icons:
            self._install_custom_icons(res_dir, icon_source_dir)
        else:
            if icon_base:
                self.logger.warning(
                    f"Icon configured as '{icon_base}' but no matching PNG files found, "
                    f"using default icons"
                )
            # 使用默认模板图标
            self._install_default_icons(res_dir, template_dir)

        # values
        values_dir = res_dir / "values"
        values_dir.mkdir(parents=True, exist_ok=True)

        # colors.xml
        colors_src = template_dir / "app/src/main/res/values/colors.xml"
        if colors_src.exists():
            shutil.copy2(colors_src, values_dir / "colors.xml")

        # strings.xml (使用模板)
        self._render_template(jinja_env, "app/src/main/res/values/strings.xml.j2", values_dir / "strings.xml", template_vars)

        # themes.xml (使用模板)
        self._render_template(jinja_env, "app/src/main/res/values/themes.xml.j2", values_dir / "themes.xml", template_vars)

        # 创建 Kotlin 源码目录
        kotlin_package_dir = manifest_dir / "java" / Path(*package_name.split("."))
        kotlin_package_dir.mkdir(parents=True, exist_ok=True)
        
        # MainActivity.kt
        main_activity = kotlin_package_dir / "MainActivity.kt"
        if not main_activity.exists():
            main_activity.write_text(self._generate_main_activity(package_name, port, app_name))

        # PythonService.kt
        python_service = kotlin_package_dir / "PythonService.kt"
        if not python_service.exists():
            python_service.write_text(self._generate_python_service(package_name, port, app_name))

        # 创建 gradle wrapper
        gradle_dir = bundle_dir / "gradle" / "wrapper"
        gradle_dir.mkdir(parents=True, exist_ok=True)
        self._create_gradle_wrapper(bundle_dir)

        # 创建 gradle.properties
        gradle_props = bundle_dir / "gradle.properties"
        if not gradle_props.exists():
            gradle_props_src = template_dir / "gradle.properties"
            if gradle_props_src.exists():
                shutil.copy2(gradle_props_src, gradle_props)

        # 创建 local.properties
        local_props = bundle_dir / "local.properties"
        android_home = os.environ.get("ANDROID_HOME", str(Path.home() / ".android-sdk"))
        local_props.write_text(f"sdk.dir={android_home.replace(os.sep, '/')}\n")

        self.logger.success(f"Android project created at {bundle_dir}")

    def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug", arch: list = None) -> BuildResult:
        """构建 Android APK
        
        Args:
            project_dir: 项目目录
            config: 配置字典
            build_type: 构建类型 (debug/release)
            arch: 目标架构列表，如 ["arm64-v8a"] 或 ["arm64-v8a", "armeabi-v7a"]
                  如果为 None，则使用 pyproject.toml 中的配置
        """
        try:
            # 1. 检查环境
            ok, missing = self.check_environment()
            if not ok:
                raise PyAppEnvironmentError(
                    f"Missing dependencies: {', '.join(missing)}",
                    "Run 'pyapp setup android' to install missing dependencies"
                )

            # 获取架构配置（命令行参数优先于配置文件）
            android_config = config.get("tool", {}).get("pyapp", {}).get("android", {})
            if arch is not None:
                abi_filters = arch
            else:
                abi_filters = android_config.get("abi_filters", ["arm64-v8a"])

            # 2. 创建项目结构（如果 app 目录不存在）
            bundle_dir = project_dir / "bundles" / "android"
            app_dir = bundle_dir / "app"
            if not app_dir.exists() or not (app_dir / "build.gradle.kts").exists():
                self.create(project_dir, config, arch=abi_filters)

            # 3. 同步 Python 源码到 Chaquopy 默认位置
            self.logger.step(1, 4, "Syncing Python source code")
            self._sync_python_source(project_dir, bundle_dir, config)

            # 4. 同步前端资源
            self.logger.step(2, 4, "Syncing frontend resources")
            self._sync_frontend_dist(project_dir, bundle_dir, config)

            # 5. 更新 build.gradle.kts 中的依赖配置
            self.logger.step(3, 4, "Configuring Chaquopy dependencies")
            self._update_chaquopy_dependencies(bundle_dir, config)

            # 6. 写入构建元数据（含 build_type，供 package 阶段决定 Gradle 任务）
            self.logger.step(4, 4, "Writing build metadata")
            self._write_build_meta(bundle_dir, "android", config, arch=abi_filters, build_type=build_type)

            self.logger.success(f"Build prepared at {bundle_dir}")

            return BuildResult(success=True, output_path=bundle_dir)

        except (BuildError, PyAppEnvironmentError) as e:
            self.logger.error(str(e))
            return BuildResult(success=False, error_message=str(e))
        except Exception as e:
            self.logger.error(f"Build failed: {e}", exc_info=True)
            return BuildResult(success=False, error_message=str(e))

    def run(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """安装并运行 Android 应用"""
        from ..core.device import DeviceManager

        device_manager = DeviceManager()
        app_name = self.get_app_name(config)
        version = self.get_app_version(config)
        app_module = self.get_app_module(config)
        package_name = config.get("tool", {}).get("pyapp", {}).get("android", {}).get(
            "package_name", f"com.example.{app_module.replace('_', '').lower()}"
        )

        # 查找 APK（按新命名格式查找，回退到旧格式）
        dist_dir = project_dir / "dist"
        apk_path = None
        if dist_dir.exists():
            # 优先按架构精确查找新格式: {app_name}-{version}-android-{arch}.apk
            android_config = config.get("tool", {}).get("pyapp", {}).get("android", {})
            abi_filters = android_config.get("abi_filters", ["arm64-v8a"])
            arch_suffix = "_".join(a.replace("-", "_") for a in abi_filters)
            specific_apk = dist_dir / f"{app_name}-{version}-android-{arch_suffix}.apk"
            if specific_apk.exists():
                apk_path = specific_apk
            else:
                # 查找任意新格式 APK
                apk_files = sorted(dist_dir.glob(f"{app_name}-{version}-android-*.apk"))
                if apk_files:
                    apk_path = apk_files[-1]
                # 回退旧格式: {app_name}-{version}.apk
                elif (dist_dir / f"{app_name}-{version}.apk").exists():
                    apk_path = dist_dir / f"{app_name}-{version}.apk"
        if not apk_path or not apk_path.exists():
            # 尝试构建
            self.logger.info("APK not found, building first...")
            result = self.build(project_dir, config)
            if not result.success:
                return
            apk_path = result.output_path

        # 安装 APK
        devices = device_manager.adb_devices()
        device = devices[0] if devices else None

        if not device:
            self.logger.error("No Android device connected")
            return

        if not device_manager.adb_install(apk_path, device):
            return

        # 启动应用
        device_manager.adb_start_app(package_name, device)

    def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
        """打包 Android APK（运行 Gradle + 签名，不再调用 build）"""
        try:
            bundle_dir = project_dir / "bundles" / "android"

            if not bundle_dir.exists():
                raise BuildError(
                    f"Bundle directory not found: {bundle_dir}",
                    "Run 'pyapp build android' first"
                )

            # 从 build.meta.json 读取 arch 和 build_type
            meta = self._read_build_meta(bundle_dir)
            app_name = meta["app_name"]
            version = meta["version"]
            abi_filters = meta["arch"]
            build_type = meta["build_type"]

            # 运行 Gradle 构建
            build_task = "assembleDebug" if build_type == "debug" else "assembleRelease"
            gradle_cmd = "gradlew.bat" if os.name == "nt" else "gradlew"
            gradle_path = bundle_dir / gradle_cmd

            env = os.environ.copy()
            if "JAVA_HOME" not in env or not Path(env["JAVA_HOME"]).exists():
                jdk_base_dir = Path.home() / ".android-jdk"
                if jdk_base_dir.exists():
                    for d in jdk_base_dir.iterdir():
                        if d.is_dir() and ((d / "bin" / "java.exe").exists() or (d / "bin" / "java").exists()):
                            env["JAVA_HOME"] = str(d)
                            break
            if "ANDROID_HOME" not in env:
                sdk_dir = Path.home() / ".android-sdk"
                if sdk_dir.exists():
                    env["ANDROID_HOME"] = str(sdk_dir)

            self._preload_gradle_distribution(bundle_dir, env)

            self.logger.info(f"Running Gradle {build_task}...")
            self.logger.info(f"Target architectures: {', '.join(abi_filters)}")
            result = subprocess.run(
                [str(gradle_path), "--console", "plain", build_task],
                cwd=str(bundle_dir),
                capture_output=True,
                text=True,
                env=env,
            )

            if result.stdout:
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if "Chaquopy: Installing for" in line:
                        self.logger.info(f"")
                        self.logger.info(f"Installing packages for {line.split('Installing for')[-1].strip()}:")
                    elif line.startswith("Successfully installed "):
                        packages = line[len("Successfully installed "):].strip()
                        for pkg in packages.split():
                            self.logger.info(f"  {pkg}")
                    elif line.startswith("Downloading "):
                        self.logger.info(f"  {line}")
                    elif any(keyword in line for keyword in ["BUILD", "FAILED", "SUCCESS", "actionable"]):
                        self.logger.info(f"  {line}")

            if result.returncode != 0:
                if result.stderr:
                    self.logger.error(result.stderr)
                raise BuildError(
                    f"Gradle build failed",
                    "Check the Gradle output for details"
                )

            # 复制 APK 到 dist/
            dist_dir = self.ensure_dist_dir(project_dir)
            apk_pattern = "*debug*.apk" if build_type == "debug" else "*release*.apk"
            apk_files = list((bundle_dir / "app" / "build" / "outputs" / "apk").rglob(apk_pattern))

            if not apk_files:
                raise BuildError("APK not found after build")

            apk_path = apk_files[0]
            arch_suffix = "_".join(a.replace("-", "_") for a in abi_filters)
            dest_apk = dist_dir / f"{app_name}-{version}-android-{arch_suffix}.apk"
            shutil.copy2(apk_path, dest_apk)

            self.logger.success(f"APK: {dest_apk}")

            # 签名（可选）
            keystore_path = os.environ.get("ANDROID_KEYSTORE_PATH")
            if not keystore_path:
                self.logger.warning(
                    "ANDROID_KEYSTORE_PATH not set, APK is unsigned. "
                    "Set environment variable for signed release builds."
                )
                return BuildResult(success=True, output_path=dest_apk)

            # 使用 jarsigner 签名
            keystore_password = os.environ.get("ANDROID_KEYSTORE_PASSWORD", "")
            key_alias = os.environ.get("ANDROID_KEY_ALIAS", "release-key")

            signed_apk = dest_apk.with_name(dest_apk.stem + "-signed.apk")

            cmd = [
                "jarsigner",
                "-verbose",
                "-sigalg", "SHA256withRSA",
                "-digestalg", "SHA-256",
                "-keystore", keystore_path,
                "-storepass", keystore_password,
                "-signedjar", str(signed_apk),
                str(dest_apk),
                key_alias,
            ]

            sign_result = subprocess.run(cmd, capture_output=True, text=True)
            if sign_result.returncode != 0:
                self.logger.error(f"Signing failed: {sign_result.stderr}")
                return BuildResult(success=False, error_message=f"Signing failed: {sign_result.stderr}")

            # 替换为签名后的 APK
            shutil.move(str(signed_apk), str(dest_apk))
            self.logger.success(f"Signed APK: {dest_apk}")

            return BuildResult(success=True, output_path=dest_apk)

        except (BuildError, PyAppEnvironmentError) as e:
            self.logger.error(str(e))
            return BuildResult(success=False, error_message=str(e))
        except Exception as e:
            self.logger.error(f"Package failed: {e}", exc_info=True)
            return BuildResult(success=False, error_message=str(e))

    def _render_template(self, jinja_env, template_name, output_path, variables):
        """渲染 Jinja2 模板"""
        template = jinja_env.get_template(template_name)
        content = template.render(**variables)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    def _update_chaquopy_dependencies(self, bundle_dir: Path, config: Dict[str, Any]) -> None:
        """更新 build.gradle.kts 中的 Chaquopy pip 依赖配置"""
        import re

        # 获取依赖列表
        dependencies = config.get("project", {}).get("dependencies", [])
        android_config = config.get("tool", {}).get("pyapp", {}).get("android", {})
        platform_dependencies = android_config.get("dependencies", [])
        app_module = config.get("tool", {}).get("pyapp", {}).get("app_module", "app")

        # 合并依赖（平台特定依赖优先）
        all_dependencies = self._merge_dependencies(dependencies, platform_dependencies)

        if not all_dependencies:
            self.logger.info("No dependencies to configure")
            return

        self.logger.info(f"Dependencies: {', '.join(all_dependencies)}")

        # 获取 pip 配置
        pip_index_url = android_config.get("pip_index_url", "")
        pip_extra_index_urls = android_config.get("pip_extra_index_urls", [
            "https://chaquo.com/pypi-13.1",
            "https://pypi.org/simple",
        ])
        pip_timeout = android_config.get("pip_timeout", 120)
        pip_proxy = android_config.get("pip_proxy", "")

        # 读取并更新 build.gradle.kts
        build_gradle_path = bundle_dir / "app" / "build.gradle.kts"
        if not build_gradle_path.exists():
            self.logger.warning("app/build.gradle.kts not found")
            return

        content = build_gradle_path.read_text(encoding="utf-8")

        # 更新 extractPackages 配置
        extract_pattern = r'extractPackages\s*\([^)]*\)'
        extract_line = f'extractPackages("{app_module}.resources")'
        content = re.sub(extract_pattern, extract_line, content)

        # 构建 pip 配置
        pip_config_lines = []

        if pip_index_url:
            pip_config_lines.append(f'            options("--index-url", "{pip_index_url}")')

        for extra_url in pip_extra_index_urls:
            pip_config_lines.append(f'            options("--extra-index-url", "{extra_url}")')

        if pip_timeout:
            pip_config_lines.append(f'            options("--timeout", "{pip_timeout}")')

        if pip_proxy:
            pip_config_lines.append(f'            options("--proxy", "{pip_proxy}")')

        # 添加依赖
        for dep in all_dependencies:
            pip_config_lines.append(f'            install("{dep}")')

        # 替换 pip 块
        pip_block = "pip {\n" + "\n".join(pip_config_lines) + "\n        }"

        # 使用正则替换 pip 块
        pattern = r'pip\s*\{[^}]*\}'
        new_content = re.sub(pattern, pip_block, content, flags=re.DOTALL)

        build_gradle_path.write_text(new_content, encoding="utf-8")
        self.logger.success(f"Configured {len(all_dependencies)} dependencies")

    def _sync_python_source(self, project_dir: Path, bundle_dir: Path, config: Dict[str, Any]) -> None:
        """
        同步 Python 源码到 Chaquopy 默认位置: app/src/main/python/
        
        Chaquopy 默认查找 app/src/main/python/ 目录下的 Python 文件。
        """
        src_dir = project_dir / "src"
        python_target = bundle_dir / "app" / "src" / "main" / "python"
        
        if not src_dir.exists():
            self.logger.warning(f"Source directory not found: {src_dir}")
            return
        
        # 清理旧文件
        if python_target.exists():
            shutil.rmtree(python_target)
        
        python_target.mkdir(parents=True, exist_ok=True)
        
        # 复制 src/ 下的所有 Python 包到 app/src/main/python/
        version = self.get_app_version(config)
        for item in src_dir.iterdir():
            if item.is_dir():
                # 复制 Python 包目录
                target = python_target / item.name
                shutil.copytree(item, target)
                self._inject_version(target, version)
                self.logger.info(f"Copied {item.name} → app/src/main/python/{item.name}")
            elif item.suffix == ".py":
                # 复制单个 Python 文件
                shutil.copy2(item, python_target / item.name)
                self.logger.info(f"Copied {item.name} → app/src/main/python/{item.name}")
        
        # 生成 bridge.py
        app_module = config.get("tool", {}).get("pyapp", {}).get("app_module", "app")
        bridge_py = python_target / "bridge.py"
        bridge_py.write_text(self._generate_bridge_py(app_module), encoding="utf-8")
        self.logger.info("Generated bridge.py")
        
        self.logger.success(f"Synced source code to app/src/main/python/")

    def _sync_frontend_dist(self, project_dir: Path, bundle_dir: Path, config: Dict[str, Any]) -> None:
        """
        同步前端编译产物到 Chaquopy Python 包目录

        源: frontend/dist/
        目标: app/src/main/python/{app_module}/resources/static/
        """
        frontend_dist = project_dir / "frontend" / "dist"
        app_module = config.get("tool", {}).get("pyapp", {}).get("app_module", "app")
        
        python_target = bundle_dir / "app" / "src" / "main" / "python"
        target_static = python_target / app_module / "resources" / "static"

        if not frontend_dist.exists():
            self.logger.warning("frontend/dist/ not found, skipping frontend sync")
            return

        # 确保 resources 目录存在
        resources_dir = python_target / app_module / "resources"
        resources_dir.mkdir(parents=True, exist_ok=True)
        
        # 确保 resources/__init__.py 存在
        resources_init = resources_dir / "__init__.py"
        if not resources_init.exists():
            resources_init.write_text('"""Resources package"""', encoding="utf-8")

        # 同步前端资源
        if target_static.exists():
            shutil.rmtree(target_static)
        shutil.copytree(frontend_dist, target_static)

        self.logger.success(f"Synced frontend/dist/ → app/src/main/python/{app_module}/resources/static/")

    def _generate_main_activity(self, package_name: str, port: int = 18080, app_name: str = "Python") -> str:
        """生成 MainActivity Kotlin 代码"""
        return f'''package {package_name}

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : AppCompatActivity() {{

    companion object {{
        private const val TAG = "MainActivity"
        private const val PYTHON_PORT = {port}
        private const val STATUS_URL = "http://127.0.0.1:$PYTHON_PORT/api/health"
        private const val MAX_RETRY_COUNT = 30
        private const val RETRY_INTERVAL_MS = 500L
    }}

    private var webView: WebView? = null
    private lateinit var rootLayout: FrameLayout
    private lateinit var loadingPanel: View
    private lateinit var progressBar: ProgressBar
    private lateinit var tvStatus: TextView

    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)

        // 创建根布局
        rootLayout = FrameLayout(this).apply {{
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }}
        setContentView(rootLayout)

        // 创建加载状态视图
        loadingPanel = createLoadingView()
        rootLayout.addView(loadingPanel)

        // 启动 Python 服务
        startPythonService()

        // 等待服务就绪
        waitForPythonReady()
    }}

    private fun createLoadingView(): View {{
        return FrameLayout(this).apply {{
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
                android.view.Gravity.CENTER
            )

            addView(ProgressBar(context).apply {{
                layoutParams = FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT
                )
                progressBar = this
            }})

            addView(TextView(context).apply {{
                layoutParams = FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT
                ).apply {{
                    topMargin = 80
                }}
                text = "正在启动..."
                textSize = 14f
                setTextColor(android.graphics.Color.parseColor("#666666"))
                tvStatus = this
            }})
        }}
    }}

    private fun createWebView(): WebView {{
        return WebView(this).apply {{
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )

            settings.apply {{
                javaScriptEnabled = true
                domStorageEnabled = true
                setSupportZoom(true)
                builtInZoomControls = true
                displayZoomControls = false
                // Disable cache to always load fresh content from Python server
                cacheMode = android.webkit.WebSettings.LOAD_NO_CACHE
                mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            }}

            webViewClient = object : WebViewClient() {{
                override fun shouldOverrideUrlLoading(
                    view: WebView?,
                    request: WebResourceRequest?
                ): Boolean {{
                    val url = request?.url.toString()
                    return when {{
                        url.startsWith("http://127.0.0.1:$PYTHON_PORT") -> false
                        url.startsWith("http://localhost:$PYTHON_PORT") -> false
                        url == "about:blank" -> false
                        else -> true
                    }}
                }}

                override fun onPageFinished(view: WebView?, url: String?) {{
                    super.onPageFinished(view, url)
                    Log.i(TAG, "Page finished loading: $url")
                }}

                override fun onReceivedError(
                    view: WebView?,
                    request: WebResourceRequest?,
                    error: android.webkit.WebResourceError?
                ) {{
                    super.onReceivedError(view, request, error)
                    Log.e(TAG, "WebView error: ${{error?.description}}")
                }}
            }}

            WebView.setWebContentsDebuggingEnabled(true)
        }}
    }}

    private fun startPythonService() {{
        tvStatus.text = "正在启动 {app_name} 服务..."
        val intent = Intent(this, PythonService::class.java)
        startForegroundService(intent)
        Log.i(TAG, "PythonService started")
    }}

    private fun waitForPythonReady() {{
        lifecycleScope.launch {{
            var retryCount = 0

            while (isActive && retryCount < MAX_RETRY_COUNT) {{
                retryCount++
                tvStatus.text = "等待 {app_name} 服务就绪... ($retryCount/$MAX_RETRY_COUNT)"

                try {{
                    if (checkPythonStatus()) {{
                        Log.i(TAG, "Python service is ready")
                        loadWebView()
                        return@launch
                    }}
                }} catch (e: Exception) {{
                    Log.d(TAG, "Python not ready yet: ${{e.message}}")
                }}

                delay(RETRY_INTERVAL_MS)
            }}

            tvStatus.text = "{app_name} 服务启动超时"
        }}
    }}

    private suspend fun checkPythonStatus(): Boolean {{
        return withContext(Dispatchers.IO) {{
            try {{
                val url = URL(STATUS_URL)
                val connection = url.openConnection() as HttpURLConnection
                connection.apply {{
                    requestMethod = "GET"
                    connectTimeout = 2000
                    readTimeout = 2000
                }}
                val responseCode = connection.responseCode
                connection.disconnect()
                responseCode == 200
            }} catch (e: Exception) {{
                false
            }}
        }}
    }}

    private fun loadWebView() {{
        runOnUiThread {{
            tvStatus.text = "加载应用界面..."

            webView = createWebView()
            rootLayout.addView(webView)

            loadingPanel.visibility = View.GONE

            webView?.loadUrl("http://127.0.0.1:$PYTHON_PORT")
        }}
    }}

    override fun onBackPressed() {{
        if (webView?.canGoBack() == true) {{
            webView?.goBack()
        }} else {{
            moveTaskToBack(true)
        }}
    }}

    override fun onDestroy() {{
        webView?.apply {{
            stopLoading()
            settings.javaScriptEnabled = false
            clearCache(true)
            clearHistory()
            removeAllViews()
            destroy()
        }}
        webView = null
        super.onDestroy()
    }}
}}
'''

    def _generate_python_service(self, package_name: str, port: int = 18080, app_name: str = "Python") -> str:
        """生成 PythonService Kotlin 代码"""
        return f'''package {package_name}

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.core.app.NotificationCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.*
import java.io.File

class PythonService : Service() {{

    companion object {{
        private const val TAG = "PythonService"
        private const val NOTIFICATION_ID = 1001
        private const val CHANNEL_ID = "python_service_channel"
        private const val PYTHON_PORT = {port}
    }}

    private val serviceScope = CoroutineScope(Dispatchers.Default + SupervisorJob())
    private var pythonJob: Job? = null

    override fun onCreate() {{
        super.onCreate()
        createNotificationChannel()
        Log.i(TAG, "PythonService created")
    }}

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {{
        startForeground(NOTIFICATION_ID, createNotification())
        startPythonServer()
        return START_STICKY
    }}

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {{
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            val channel = NotificationChannel(
                CHANNEL_ID,
                "{app_name} 服务",
                NotificationManager.IMPORTANCE_LOW
            ).apply {{
                description = "{app_name} 服务运行中"
            }}
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }}
    }}

    private fun createNotification(): Notification {{
        val intent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("{app_name} 服务")
            .setContentText("服务运行中 · 端口 $PYTHON_PORT")
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }}

    private fun startPythonServer() {{
        pythonJob?.cancel()

        pythonJob = serviceScope.launch {{
            try {{
                if (!Python.isStarted()) {{
                    Python.start(AndroidPlatform(this@PythonService))
                    Log.i(TAG, "Python runtime initialized")
                }}

                val python = Python.getInstance()

                val appDir = File(filesDir, "app").apply {{ mkdirs() }}
                val dataDir = File(filesDir, "data").apply {{ mkdirs() }}

                val bridge = python.getModule("bridge")
                val result = bridge.callAttr(
                    "start_server",
                    PYTHON_PORT,
                    appDir.absolutePath,
                    dataDir.absolutePath
                )

                Log.i(TAG, "Python server started: $result")

            }} catch (e: Exception) {{
                Log.e(TAG, "Failed to start Python server", e)
                // 通知用户服务启动失败
                Handler(Looper.getMainLooper()).post {{
                    Toast.makeText(
                        this@PythonService,
                        "{app_name} 服务启动失败: ${{e.message}}",
                        Toast.LENGTH_LONG
                    ).show()
                }}
            }}
        }}
    }}

    private fun stopPythonServer() {{
        try {{
            if (Python.isStarted()) {{
                val python = Python.getInstance()
                val bridge = python.getModule("bridge")
                bridge.callAttr("stop_server")
                Log.i(TAG, "Python server stopped")
            }}
        }} catch (e: Exception) {{
            Log.e(TAG, "Failed to stop Python server", e)
        }}
    }}

    override fun onDestroy() {{
        stopPythonServer()
        pythonJob?.cancel()
        serviceScope.cancel()
        Log.i(TAG, "PythonService destroyed")
        super.onDestroy()
    }}
}}
'''

    def _generate_bridge_py(self, app_module: str) -> str:
        """Generate bridge.py Python bridge module"""
        return f'''"""
Python Bridge for Android

Provides interface for Android layer to call Python service
"""

import threading
import logging
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("bridge")

_server = None
_server_thread: Optional[threading.Thread] = None
_actual_port: Optional[int] = None
_lock = threading.Lock()


def start_server(port: int, app_dir: str, data_dir: str) -> str:
    """
    Start FastAPI service in background thread

    Args:
        port: Service port
        app_dir: Application directory
        data_dir: Data directory

    Returns:
        Startup result message
    """
    global _server, _server_thread, _actual_port

    with _lock:
        if _server_thread and _server_thread.is_alive():
            return "Server already running"

        _server = None
        _actual_port = port

    def run_server():
        global _server
        try:
            import os

            # Set environment variables
            os.environ["APP_DIR"] = app_dir
            os.environ["APP_DATA_DIR"] = data_dir
            os.environ["APP_PORT"] = str(port)

            # create_server(app, ...) returns the uvicorn.Server handle without running.
            # _server is published before run() so stop_server() can flip should_exit.
            # 兼容性：用户 main.py 可能有本地 create_server(host, port, access_log) 包装器
            # （旧模板），也可能没有（新模板，依赖 pyapp_runtime.create_server(app, ...)）。
            # 优先用 pyapp_runtime 的统一 API，回退到用户自定义的 create_server。
            try:
                from pyapp_runtime import create_server as _create_server
                from {app_module}.main import app as _app
                server = _create_server(_app, host="127.0.0.1", port=port, access_log=False)
            except ImportError:
                # 旧项目（未安装 pyapp-runtime）：回退到用户 main.py 中的 create_server
                from {app_module}.main import create_server
                server = create_server(host="127.0.0.1", port=port, access_log=False)
            with _lock:
                _server = server

            logger.info(f"Starting server on port {{port}}")
            server.run()

        except Exception as e:
            logger.error(f"Server error: {{e}}")
            import traceback
            traceback.print_exc()

    _server_thread = threading.Thread(target=run_server, daemon=True)
    _server_thread.start()

    return f"Server starting on port {{port}}"


def stop_server() -> str:
    """
    Stop FastAPI service

    Returns:
        Stop result message
    """
    global _server

    with _lock:
        if _server:
            _server.should_exit = True
            logger.info("Server stop requested")
            return "Server stopping"

        # Thread is alive but create_server() hasn't returned the server handle yet.
        # Treat as starting so the caller knows to retry rather than misreport
        # "not running" right after start_server().
        if _server_thread and _server_thread.is_alive():
            return "Server still starting"

        return "Server not running"


def get_status() -> dict:
    """
    Get service status

    Returns:
        Status info dict
    """
    import sys

    with _lock:
        return {{
            "status": "running" if _server_thread and _server_thread.is_alive() else "stopped",
            "python_version": sys.version,
            "port": _actual_port if _server_thread and _server_thread.is_alive() else None,
        }}
'''

    @staticmethod
    def _find_build_python(python_version: str) -> str:
        """查找本地 Python 可执行文件路径，用于 Chaquopy 的 buildPython 配置

        Chaquopy 要求 buildPython 的主版本号和次版本号与 app 的 Python 版本一致。
        参考: https://chaquo.com/chaquopy/doc/current/android.html#buildpython
        """
        import shutil

        major_minor = ".".join(python_version.split(".")[:2])

        # 按优先级尝试不同的 Python 命令
        if os.name == "nt":
            # Windows: 尝试 py -X.Y, py -X, python
            candidates = [
                (["py", f"-{major_minor}"], f"py -{major_minor}"),
                (["py", f"-{python_version.split('.')[0]}"], f"py -{python_version.split('.')[0]}"),
            ]
        else:
            # Linux/Mac: 尝试 pythonX.Y, python3, python
            candidates = [
                ([f"python{major_minor}"], f"python{major_minor}"),
                (["python3"], "python3"),
            ]

        # 所有平台最后都尝试 python
        candidates.append((["python"], "python"))

        for cmd, display in candidates:
            exe_path = shutil.which(cmd[0])
            if exe_path:
                # 验证版本是否匹配
                try:
                    result = subprocess.run(
                        [exe_path] + cmd[1:] + ["--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    version_str = (result.stdout or result.stderr).strip()
                    if major_minor in version_str:
                        return exe_path.replace("\\", "/")
                except (subprocess.TimeoutExpired, OSError):
                    continue

        # 未找到匹配版本，返回空字符串（让 Chaquopy 自动查找）
        return ""

    def _preload_gradle_distribution(self, bundle_dir: Path, env: dict):
        """将 Gradle 发行版 URL 替换为本地缓存路径，避免 Java SSL 证书问题

        依赖 pyapp setup android 预下载的 Gradle 发行版缓存。
        如果缓存不存在，则检查 Gradle wrapper 自身缓存是否已有该版本，
        如果有则跳过（让 wrapper 直接使用自己的缓存）。
        """
        # 读取 gradle-wrapper.properties 获取 distributionUrl
        props_file = bundle_dir / "gradle" / "wrapper" / "gradle-wrapper.properties"
        if not props_file.exists():
            return

        props_text = props_file.read_text(encoding="utf-8")
        distribution_url = None
        for line in props_text.splitlines():
            if line.startswith("distributionUrl="):
                distribution_url = line.split("=", 1)[1].strip()
                break

        if not distribution_url or distribution_url.startswith("file://"):
            return

        # 检查 Gradle wrapper 自身缓存是否已有该版本
        # wrapper 缓存目录名格式：gradle-8.13-bin（去掉 .zip 后缀）
        filename = distribution_url.split("/")[-1]
        version_dir_name = filename.replace(".zip", "")
        wrapper_dists = Path.home() / ".gradle" / "wrapper" / "dists"
        if wrapper_dists.exists():
            dist_dir = wrapper_dists / version_dir_name
            if dist_dir.exists():
                # 检查是否有已解压的 Gradle 发行版（包含 bin/ 目录）
                for hash_dir in dist_dir.iterdir():
                    if hash_dir.is_dir():
                        for uuid_dir in hash_dir.iterdir():
                            if uuid_dir.is_dir() and (uuid_dir / "bin").exists():
                                self.logger.info(f"Gradle {version_dir_name} already in wrapper cache")
                                return

        # 检查 pyapp 预下载缓存是否存在
        local_zip = Path.home() / ".gradle" / "pyapp-cache" / filename

        if local_zip.exists():
            # 修改 gradle-wrapper.properties 使用本地文件
            local_url = local_zip.as_uri()  # 生成 file:/// URL
            new_props = props_text.replace(distribution_url, local_url)
            props_file.write_text(new_props, encoding="utf-8")
            self.logger.info(f"Using local Gradle distribution: {local_zip.name}")
        else:
            self.logger.info("Gradle distribution not cached, wrapper will download via HTTPS")
            self.logger.info("  Run 'pyapp setup android' to pre-download Gradle")

    def _create_gradle_wrapper(self, bundle_dir: Path):
        """创建 Gradle Wrapper 文件（从模板目录复制）"""
        template_dir = Path(__file__).parent.parent / "templates" / "shells" / "android"

        # 复制 gradlew (Unix)
        src_gradlew = template_dir / "gradlew"
        dst_gradlew = bundle_dir / "gradlew"
        if src_gradlew.exists():
            shutil.copy2(src_gradlew, dst_gradlew)
            # 设置可执行权限并确保 LF 行尾符（Unix shell 脚本需要）
            if os.name != "nt":
                # 转换 CRLF 为 LF
                content = dst_gradlew.read_text(encoding="utf-8")
                dst_gradlew.write_text(content.replace("\r\n", "\n"), encoding="utf-8")
                os.chmod(dst_gradlew, 0o755)
        else:
            self.logger.warning("gradlew template not found, creating stub...")
            dst_gradlew.write_text("#!/bin/sh\nexec gradle \"$@\"\n", encoding="utf-8")
            if os.name != "nt":
                os.chmod(dst_gradlew, 0o755)

        # 复制 gradlew.bat (Windows)
        src_gradlew_bat = template_dir / "gradlew.bat"
        dst_gradlew_bat = bundle_dir / "gradlew.bat"
        if src_gradlew_bat.exists():
            shutil.copy2(src_gradlew_bat, dst_gradlew_bat)
        else:
            self.logger.warning("gradlew.bat template not found, creating stub...")
            dst_gradlew_bat.write_text("@echo off\ncall gradle %*\n", encoding="utf-8")

        # 复制 gradle/wrapper 目录
        src_wrapper_dir = template_dir / "gradle" / "wrapper"
        dst_wrapper_dir = bundle_dir / "gradle" / "wrapper"
        dst_wrapper_dir.mkdir(parents=True, exist_ok=True)

        # 复制 gradle-wrapper.jar
        src_jar = src_wrapper_dir / "gradle-wrapper.jar"
        dst_jar = dst_wrapper_dir / "gradle-wrapper.jar"
        if src_jar.exists():
            shutil.copy2(src_jar, dst_jar)
        else:
            self.logger.warning(
                "gradle-wrapper.jar not found in template. "
                "Gradle wrapper may not work correctly."
            )

        # 复制 gradle-wrapper.properties
        src_props = src_wrapper_dir / "gradle-wrapper.properties"
        dst_props = dst_wrapper_dir / "gradle-wrapper.properties"
        if src_props.exists():
            shutil.copy2(src_props, dst_props)
        else:
            # 创建默认配置
            dst_props.write_text(
                "distributionBase=GRADLE_USER_HOME\n"
                "distributionPath=wrapper/dists\n"
                "distributionUrl=https://services.gradle.org/distributions/gradle-8.5-bin.zip\n"
                "networkTimeout=10000\n"
                "validateDistributionUrl=true\n"
                "zipStoreBase=GRADLE_USER_HOME\n"
                "zipStorePath=wrapper/dists\n",
                encoding="utf-8"
            )

    # 图标尺寸到 Android 密度目录的映射（方形和圆形图标共用）
    _LAUNCHER_DENSITY_MAP = {
        48: "mipmap-mdpi",
        72: "mipmap-hdpi",
        96: "mipmap-xhdpi",
        144: "mipmap-xxhdpi",
        192: "mipmap-xxxhdpi",
    }

    _ADAPTIVE_DENSITY_MAP = {
        108: "drawable-mdpi",
        162: "drawable-hdpi",
        216: "drawable-xhdpi",
        324: "drawable-xxhdpi",
        432: "drawable-xxxhdpi",
    }

    def _install_custom_icons(self, res_dir: Path, icon_source_dir: Path) -> None:
        """安装用户自定义图标（Briefcase 风格命名约定）

        图标文件命名格式: {name}-{type}-{size}.png
        - square: 方形图标 → mipmap-{density}/ic_launcher.png
        - round: 圆形图标 → mipmap-{density}/ic_launcher_round.png
        - adaptive: 自适应图标前景层 → drawable-{density}/ic_launcher_foreground.png

        Args:
            res_dir: Android res/ 目录
            icon_source_dir: 图标基础路径（如 icons/android/xplay），
                             实际文件为 icons/android/xplay-square-48.png 等
        """
        icon_name = icon_source_dir.name  # e.g. "xplay"
        icon_dir = icon_source_dir.parent  # e.g. "icons/android/"

        installed = 0

        # 安装方形图标 → mipmap-{density}/ic_launcher.png
        for size, density_dir in self._LAUNCHER_DENSITY_MAP.items():
            src = icon_dir / f"{icon_name}-square-{size}.png"
            if src.exists():
                dst_dir = res_dir / density_dir
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_dir / "ic_launcher.png")
                installed += 1

        # 安装圆形图标 → mipmap-{density}/ic_launcher_round.png
        for size, density_dir in self._LAUNCHER_DENSITY_MAP.items():
            src = icon_dir / f"{icon_name}-round-{size}.png"
            if src.exists():
                dst_dir = res_dir / density_dir
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_dir / "ic_launcher_round.png")
                installed += 1

        # 安装自适应图标前景层 → drawable-{density}/ic_launcher_foreground.png
        has_adaptive = False
        for size, density_dir in self._ADAPTIVE_DENSITY_MAP.items():
            src = icon_dir / f"{icon_name}-adaptive-{size}.png"
            if src.exists():
                dst_dir = res_dir / density_dir
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_dir / "ic_launcher_foreground.png")
                has_adaptive = True
                installed += 1

        # 创建自适应图标 XML 定义（API 26+）
        # 仅在提供了 adaptive 前景层 PNG 时才生成，否则不生成 mipmap-anydpi-v26，
        # 让系统直接使用 mipmap 中的方形/圆形图标，避免"方中圆"视觉错误
        if has_adaptive:
            mipmap_v26_dir = res_dir / "mipmap-anydpi-v26"
            mipmap_v26_dir.mkdir(parents=True, exist_ok=True)

            adaptive_icon_xml = '''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background"/>
    <foreground android:drawable="@drawable/ic_launcher_foreground"/>
</adaptive-icon>
'''
            (mipmap_v26_dir / "ic_launcher.xml").write_text(adaptive_icon_xml, encoding="utf-8")
            (mipmap_v26_dir / "ic_launcher_round.xml").write_text(adaptive_icon_xml, encoding="utf-8")

        self.logger.success(f"Installed {installed} custom icon files")

    def _install_default_icons(self, res_dir: Path, template_dir: Path) -> None:
        """安装默认模板图标（矢量图标）"""
        # mipmap-anydpi-v26 (自适应图标)
        mipmap_dir = res_dir / "mipmap-anydpi-v26"
        mipmap_dir.mkdir(parents=True, exist_ok=True)
        for icon_file in ["ic_launcher.xml", "ic_launcher_round.xml"]:
            src = template_dir / "app/src/main/res/mipmap-anydpi-v26" / icon_file
            dst = mipmap_dir / icon_file
            if src.exists():
                shutil.copy2(src, dst)

        # drawable
        drawable_dir = res_dir / "drawable"
        drawable_dir.mkdir(parents=True, exist_ok=True)
        drawable_src = template_dir / "app/src/main/res/drawable/ic_launcher_foreground.xml"
        if drawable_src.exists():
            shutil.copy2(drawable_src, drawable_dir / "ic_launcher_foreground.xml")
