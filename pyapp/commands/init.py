"""pyapp init 命令 - 初始化新项目"""

import re
from pathlib import Path
from typing import Optional

import click
from jinja2 import Environment, FileSystemLoader

from ..core.logger import get_logger


def init_project(name: str, template: str = "fastapi", output_dir: Optional[str] = None):
    """
    初始化新项目

    Args:
        name: 项目名称
        template: 项目模板 (basic/fastapi)
        output_dir: 输出目录，默认为当前目录下的 name 子目录
    """
    logger = get_logger()

    # 验证项目名称
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name):
        raise click.ClickException(
            f"Invalid project name: {name}. "
            "Name must start with a letter and contain only letters, numbers, hyphens, and underscores."
        )

    # 确定输出目录
    if output_dir:
        project_dir = Path(output_dir)
    else:
        project_dir = Path.cwd() / name

    if project_dir.exists():
        raise click.ClickException(f"Directory already exists: {project_dir}")

    # Python 模块名（将 - 转换为 _）
    module_name = name.replace("-", "_")

    logger.info(f"Creating project '{name}' at {project_dir}")

    # 创建目录结构
    _create_project_structure(project_dir, name, module_name, template)

    logger.success(f"Project '{name}' created successfully!")
    logger.info("")
    logger.info("Next steps:")
    logger.info(f"  cd {name}")
    logger.info("  pyapp build windows      # Build for Windows")
    logger.info("  pyapp run windows        # Run the app")
    logger.info("  pyapp run windows -ur    # Update deps and run")
    logger.info("")
    logger.info("Release flow:")
    logger.info("  pyapp build windows      # Prepare bundles")
    logger.info("  pyapp compile windows    # Compile with Nuitka (optional)")
    logger.info("  pyapp package windows    # Package distributable")


def _create_project_structure(project_dir: Path, name: str, module_name: str, template: str):
    """创建项目目录结构"""

    # 创建目录
    dirs = [
        project_dir,
        project_dir / "src" / module_name,
        project_dir / "src" / module_name / "resources" / "config",
        project_dir / "src" / module_name / "resources" / "static",
        project_dir / "frontend",
        project_dir / "bundles",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # 生成 pyproject.toml
    _generate_pyproject(project_dir, name, module_name, template)

    # 生成 Python 源码
    _generate_python_files(project_dir, name, module_name, template)

    # 生成 .gitignore
    _generate_gitignore(project_dir)

    # 生成 README
    _generate_readme(project_dir, name, module_name)

    # 生成前端模板（如果选择 fastapi 模板）
    if template == "fastapi":
        _generate_frontend_template(project_dir, name, module_name)

    # 生成 CI 脚本和 Termux 编译脚本
    _generate_ci_workflows(project_dir, name, module_name)


def _generate_pyproject(project_dir: Path, name: str, module_name: str, template: str):
    """生成 pyproject.toml"""
    template_dir = Path(__file__).parent.parent / "templates" / "project"

    if (template_dir / "pyproject.toml.j2").exists():
        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
        jinja_template = jinja_env.get_template("pyproject.toml.j2")
        content = jinja_template.render(
            name=name,
            module_name=module_name,
            template=template,
        )
    else:
        # 内联模板
        content = f'''[project]
name = "{name}"
version = "0.1.0"
description = "A cross-platform application built with PyApp"
authors = [{{name = "Developer", email = "dev@example.com"}}]
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "platformdirs>=4.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "httpx>=0.24.0",
]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.pyapp]
python_version = "3.10"
app_module = "{module_name}"
port = 18080

[tool.pyapp.android]
package_name = "com.example.{module_name.replace('_', '').lower()}"
min_sdk = 24
target_sdk = 34
permissions = [
    "INTERNET",
    "FOREGROUND_SERVICE",
]

[tool.pyapp.windows]
deployment = "standalone"
create_service = true
service_name = "{name.replace('-', ' ').title().replace(' ', '')}"

[tool.pyapp.linux]
deployment = "shared"
install_systemd = true
service_name = "{name.replace('_', '-')}"
'''

    (project_dir / "pyproject.toml").write_text(content, encoding="utf-8")


def _generate_python_files(project_dir: Path, name: str, module_name: str, template: str):
    """生成 Python 源码文件"""

    src_dir = project_dir / "src" / module_name

    # __init__.py
    (src_dir / "__init__.py").write_text(
        f'"""{name}"""\n__version__ = "0.1.0"\nfrom {module_name}.main import main\n',
        encoding="utf-8"
    )

    # __main__.py
    (src_dir / "__main__.py").write_text(
        f'"""应用入口"""\nfrom {module_name}.main import main\n\nif __name__ == "__main__":\n    main()\n',
        encoding="utf-8"
    )

    # main.py
    if template == "fastapi":
        app_content = f'''"""FastAPI Application"""

import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pyapp_runtime import attach, create_server

app = FastAPI(title="{name}")
# 注册生命周期端点（/api/health、/api/shutdown、/api/restart）。
# 幂等：create_server() 内部会再次调用 attach()，不会重复注册。
attach(app)


def get_resource_dir() -> Path:
    mod = sys.modules.get("{module_name}")
    if mod and hasattr(mod, "_RESOURCE_DIR"):
        return Path(mod._RESOURCE_DIR) / "resources"
    return Path(__file__).parent / "resources"


RESOURCES_DIR = get_resource_dir()
STATIC_DIR = RESOURCES_DIR / "static"
IS_DEV_MODE = os.environ.get("APP_MODE", "production") == "dev"

FRONTEND_AVAILABLE = STATIC_DIR.exists() and any(STATIC_DIR.iterdir())
if FRONTEND_AVAILABLE:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
elif not IS_DEV_MODE:
    print(f"Warning: Frontend not found at {{STATIC_DIR}}")


@app.get("/")
async def index():
    if FRONTEND_AVAILABLE:
        return FileResponse(STATIC_DIR / "index.html")
    return JSONResponse({{
        "message": "Frontend not available",
        "mode": "development" if IS_DEV_MODE else "production",
        "hints": ["cd frontend && npm run dev", "npm run build && pyapp build <platform>", "/docs"]
    }})


def main(host="0.0.0.0", port=None, access_log=True):
    """应用入口（阻塞运行）"""
    create_server(app, host=host, port=port, access_log=access_log).run()
'''
    else:
        app_content = f'''"""应用入口"""

def main(**kwargs):
    """启动应用"""
    print("Hello from {name}!")


if __name__ == "__main__":
    main()
'''

    (src_dir / "main.py").write_text(app_content, encoding="utf-8")


def _generate_gitignore(project_dir: Path):
    """生成 .gitignore"""
    content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
*.egg

# Virtual environments
.venv/
venv/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo

# PyApp
bundles/
frontend/dist/
frontend/node_modules/

# OS
.DS_Store
Thumbs.db
"""
    (project_dir / ".gitignore").write_text(content, encoding="utf-8")


def _generate_readme(project_dir: Path, name: str, module_name: str):
    """生成 README.md"""
    content = f"""# {name}

A cross-platform application built with PyApp.

## Development

```bash
# Build and run
pyapp build windows
pyapp run windows

# Update source code and run
pyapp run windows -u

# Rebuild dependencies and run
pyapp run windows -ur
```

## Release

```bash
# Build → (optional) compile → package
pyapp build windows
pyapp compile windows    # optional, requires Nuitka
pyapp package windows

# Cross-platform
pyapp build linux --arch aarch64
pyapp build android --arch arm64-v8a
```

## Project Structure

```
{name}/
├── pyproject.toml          # Project configuration
├── src/{module_name}/      # Python source code
│   ├── __init__.py
│   ├── __main__.py         # Entry point
│   ├── main.py             # FastAPI application
│   └── resources/          # Static resources
├── frontend/               # Frontend project (optional)
├── .github/workflows/      # CI scripts (auto-generated)
├── scripts/                # Termux compile script (auto-generated)
└── bundles/                # Platform build output
```
"""
    (project_dir / "README.md").write_text(content, encoding="utf-8")


def _generate_frontend_template(project_dir: Path, name: str, module_name: str):
    """生成前端项目模板"""
    frontend_dir = project_dir / "frontend"

    # package.json
    package_json = f"""{{
  "name": "{name}-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "vue": "^3.4.0"
  }},
  "devDependencies": {{
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.0.0"
  }}
}}
"""
    (frontend_dir / "package.json").write_text(package_json, encoding="utf-8")

    # vite.config.ts
    # Use environment variable VITE_API_PORT for development proxy
    # Default to 18080 if not set
    vite_config = """import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/static/',  // Static files are mounted at /static in FastAPI
  server: {
    // Proxy /api to backend during development
    // Set VITE_API_PORT environment variable to match pyproject.toml port
    proxy: {
      '/api': {
        target: `http://localhost:${process.env.VITE_API_PORT || 18080}`,
        changeOrigin: true,
      }
    }
  }
})
"""
    (frontend_dir / "vite.config.ts").write_text(vite_config, encoding="utf-8")

    # .env.development - for local development
    env_dev = """# Backend API port for development
# Should match the port in pyproject.toml [tool.pyapp].port
VITE_API_PORT=18080
"""
    (frontend_dir / ".env.development").write_text(env_dev, encoding="utf-8")

    # src/App.vue
    src_dir = frontend_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    app_vue = """<template>
  <div id="app">
    <h1>PyApp Application</h1>
    <p>Frontend is working!</p>
    <p>API Status: {{ status }}</p>
  </div>
</template>

<script>
export default {
  name: 'App',
  data() {
    return {
      status: 'loading...'
    }
  },
  async mounted() {
    try {
      const res = await fetch('/api/health')
      const data = await res.json()
      this.status = data.status
    } catch (e) {
      this.status = 'error'
    }
  }
}
</script>

<style>
#app {
  font-family: Arial, sans-serif;
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
}
</style>
"""
    (src_dir / "App.vue").write_text(app_vue, encoding="utf-8")

    # src/main.ts
    main_ts = """import { createApp } from 'vue'
import App from './App.vue'

createApp(App).mount('#app')
"""
    (src_dir / "main.ts").write_text(main_ts, encoding="utf-8")

    # index.html
    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PyApp Application</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
"""
    (frontend_dir / "index.html").write_text(index_html, encoding="utf-8")


def _generate_ci_workflows(project_dir: Path, name: str, module_name: str):
    """生成 GitHub Actions CI 脚本和 Termux 编译脚本"""
    logger = get_logger()

    ci_template_dir = Path(__file__).parent.parent / "templates" / "ci"
    if not ci_template_dir.exists():
        logger.warning(f"CI template directory not found: {ci_template_dir}, skipping CI generation")
        return

    jinja_env = Environment(loader=FileSystemLoader(str(ci_template_dir)))

    # CI 模板使用 {% raw %} 包裹，无需渲染变量
    render_ctx = {
        "name": name,
        "module_name": module_name,
    }

    # 1. 生成 CI workflow 脚本
    workflows_dir = project_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    for template_name in ["build-windows.yml.j2", "build-linux.yml.j2", "build-android.yml.j2"]:
        jinja_template = jinja_env.get_template(template_name)
        content = jinja_template.render(**render_ctx)
        output_name = template_name.replace(".j2", "")
        (workflows_dir / output_name).write_text(content, encoding="utf-8")
    logger.info("Generated CI workflows: .github/workflows/")
