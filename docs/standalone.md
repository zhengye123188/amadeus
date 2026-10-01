# 独立安装器

安装包自带 Node 22.23.1、Python 3.12.14、Pi 和科研后端依赖（含 Jev extra）。用户无需预装 Node、npm、Python、uv 或 Pi。下载完成后，安装过程不访问网络；使用模型和网络科研工具仍需要网络及自己的 API 账号。

## 用户安装

打开 [安装包构建页面](https://github.com/zhengye123188/research-cli/actions/workflows/standalone.yml)，选择通过的运行记录，在底部 **Artifacts** 下载对应平台的压缩包。下载 Actions artifacts 需要登录 GitHub；文件保留 30 天，目前尚未发布长期可用的 Release 下载地址。先解压下载的 ZIP，里面包含 `.run` 和 `.run.sha256` 文件。

选择与机器匹配的 `.run` 文件，在终端执行：

```bash
sh ~/Downloads/research-cli-0.2.0-darwin-arm64.run
```

如果文件解压在子目录，请把命令中的路径替换为实际文件路径。安装器会自动校验内嵌内容；也可在两个文件所在目录提前运行 `shasum -a 256 -c research-cli-0.2.0-darwin-arm64.run.sha256`（Linux 可使用 `sha256sum -c`）。

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

独立命令始终使用包内运行环境，不依赖 nvm 当前选择的 Node。`research setup` 会提示运行环境已包含；无须再次安装。

## 更新、回退和卸载

更新时运行新安装器；它先验证校验和、复制到新目录、检查运行环境，成功后原子切换 `current` 链接。不会覆盖其他来源的同名 `research` 命令；遇到冲突可以使用不同命令目录：

```bash
sh research-cli-0.2.0-darwin-arm64.run --prefix "$HOME/Apps/research-cli" --bin-dir "$HOME/Apps/bin"
```

旧版本保留在安装目录，重新运行旧版本安装器可回退。项目中的 `.research` 数据和 API 配置独立于程序目录，更新不删除它们。卸载时删除安装器打印的命令链接及程序安装目录即可；API 配置与科研数据应按用户需要单独保留或清理。

## 开发者构建

构建机需要 Python ≥3.12、uv、curl 和 tar。构建脚本下载并校验已固定的 Node/Python 官方分发文件；使用下载的 Node 执行 npm ci，运行环境不取自本机虚拟环境。必须在目标 OS/CPU 原生构建，以匹配 npm/Python 原生依赖。

Intel Mac 构建机还需要 Xcode 命令行工具、Rust、make 和 Perl。由于上游 cryptography 已停止提供 Intel Mac wheel，构建脚本保留锁定版本，校验源包后编译，并静态链接固定版本的 OpenSSL；随后检查原生模块没有引用构建机的第三方动态库。安装用户无需这些构建工具。[上游安装说明](https://cryptography.io/en/stable/installation/)介绍了静态编译方法。

```bash
uv run --python 3.12 python scripts/build_standalone.py
uv run --python 3.12 python scripts/smoke_standalone.py dist/standalone/*.run
```

产物在 `dist/standalone/`：自解压 `.run`、可手动解压的 `.tar.gz`、各自 `.sha256`。运行环境 URL/哈希锁定在 `packaging/runtimes.json`；JS/Python 依赖锁定在 package-lock.json / uv.lock。包内 bundle.json 记录所有文件与符号链接，保留第三方许可证。校验和用于检测损坏，不等于代码签名或发布者认证。

GitHub 的 `Standalone installers` 手动工作流在四种平台构建、进行独立安装测试，并上传 Actions artifacts。它不会创建 Release 或触发 PyPI 发布。首次分发前应确认对应平台工作流通过，并把 `.run` 与 `.sha256` 一起提供给用户。

macOS 分发目前没有 Developer ID 签名或公证；其他 Mac 上的 Gatekeeper 行为尚需实际下载验证。不能把本机构建运行通过当作 Apple 公证通过，也不应要求用户全局关闭系统保护。
