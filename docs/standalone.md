# 独立安装器

安装包自带 Node 22.23.1、Python 3.12.14、Pi 和科研后端依赖（含 Jev extra）。用户无需预装 Node、npm、Python、uv 或 Pi。下载完成后，安装过程不访问网络；使用模型和网络科研工具仍需要网络及自己的 API 账号。

v0.5.0 安装器包含 `pi-docparser`、`pi-subagents`、`pi-web-access` 和 Context7 四个内置包，以及本地 OCR 使用的英语、简体和繁体中文语言数据；保留内置 npm/npx，供 `research packages install` 使用。用户额外安装 Pi 包时仍可能需要网络及该包自己的依赖。2026-10-02 的 [四平台构建与实装检查](https://github.com/zhengye123188/research-cli/actions/runs/37019987067) 全部通过，[GitHub Release v0.5.0](https://github.com/zhengye123188/research-cli/releases/tag/v0.5.0) 已公开并设为 latest；实际检查范围见 [验证记录](validation.md)。

## 用户安装

在 macOS / Linux 终端执行：

```bash
curl -fsSL https://github.com/zhengye123188/research-cli/releases/latest/download/install.sh | sh
```

下载入口自动识别系统与 CPU，从同一版本的 GitHub Release 获取 `.run` 和 `.run.sha256`，校验通过后安装。它需要 curl 和系统 SHA-256 工具，安装包本身包含运行环境。也可以先下载并查看入口脚本，再执行 `sh install.sh`。

手动下载可打开 [公开下载页面](https://github.com/zhengye123188/research-cli/releases/latest)，在 **Assets** 中选择对应平台的 `.run` 和 `.run.sha256` 文件。无需登录 GitHub，也无需解压 ZIP。

选择与机器匹配的 `.run` 文件，在终端执行：

```bash
sh ~/Downloads/research-cli-0.5.0-darwin-arm64.run
```

请把命令中的路径替换为实际下载位置。安装器会自动校验内嵌内容；也可在两个文件所在目录提前运行 `shasum -a 256 -c research-cli-0.5.0-darwin-arm64.run.sha256`（Linux 可使用 `sha256sum -c`）。

| 文件后缀 | 平台 |
|---|---|
| darwin-arm64.run | Apple Silicon Mac |
| darwin-x64.run | Intel Mac |
| linux-x64.run | Linux x86-64，glibc |
| linux-arm64.run | Linux ARM64，glibc |

当前不支持 Windows 或 Alpine/musl。使用系统 shell、tar 和 SHA-256 工具；原生扩展和系统库仍有平台要求。兼容性以构建工作流实测系统为准，不宣称任意旧操作系统均可运行。

默认安装到 `~/.local/share/research-cli/versions/`，命令链接为 `~/.local/bin/research`，无需 sudo，也不会改写 shell 配置。首次运行：

```bash
"$HOME/.local/bin/research" configure
"$HOME/.local/bin/research"
```

`configure` 默认填入 DeepSeek 地址、deepseek-v4-pro 和 chat 协议，允许修改。密钥输入不回显，存放在 `~/.config/research-cli/api.json`（或 XDG_CONFIG_HOME 下），文件权限 0600。后续打开新终端仍可使用；环境变量优先于保存的配置。配置不会上传 GitHub，也不会随安装包分发。

若想直接输入 `research`，将 `~/.local/bin` 加入 PATH；当前窗口执行：

```bash
export PATH="$HOME/.local/bin:$PATH"
research doctor
```

要让新打开的终端也能直接输入命令，请将 `export PATH="$HOME/.local/bin:$PATH"` 加入自己的 shell 配置（macOS 默认 zsh 使用 `~/.zshrc`）。配置完成后，在任意项目文件夹打开终端，或先 `cd` 到目标项目：

```bash
cd "/你的项目目录"
research
```

当前目录自动作为工作区，读写文件、科研记忆和实验记录均围绕该项目；科研数据存放在项目 `.research/` 下。安装目录只用于存放程序和运行环境。API 配置属于用户，可在多个项目共用。界面中的 `/research-status` 可核对工作区；在同一项目运行 `research --continue` 可继续最近会话。也可以通过 `research --workspace "/你的项目目录"` 指定其他项目。

独立命令始终使用包内运行环境，不依赖 nvm 当前选择的 Node。`research setup` 会提示运行环境已包含；无须再次安装。

## 更新、回退和卸载

更新时运行新安装器；它先验证校验和、复制到新目录、检查运行环境，成功后原子切换 `current` 链接。不会覆盖其他来源的同名 `research` 命令；遇到冲突可以使用不同命令目录：

```bash
sh research-cli-0.5.0-darwin-arm64.run --prefix "$HOME/Apps/research-cli" --bin-dir "$HOME/Apps/bin"
```

下载入口同样支持这些参数：

```bash
curl -fsSL https://github.com/zhengye123188/research-cli/releases/latest/download/install.sh | sh -s -- --prefix "$HOME/Apps/research-cli" --bin-dir "$HOME/Apps/bin"
```

旧版本保留在安装目录，重新运行旧版本安装器可回退程序。数据库升级后的兼容性需单独检查：回退前保留备份，并在新工作区恢复兼容数据，不能假定旧程序可读取新版本数据库。项目中的 `.research` 数据和 API 配置独立于程序目录，更新不删除它们。卸载时删除安装器打印的命令链接及程序安装目录即可；API 配置与科研数据应按用户需要单独保留或清理。

## 开发者构建

构建机需要 Python ≥3.12、uv、curl 和 tar。构建脚本下载并校验已固定的 Node/Python 官方分发文件；使用下载的 Node 执行 npm ci，运行环境不取自本机虚拟环境。必须在目标 OS/CPU 原生构建，以匹配 npm/Python 原生依赖。

Intel Mac 构建机还需要 Xcode 命令行工具、Rust、make 和 Perl。由于上游 cryptography 已停止提供 Intel Mac wheel，构建脚本保留锁定版本，校验源包后编译，并静态链接固定版本的 OpenSSL；随后检查原生模块没有引用构建机的第三方动态库。安装用户无需这些构建工具。[上游安装说明](https://cryptography.io/en/stable/installation/)介绍了静态编译方法。

```bash
uv run --python 3.12 python scripts/build_standalone.py
uv run --python 3.12 python scripts/smoke_standalone.py dist/standalone/research-cli-0.5.0-darwin-arm64.run
# 将文件名替换为本机平台对应的产物
```

产物在 `dist/standalone/`：自解压 `.run`、可手动解压的 `.tar.gz`、各自 `.sha256`。运行环境 URL/哈希锁定在 `packaging/runtimes.json`；JS/Python 依赖锁定在 package-lock.json / uv.lock；OCR 语言数据的固定 commit、大小和 SHA-256 在 `bin/ocr.mjs`。包内 bundle.json 记录所有文件与符号链接，保留第三方许可证。校验和用于检测损坏，不等于代码签名或发布者认证。

GitHub 的 [Standalone installers](https://github.com/zhengye123188/research-cli/actions/workflows/standalone.yml) 手动工作流在四种平台构建、进行独立安装测试，并上传 Actions artifacts。默认 `publish=false` 只构建；选择 `publish=true` 时，四个平台全部通过后才会校验产物并创建同版本的 GitHub Release。工作流先上传完整草稿，再公开发布，包含四组 `.run` / `.sha256` 和 `install.sh` 下载入口。已有版本不会被覆盖。

发布前运行 `npm run version:set -- VERSION` 同步前后端、两个锁文件及下载入口的版本，再运行 `npm run version:check`，并准备对应的 `docs/releases/vVERSION.md`。GitHub 安装包发布不会上传 npm 或 PyPI；这些包需要按 [发布指南](pypi.md) 显式发布。Actions artifacts 仍可用于内部构建检查，下载要求 GitHub 登录，保留 30 天。

工作流会拒绝指向其他提交的同版本标签，也不会覆盖已有 Release。若上传中断留下草稿，先在 GitHub 检查并移除该草稿，再从同一个提交重跑；已公开版本应通过增加版本号更新。

macOS 分发目前没有 Developer ID 签名或公证；其他 Mac 上的 Gatekeeper 行为尚需实际下载验证。不能把本机构建运行通过当作 Apple 公证通过，也不应要求用户全局关闭系统保护。
