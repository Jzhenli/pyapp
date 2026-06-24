"""PyApp CLI 工具验证脚本 - 检查各模块是否正常工作"""

import sys
import traceback
from pathlib import Path

# 测试结果统计
passed = 0
failed = 0
errors = []


def test(name, func):
    """运行单个测试"""
    global passed, failed
    try:
        func()
        passed += 1
        print(f"  PASS  {name}")
    except Exception as e:
        failed += 1
        errors.append((name, e))
        print(f"  FAIL  {name}: {e}")


print("=" * 60)
print("PyApp CLI 验证脚本")
print("=" * 60)

# ===== 1. 模块导入测试 =====
print("\n[1] 模块导入测试")

def test_import_cli():
    from pyapp.cli import main
test("import pyapp.cli", test_import_cli)

def test_import_config():
    from pyapp.core.config import load_config, AppConfig
test("import pyapp.core.config", test_import_config)

def test_import_errors():
    from pyapp.core.errors import PyAppError, ConfigError, PyAppEnvironmentError, BuildError, DownloadError
test("import pyapp.core.errors", test_import_errors)

def test_import_cache():
    from pyapp.core.cache import CacheManager
test("import pyapp.core.cache", test_import_cache)

def test_import_logger():
    from pyapp.core.logger import get_logger, setup_logging
test("import pyapp.core.logger", test_import_logger)

def test_import_runtime():
    from pyapp.core.runtime import RuntimeManager, RUNTIME_SOURCES
test("import pyapp.core.runtime", test_import_runtime)

def test_import_builder():
    from pyapp.core.builder import sync_frontend_dist
test("import pyapp.core.builder", test_import_builder)

def test_import_device():
    from pyapp.core.device import DeviceManager
test("import pyapp.core.device", test_import_device)

def test_import_watcher():
    from pyapp.core.watcher import FileWatcher, HAS_WATCHDOG
test("import pyapp.core.watcher", test_import_watcher)

def test_import_platforms():
    from pyapp.platforms import get_platform, get_all_platforms, PLATFORMS
    assert "android" in PLATFORMS
    assert "windows" in PLATFORMS
    assert "linux" in PLATFORMS
test("import pyapp.platforms", test_import_platforms)

def test_import_commands():
    from pyapp.commands.init import init_project
    from pyapp.commands.create import create_platform
    from pyapp.commands.build import build_platform
    from pyapp.commands.run import run_platform
    from pyapp.commands.compile import compile_platform
    from pyapp.commands.package import package_platform
    from pyapp.commands.deploy import deploy_platform
    from pyapp.commands.setup import setup_platform
    from pyapp.commands.logs import show_logs, clear_logs
test("import pyapp.commands.*", test_import_commands)

# ===== 2. 核心模块功能测试 =====
print("\n[2] 核心模块功能测试")

def test_config_dataclass():
    from pyapp.core.config import ProjectConfig, PyAppConfig, AppConfig
    project = ProjectConfig(name="test", version="0.1.0")
    pyapp = PyAppConfig(app_module="test")
    config = AppConfig(project=project, pyapp=pyapp)
    assert config.project.name == "test"
    d = config.to_dict()
    assert d["project"]["name"] == "test"
test("AppConfig 数据类", test_config_dataclass)

def test_merged_dependencies():
    from pyapp.core.config import ProjectConfig, PyAppConfig, AppConfig
    project = ProjectConfig(
        name="test", version="0.1.0",
        dependencies=["fastapi>=0.115.0", "numpy>=1.20"]
    )
    pyapp = PyAppConfig(
        app_module="test",
        android={"dependencies": ["numpy==1.26.4", "pillow>=9.0"]}
    )
    config = AppConfig(project=project, pyapp=pyapp)
    merged = config.get_merged_dependencies("android")
    # numpy 应被覆盖，fastapi 保留，pillow 追加
    names = [d.split(">=")[0].split("==")[0].lower() for d in merged]
    assert "fastapi" in names, f"fastapi missing in {merged}"
    assert "numpy" in names, f"numpy missing in {merged}"
    assert "pillow" in names, f"pillow missing in {merged}"
    # numpy 应该是 1.26.4 版本
    numpy_dep = [d for d in merged if d.lower().startswith("numpy")][0]
    assert "1.26.4" in numpy_dep, f"numpy not overridden: {numpy_dep}"
test("依赖合并逻辑", test_merged_dependencies)

def test_error_classes():
    from pyapp.core.errors import PyAppError, ConfigError, PyAppEnvironmentError, BuildError
    e = ConfigError("test error", hint="fix it")
    assert str(e) == "test error\n  Hint: fix it"
    # PyAppEnvironmentError 不应遮蔽内置 EnvironmentError
    assert PyAppEnvironmentError is not EnvironmentError
test("错误类层次", test_error_classes)

def test_cache_manager():
    from pyapp.core.cache import CacheManager
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(Path(tmpdir))
        # 测试基本操作
        assert cache.get("test-key") is None
        # 创建临时文件
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("hello")
        result = cache.put("test-key", test_file)
        assert result.exists()
        assert cache.get("test-key") is not None
        assert cache.delete("test-key") is True
        assert cache.get("test-key") is None
test("CacheManager 基本操作", test_cache_manager)

def test_logger():
    from pyapp.core.logger import get_logger
    logger1 = get_logger("test1")
    logger2 = get_logger("test2")
    # 不同名称应返回不同实例
    assert logger1 is not logger2
    # 相同名称应返回相同实例
    logger1_again = get_logger("test1")
    assert logger1 is logger1_again
test("Logger 多实例", test_logger)

def test_platform_base():
    from pyapp.platforms import get_platform
    from pyapp.platforms.base import BuildResult
    # 测试 BuildResult
    r = BuildResult(success=True, output_path=Path("/tmp/test"))
    assert r.success
    # 测试平台实例
    for name in ["android", "windows", "linux"]:
        p = get_platform(name)
        assert p.name == name
test("平台注册机制", test_platform_base)

# ===== 3. 项目初始化测试 =====
print("\n[3] 项目初始化测试")

import tempfile
import shutil

def test_init_project():
    from pyapp.commands.init import init_project
    tmpdir = Path(tempfile.mkdtemp())
    try:
        init_project("my-app", template="fastapi", output_dir=str(tmpdir / "my-app"))
        project_dir = tmpdir / "my-app"
        assert (project_dir / "pyproject.toml").exists()
        assert (project_dir / "src" / "my_app" / "__init__.py").exists()
        assert (project_dir / "src" / "my_app" / "__main__.py").exists()
        assert (project_dir / "src" / "my_app" / "app.py").exists()
        assert (project_dir / "frontend" / "package.json").exists()
        assert (project_dir / ".gitignore").exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
test("init fastapi 模板", test_init_project)

def test_init_basic_template():
    from pyapp.commands.init import init_project
    tmpdir = Path(tempfile.mkdtemp())
    try:
        init_project("simple-tool", template="basic", output_dir=str(tmpdir / "simple-tool"))
        project_dir = tmpdir / "simple-tool"
        assert (project_dir / "pyproject.toml").exists()
        assert (project_dir / "src" / "simple_tool" / "app.py").exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
test("init basic 模板", test_init_basic_template)

def test_config_load():
    from pyapp.commands.init import init_project
    from pyapp.core.config import load_config
    tmpdir = Path(tempfile.mkdtemp())
    try:
        init_project("config-test", output_dir=str(tmpdir / "config-test"))
        config = load_config(tmpdir / "config-test")
        assert config.project.name == "config-test"
        assert config.pyapp.app_module == "config_test"
        assert config.pyapp.port == 18080
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
test("配置文件加载", test_config_load)

# ===== 4. 平台创建测试 =====
print("\n[4] 平台项目创建测试")

def test_create_android():
    from pyapp.commands.init import init_project
    from pyapp.commands.create import create_platform
    from pyapp.core.config import load_config
    tmpdir = Path(tempfile.mkdtemp())
    try:
        init_project("android-test", output_dir=str(tmpdir / "android-test"))
        create_platform("android", tmpdir / "android-test")
        bundle = tmpdir / "android-test" / "bundles" / "android"
        assert (bundle / "settings.gradle.kts").exists()
        assert (bundle / "app" / "build.gradle.kts").exists()
        assert (bundle / "app" / "src" / "main" / "AndroidManifest.xml").exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
test("create android", test_create_android)

def test_create_windows():
    from pyapp.commands.init import init_project
    from pyapp.commands.create import create_platform
    tmpdir = Path(tempfile.mkdtemp())
    try:
        init_project("win-test", output_dir=str(tmpdir / "win-test"))
        create_platform("windows", tmpdir / "win-test")
        bundle = tmpdir / "win-test" / "bundles" / "windows"
        assert (bundle / "app_stub.c").exists()
        assert (bundle / "build.bat").exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
test("create windows", test_create_windows)

def test_create_linux():
    from pyapp.commands.init import init_project
    from pyapp.commands.create import create_platform
    tmpdir = Path(tempfile.mkdtemp())
    try:
        init_project("linux-test", output_dir=str(tmpdir / "linux-test"))
        create_platform("linux", tmpdir / "linux-test")
        bundle = tmpdir / "linux-test" / "bundles" / "linux"
        assert (bundle / "run.sh").exists()
        assert (bundle / "install.sh").exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
test("create linux", test_create_linux)

# ===== 5. watchdog 可用性检查 =====
print("\n[5] 可选依赖检查")

def test_watchdog():
    from pyapp.core.watcher import HAS_WATCHDOG
    if HAS_WATCHDOG:
        print(f"  INFO  watchdog 已安装，dev 模式文件监听可用")
    else:
        print(f"  WARN  watchdog 未安装，dev 模式将使用简单阻塞模式")
        print(f"        安装: pip install watchdog")
test("watchdog 检查", test_watchdog)

def test_packaging():
    try:
        from packaging.version import parse
        print(f"  INFO  packaging 已安装，版本验证功能可用")
    except ImportError:
        print(f"  WARN  packaging 未安装，版本验证将跳过")
        print(f"        安装: pip install packaging")
test("packaging 检查", test_packaging)

# ===== 结果汇总 =====
print("\n" + "=" * 60)
total = passed + failed
print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
if errors:
    print("\n失败详情:")
    for name, e in errors:
        print(f"  {name}: {e}")
        traceback.print_exception(type(e), e, e.__traceback__)
        print()
print("=" * 60)

sys.exit(1 if failed > 0 else 0)
