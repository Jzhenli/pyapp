# PyApp 项目创建与 GitHub 协作最佳实践

本文档描述使用 PyApp CLI 创建新项目、本地开发、提交到 GitHub 以及通过 CI/CD 自动化发布的完整最佳实践流程。

## 一、安装 PyApp CLI

```powershell
# 开发模式安装（在 pyapp 仓库根目录）
pip install -e .

# 或直接从 GitHub 安装
pip install "pyapp-cli[compile] @ git+https://github.com/Jzhenli/pyapp.git"
```

验证安装：

```powershell
pyapp --version
```

## 二、创建新项目

```powershell
# FastAPI 模板（默认，含前端 Vue + Vite + CI 工作流）
pyapp init my-app

# 基础模板（无前端）
pyapp init my-app --template basic

# 指定输出目录
pyapp init my-app -o D:\code\my-app
```

`init` 会自动生成完整的项目骨架：

```
my-app/
├── pyproject.toml          # 项目配置（含 [tool.pyapp] 配置）
├── .gitignore              # 已忽略 bundles/、frontend/node_modules/ 等
├── README.md
├── src/my_app/             # Python 源码
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py              # FastAPI 入口
│   └── resources/
├── frontend/               # Vue3 + Vite 前端
├── bundles/                # 构建中间产物（已 ignore）
└── .github/workflows/      # 自动生成的 CI：build-windows/linux/android.yml
```

## 三、本地开发与验证

```powershell
cd my-app

# 1. 构建前端静态资源
cd frontend
npm install
npm run build              # 产物到 frontend/dist/
cd ..

# 2. 准备运行时 bundles（拉取 Embeddable Python + 安装 pip 依赖 + 拷贝源码）
pyapp build windows

# 3. 运行
pyapp run windows

# 迭代开发
pyapp run windows -u       # 仅更新源码
pyapp run windows -ur      # 更新源码 + 重装依赖

# 排查问题时启用详细日志
pyapp -v build windows
pyapp logs -n 100
```

发布前可选 Nuitka 编译（保护源码 + 提升性能）：

```powershell
pyapp build windows
pyapp compile windows      # 需要 pip install nuitka ordered-set zstandard
pyapp package windows      # 输出 dist/*.zip
```

跨平台构建示例：

```powershell
pyapp build linux                       # 默认 x86_64
pyapp build linux --arch aarch64        # ARM64
pyapp build linux --arch armv7l         # ARM32
pyapp build android --arch arm64-v8a
pyapp build android --arch arm64-v8a,armeabi-v7a   # 多架构
```

## 四、初始化 Git 仓库并提交 GitHub

`pyapp init` 已生成 `.gitignore`，关键产物 `bundles/`、`dist/`、`frontend/node_modules/`、`frontend/dist/`、`.venv/` 都已忽略。

```powershell
cd my-app
git init -b main
git add .
git commit -m "chore: init project with pyapp"

# 在 GitHub 上创建空仓库 my-app（不要勾选 README/.gitignore），然后：
git remote add origin https://github.com/<your-username>/my-app.git
git push -u origin main
```

### 提交规范建议

采用 Conventional Commits，与 CI tag 命名配合：

| 前缀 | 用途 |
| ---- | ---- |
| `feat:` | 新功能 |
| `fix:` | Bug 修复 |
| `chore:` | 构建/配置/依赖等杂项 |
| `build(deps):` | 依赖升级 |
| `docs:` | 文档更新 |
| `refactor:` | 重构 |

示例：

```
feat: add user login api
fix: correct port binding on windows
chore: bump fastapi to 0.137
build(deps): update frontend packages
```

## 五、CI/CD 最佳实践（已自动配置）

`pyapp init` 已在 `.github/workflows/` 生成三个工作流：`build-windows.yml`、`build-linux.yml`、`build-android.yml`。

### 触发方式

- **Tag 触发**：`<app_name>-windows/v<version>` 或 `<app_name>-all/v<version>`
- **手动触发**：GitHub Actions 面板 → Run workflow（可勾选 Nuitka、覆盖版本号）

### CI 流程

构建前端 → 安装 pyapp → `pyapp build` → `pyapp compile` → `pyapp package` → 上传 artifact。

### 推荐发布流程

```powershell
# 1. 更新 pyproject.toml 中的 version
# 2. 提交并打 tag（tag 名 = <app_name>-<platform>/v<version>）
git add pyproject.toml
git commit -m "chore: release v0.1.0"
git tag my-app-windows/v0.1.0
git push origin main --tags

# 同时发布三平台：用 -all 前缀
git tag my-app-all/v0.1.0
git push origin my-app-all/v0.1.0
```

CI 完成后，在 Actions 页面对应 run 的 Artifacts 下载 `my-app-0.1.0-windows.zip`。

> 版本号单一来源是 `pyproject.toml` 的 `version` 字段；CI 会自动从 tag 提取并回写，确保 `pyapp build` 读到正确版本。

## 六、项目日常管理建议

1. **版本管理**：版本号统一在 `pyproject.toml` 中维护，通过 tag 触发 CI 时自动回写。
2. **分支策略**：`main` 稳定分支 + `dev` 开发分支；feature 分支用 `feat/*`、`fix/*`。
3. **依赖锁定**：前端提交 `package-lock.json`；Python 依赖在 `pyproject.toml` 中固定下限。
4. **平台依赖隔离**：Android 平台特定依赖写在 `[tool.pyapp.android].dependencies`，避免污染其他平台。
5. **不要提交的目录**：`bundles/`（中间产物）、`dist/`（发布包）、`frontend/node_modules/`、`frontend/dist/`、`.venv/` —— 均已被自动生成的 `.gitignore` 覆盖。

## 七、端到端最小示例

```powershell
pip install -e D:\code\pyapp
pyapp init demo-app
cd demo-app
git init -b main && git add . && git commit -m "chore: init"
git remote add origin https://github.com/<you>/demo-app.git
git push -u origin main

# 触发首次 Windows CI 构建（手动）
# GitHub → Actions → Build Windows App → Run workflow

# 正式发版
git tag demo-app-windows/v0.1.0
git push origin demo-app-windows/v0.1.0
```

## 八、常用命令速查

| 命令 | 说明 |
| ---- | ---- |
| `pyapp init <name>` | 创建新项目 |
| `pyapp create <platform>` | 创建平台项目结构 |
| `pyapp build <platform>` | 准备构建目录（运行时 + 源码 + 依赖） |
| `pyapp compile <platform>` | Nuitka 编译为原生二进制（可选） |
| `pyapp package <platform>` | 打包为分发文件 |
| `pyapp run <platform>` | 运行应用（不存在则自动 build） |
| `pyapp run <platform> -u` | 更新源码后运行 |
| `pyapp run <platform> -ur` | 更新依赖和源码后运行 |
| `pyapp dev <platform>` | 开发模式（热重载） |
| `pyapp deploy <platform> <target>` | 部署到设备 |
| `pyapp setup <platform>` | 安装平台依赖环境 |
| `pyapp logs [-n N] [--clear]` | 查看 / 清空日志 |
| `pyapp -v <command>` | 启用详细日志 |

## 九、相关文档

- [跨平台打包工具设计方案](./跨平台打包工具设计方案.md)
- [基于 Python 运行时的跨平台应用打包方案 (Specification v2.0)](./基于%20Python%20运行时的跨平台应用打包方案%20(Specification%20v2.0).md)
- [Windows Launcher 设计](./windows-launcher-design.md)
- [Windows Stub 预编译方案](./windows-stub-precompile-proposal.md)
- [PyApp Compile 重构](./pyapp-compile-refactor.md)
- [Android 解决方案](./ANDROID_SOLUTION.md)
