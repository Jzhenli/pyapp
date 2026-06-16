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
            jdk_dir = Path.home() / ".android-jdk"
            if not jdk_dir.exists():
                missing.append("JDK not found. Run 'pyapp setup android'")
            else:
                os.environ["JAVA_HOME"] = str(jdk_dir)

        # 检查 ANDROID_HOME
        android_home = os.environ.get("ANDROID_HOME")
        if not android_home:
            sdk_dir = Path.home() / ".android-sdk"
            if not sdk_dir.exists():
                missing.append("Android SDK not found. Run 'pyapp setup android'")
            else:
                os.environ["ANDROID_HOME"] = str(sdk_dir)

        return len(missing) == 0, missing

    def create(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """创建 Android Gradle 项目结构"""
        from jinja2 import Environment, FileSystemLoader

        app_name = self.get_app_name(config)
        app_module = self.get_app_module(config)
        package_name = config.get("tool", {}).get("pyapp", {}).get("android", {}).get(
            "package_name", f"com.example.{app_module.replace('_', '')}"
        )
        min_sdk = config.get("tool", {}).get("pyapp", {}).get("android", {}).get("min_sdk", 24)
        target_sdk = config.get("tool", {}).get("pyapp", {}).get("android", {}).get("target_sdk", 34)
        version = self.get_app_version(config)
        python_version = self.get_python_version(config)

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

        # 创建 Java 源码目录和 MainActivity
        java_package_dir = manifest_dir / "java" / Path(*package_name.split("."))
        java_package_dir.mkdir(parents=True, exist_ok=True)
        main_activity = java_package_dir / "MainActivity.java"
        if not main_activity.exists():
            main_activity.write_text(self._generate_main_activity(package_name))

        # 创建 gradle wrapper
        gradle_dir = bundle_dir / "gradle" / "wrapper"
        gradle_dir.mkdir(parents=True, exist_ok=True)
        self._create_gradle_wrapper(bundle_dir)

        # 创建 local.properties
        local_props = bundle_dir / "local.properties"
        android_home = os.environ.get("ANDROID_HOME", str(Path.home() / ".android-sdk"))
        local_props.write_text(f"sdk.dir={android_home.replace(os.sep, '/')}\n")

        self.logger.success(f"Android project created at {bundle_dir}")

    def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug") -> BuildResult:
        """构建 Android APK"""
        try:
            # 1. 检查环境
            ok, missing = self.check_environment()
            if not ok:
                raise PyAppEnvironmentError(
                    f"Missing dependencies: {', '.join(missing)}",
                    "Run 'pyapp setup android' to install missing dependencies"
                )

            # 2. 创建项目结构（如果不存在）
            bundle_dir = project_dir / "bundles" / "android"
            if not bundle_dir.exists():
                self.create(project_dir, config)

            # 3. 同步 Python 源码
            self.logger.step(1, 6, "Syncing Python source code")
            self.sync_source_code(project_dir, "android", config)

            # 4. 同步前端资源
            self.logger.step(2, 6, "Syncing frontend resources")
            self.sync_frontend_dist(project_dir, "android", config)

            # 5. 安装依赖
            self.logger.step(3, 6, "Installing dependencies")
            self.install_dependencies(project_dir, config, "android")

            # 6. 运行 Gradle 构建
            self.logger.step(4, 6, "Running Gradle build")
            gradle_cmd = "gradlew.bat" if os.name == "nt" else "gradlew"
            gradle_path = bundle_dir / gradle_cmd

            build_task = "assembleDebug" if build_type == "debug" else "assembleRelease"
            result = subprocess.run(
                [str(gradle_path), build_task],
                cwd=str(bundle_dir),
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                raise BuildError(
                    f"Gradle build failed:\n{result.stderr}",
                    "Check the Gradle output for details"
                )

            # 7. 复制 APK 到 dist/
            self.logger.step(5, 6, "Copying APK to dist/")
            dist_dir = self.ensure_dist_dir(project_dir)
            app_name = self.get_app_name(config)
            version = self.get_app_version(config)

            apk_pattern = "*debug*.apk" if build_type == "debug" else "*release*.apk"
            apk_files = list((bundle_dir / "app" / "build" / "outputs" / "apk").rglob(apk_pattern))

            if not apk_files:
                raise BuildError("APK not found after build")

            apk_path = apk_files[0]
            dest_apk = dist_dir / f"{app_name}-{version}.apk"
            shutil.copy2(apk_path, dest_apk)

            self.logger.step(6, 6, "Build complete")
            self.logger.success(f"APK: {dest_apk}")

            return BuildResult(success=True, output_path=dest_apk)

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
            "package_name", f"com.example.{app_module.replace('_', '')}"
        )

        # 查找 APK
        apk_path = project_dir / "dist" / f"{app_name}-{version}.apk"
        if not apk_path.exists():
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

    def dev(self, project_dir: Path, config: Dict[str, Any]) -> None:
        """开发模式（文件监听 + 热重载）"""
        from ..core.device import DeviceManager
        from ..core.watcher import FileWatcher

        device_manager = DeviceManager()
        app_name = self.get_app_name(config)
        package_name = config.get("tool", {}).get("pyapp", {}).get("android", {}).get(
            "package_name", f"com.example.{app_name}"
        )

        # 先构建并安装
        self.logger.info("Building and installing app for development...")
        self.run(project_dir, config)

        # 检查设备
        devices = device_manager.adb_devices()
        device = devices[0] if devices else None
        if not device:
            self.logger.error("No Android device connected")
            return

        # 启动文件监听
        src_dir = project_dir / "src"

        def on_file_change(file_path: str):
            self.logger.info(f"Change detected: {file_path}")
            # 推送文件到设备
            local_path = Path(file_path)
            # 计算相对路径
            try:
                rel_path = local_path.relative_to(src_dir)
            except ValueError:
                return

            remote_path = f"/data/data/{package_name}/files/app/{rel_path}"
            device_manager.adb_push(local_path, remote_path, device)

            # 重启应用
            device_manager.adb_force_stop(package_name, device)
            device_manager.adb_start_app(package_name, device)
            self.logger.success("App restarted")

        watcher = FileWatcher(src_dir, on_file_change)
        watcher.start()

        self.logger.info("Development mode active. Press Ctrl+C to stop.")
        try:
            watcher.wait()
        except KeyboardInterrupt:
            watcher.stop()

    def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
        """打包发布版 APK（签名）"""
        # 构建发布版
        result = self.build(project_dir, config, build_type="release")
        if not result.success:
            return result

        # 签名检查
        keystore_path = os.environ.get("ANDROID_KEYSTORE_PATH")
        if not keystore_path:
            self.logger.warning(
                "ANDROID_KEYSTORE_PATH not set, APK is unsigned. "
                "Set environment variable for signed release builds."
            )
            return result

        # 使用 jarsigner 签名
        keystore_password = os.environ.get("ANDROID_KEYSTORE_PASSWORD", "")
        key_alias = os.environ.get("ANDROID_KEY_ALIAS", "release-key")

        apk_path = result.output_path
        signed_apk = apk_path.with_name(apk_path.stem + "-signed.apk")

        cmd = [
            "jarsigner",
            "-verbose",
            "-sigalg", "SHA256withRSA",
            "-digestalg", "SHA-256",
            "-keystore", keystore_path,
            "-storepass", keystore_password,
            "-signedjar", str(signed_apk),
            str(apk_path),
            key_alias,
        ]

        sign_result = subprocess.run(cmd, capture_output=True, text=True)
        if sign_result.returncode != 0:
            self.logger.error(f"Signing failed: {sign_result.stderr}")
            return BuildResult(success=False, error_message=f"Signing failed: {sign_result.stderr}")

        # 替换为签名后的 APK
        shutil.move(str(signed_apk), str(apk_path))
        self.logger.success(f"Signed APK: {apk_path}")

        return BuildResult(success=True, output_path=apk_path)

    def _render_template(self, jinja_env, template_name, output_path, variables):
        """渲染 Jinja2 模板"""
        template = jinja_env.get_template(template_name)
        content = template.render(**variables)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    def _generate_main_activity(self, package_name: str) -> str:
        """生成 MainActivity Java 代码"""
        return f'''package {package_name};

import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebSettings;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {{
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);

        webView.setWebViewClient(new WebViewClient());

        // 加载本地 FastAPI 服务
        webView.loadUrl("http://127.0.0.1:18080");
    }}

    @Override
    protected void onDestroy() {{
        if (webView != null) {{
            webView.destroy();
        }}
        super.onDestroy();
    }}
}}
'''

    def _create_gradle_wrapper(self, bundle_dir: Path):
        """创建 Gradle Wrapper 文件"""
        gradlew_content = '''#!/bin/sh
# Gradle wrapper stub - replace with actual gradle wrapper
echo "Please run: gradle wrapper"
gradle wrapper
'''
        gradlew_bat_content = '''@echo off
REM Gradle wrapper stub - replace with actual gradle wrapper
echo Please run: gradle wrapper
gradle wrapper
'''

        gradlew = bundle_dir / "gradlew"
        gradlew_bat = bundle_dir / "gradlew.bat"

        if not gradlew.exists():
            gradlew.write_text(gradlew_content, encoding="utf-8")
        if not gradlew_bat.exists():
            gradlew_bat.write_text(gradlew_bat_content, encoding="utf-8")

        # 如果系统有 gradle，生成真正的 wrapper
        try:
            subprocess.run(
                ["gradle", "wrapper"],
                cwd=str(bundle_dir),
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.warning(
                "Gradle not found. Please install Gradle or run 'gradle wrapper' in the bundle directory."
            )
