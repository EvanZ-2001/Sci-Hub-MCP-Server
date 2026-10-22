# Sci-Hub MCP 服务端——维护分支

[英文](README.md) | **简体中文**

这是一个本地 MCP 服务端，可以按 DOI、标题或关键词查找学术论文，获取 Crossref 元数据，并下载 PDF。

本项目基于 [JackKuo666/Sci-Hub-MCP-Server](https://github.com/JackKuo666/Sci-Hub-MCP-Server) 创建分支，修复了原实现中无法发现和下载 PDF 的问题。保留原有五个 MCP 工具名称，并增加标题消歧、备用镜像切换及 PDF 内容检查。修改记录和来源署名分别见[更新日志](CHANGELOG.md)与[署名说明](NOTICE.md)。

## 环境要求

- Python **3.12** 和 Git。仓库中的依赖锁定文件以 Python 3.12 为目标版本。
- 能够访问 Crossref，以及至少一个已配置的镜像和相应 PDF 文件所在的主机。无需 API 密钥。
- 支持通过标准输入输出连接本地 MCP 服务端的客户端，例如 Codex 或 Claude Desktop。

首个版本已在 Windows 10、Python 3.12.10 环境中完成本机验证。GitHub Actions 使用 Python 3.12，在 Windows、Ubuntu 和 macOS 上检查依赖安装、离线回归测试与 MCP 启动。持续集成不检查外部网络的可用性。

## 安装

克隆稳定版本：

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/EvanZ-2001/Sci-Hub-MCP-Server.git
cd Sci-Hub-MCP-Server
```

在 Windows PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -B verify_release.py
```

在 Linux 或 macOS 中执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -B verify_release.py
```

也可以使用 [uv](https://docs.astral.sh/uv/)：

```sh
uv venv --python 3.12
uv pip sync requirements.lock.txt
```

使用 `requirements.lock.txt` 可以复现此版本的依赖环境。`requirements.txt` 列出了供开发使用的直接依赖及版本范围。项目已不再依赖旧的 `scihub` 软件包。

## 镜像与代理

无需创建配置文件即可启动。服务端默认依次尝试以下镜像：

1. `https://www.sci-hub.st`
2. `https://sci-hub.su`
3. `https://www.sci-hub.ru`
4. `https://sci-hub.red`
5. `https://sci-hub.box`
6. `https://sci-hub.al`
7. `https://sci-hub.mk`
8. `https://sci-hub.ee`

这些地址来自此前测试过的镜像列表，用于备用切换，不保证始终可用。同一镜像可能在一次请求中返回 PDF，在下一次请求中返回验证页面。能够打开首页也不代表能够取得 PDF。

如需自定义镜像或代理，请将 `settings.example.json` 复制为 `settings.local.json`，放在 `sci_hub_search.py` 所在目录。在 PowerShell 中使用 `Copy-Item settings.example.json settings.local.json`；在 Linux 或 macOS 中使用 `cp settings.example.json settings.local.json`。

编辑复制后的文件：

```json
{
  "mirrors": [
    "https://www.sci-hub.st",
    "https://sci-hub.su",
    "https://www.sci-hub.ru",
    "https://sci-hub.red",
    "https://sci-hub.box",
    "https://sci-hub.al",
    "https://sci-hub.mk",
    "https://sci-hub.ee"
  ],
  "proxy": ""
}
```

如果不需要显式指定 HTTP 代理，请保持 `proxy` 为空。例如，只有你的电脑确实有代理监听 `7890` 端口时，才适合填写 `http://127.0.0.1:7890`。服务端不会启动或配置代理软件。显式指定的代理只作用于本服务端的 HTTP 会话，并会关闭这些会话对环境代理配置的继承。

没有显式指定代理时，Requests 使用标准环境配置，包括 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NO_PROXY`。桌面 MCP 客户端可能不会继承终端的环境变量；必要时，请在 `settings.local.json` 或客户端的服务端环境配置中指定代理。

镜像配置优先级为：`settings.local.json` 中的非空镜像列表 → 环境变量 `SCIHUB_MIRRORS` 中以逗号分隔的地址 → 内置默认值。服务端只使用 HTTPS 镜像地址。配置文件始终从源码文件所在目录读取，不受客户端工作目录影响。Git 会忽略 `settings.local.json`，请勿提交个人配置。

## 接入 Codex

按照 [Codex 官方 MCP 配置文档](https://developers.openai.com/codex/mcp)，在 `~/.codex/config.toml` 中添加服务配置。请将示例路径替换为**你电脑上的绝对路径**。如果已有 `scihub` 配置，请修改原条目，避免重复添加。

Windows 示例：

```toml
[mcp_servers.scihub]
command = 'C:\path\to\Sci-Hub-MCP-Server\.venv\Scripts\python.exe'
args = ['-B', '-u', 'C:\path\to\Sci-Hub-MCP-Server\sci_hub_server.py']
cwd = 'C:\path\to\Sci-Hub-MCP-Server'
startup_timeout_sec = 30
tool_timeout_sec = 180
enabled = true

[mcp_servers.scihub.env]
PYTHONUTF8 = "1"
PYTHONIOENCODING = "utf-8"
PYTHONDONTWRITEBYTECODE = "1"
```

在 Linux 或 macOS 上，将 `command` 改为 `/absolute/path/Sci-Hub-MCP-Server/.venv/bin/python`，将 `args` 中的脚本路径改为 `/absolute/path/Sci-Hub-MCP-Server/sci_hub_server.py`，将 `cwd` 改为 `/absolute/path/Sci-Hub-MCP-Server`。请保留上述超时和编码设置。修改配置后，重启服务端或客户端；如果仍显示旧工具列表，请新建聊天。

## 接入其他 MCP 客户端

对于使用 JSON 格式 `mcpServers` 配置的客户端，请将以下路径替换为自己的路径。在 Windows 上可以使用正斜杠，或对反斜杠进行转义：

```json
{
  "mcpServers": {
    "scihub": {
      "command": "C:/path/to/Sci-Hub-MCP-Server/.venv/Scripts/python.exe",
      "args": ["-B", "-u", "C:/path/to/Sci-Hub-MCP-Server/sci_hub_server.py"],
      "env": {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

在 Linux 或 macOS 上，替换为 `.venv/bin/python` 解释器及脚本的绝对路径。如果客户端提供工具调用超时设置，请为检索操作预留至少 180 秒。下载时使用绝对路径，并确保目标文件的父目录已经存在。

服务端在已安装依赖的环境中通过 `python sci_hub_server.py` 启动，使用标准输入输出通信，不开放 HTTP 端口。在没有 MCP 客户端连接的终端中直接运行时，它会等待协议消息。日志写入标准错误输出。

## 工具说明

| 工具 | 输入 | 结果 |
| --- | --- | --- |
| `search_scihub_by_doi` | `doi`，可以是 DOI 或 DOI 链接 | 经过验证的 PDF 链接，或包含诊断信息的失败状态 |
| `search_scihub_by_title` | `title`；可选 `author`、`year`、`journal` | 匹配论文，或需要进一步选择的候选列表 |
| `search_scihub_by_keyword` | `keyword`；`num_results` 范围为 1–20，默认 10 | Crossref 候选记录，优先返回已找到 PDF 的论文 |
| `get_paper_metadata` | `doi` | Crossref 提供的标题、作者、年份、期刊，以及可能存在的出版社 PDF 链接 |
| `download_scihub_pdf` | `pdf_url`、`output_path` | 下载结果消息 |

检索返回 `status: success` 表示候选链接的响应内容以 `%PDF-` 开头；`pdf_verified: true` 表示已完成这项内容检查。它不代表已核实整份 PDF 的论文身份。如果来源页面声明的 DOI 与请求不一致，服务端会拒绝该页面。元数据查询成功则表示 Crossref 返回了元数据，其中的出版社 PDF 链接**没有经过验证**。

标题和关键词检索先通过 Crossref 确定候选 DOI，再查找 PDF。标题存在歧义时会返回候选列表；请提供 DOI，或进一步限定作者、年份、期刊，以选择目标论文。`num_results` 限制的是返回记录数，不保证每条记录都有 PDF。未取得 PDF 的记录会保留元数据和诊断信息。

检索的总时间预算为 140 秒，标题和关键词检索中的单个候选另有更短的时间预算。网络超时和镜像验证页面仍可能影响实际完成时间。下载先写入临时 `.part` 文件，只有传输成功后才替换目标文件。目标文件的父目录必须已经存在；已有目标文件会在下载成功时被替换，失败时保持原样。

请求示例：

- 查找 DOI 为 `10.1371/journal.pmed.0020124` 的论文，返回经过验证的 PDF 链接。
- 查找论文《Why Most Published Research Findings Are False》，限定期刊为 PLoS Medicine，年份为 2005。
- 使用关键词 `research data sharing` 检索，最多返回三条记录，并说明哪些论文有经过验证的 PDF 链接。
- 将返回的 PDF 下载到我指定的绝对路径。

## 验证与故障排查

在仓库根目录中，使用已安装依赖的 Python 环境执行：

```sh
python -B -m unittest test_local_compat -v
python -B verify_release.py
```

这些检查均为离线检查。`verify_release.py` 会初始化真实的标准输入输出 MCP 连接，并检查全部五个工具及其描述和参数。

如需进一步检查 Crossref、DOI 检索、标题检索、关键词检索、下载，以及服务端重启后的行为，请执行：

```sh
python -B verify_release.py --online
```

如果没有激活虚拟环境，请将 `python` 替换为 `.venv/bin/python` 或 `.\.venv\Scripts\python.exe`。联网检查使用一篇开放获取的 PLOS 论文样本，将 PDF、诊断信息和报告写入 `verification-output/`，该目录已被 Git 忽略。检查可能需要几分钟。失败时会显示对应步骤；请结合报告、日志及代理和镜像配置排查。仅通过离线检查不能证明网络可访问。

- `blocked`：镜像返回了验证页面。服务端会尝试其他镜像，不会自动完成验证挑战。
- `unavailable`、`not_found` 或 `timeout`：查看 `diagnostics`，检查镜像访问情况、论文是否可用及代理设置。
- TLS 错误：检查本地证书和代理配置。服务端始终启用 TLS 证书校验。
- 客户端未显示工具：检查解释器和脚本的绝对路径、依赖安装情况及客户端日志，然后重启服务端。

## 许可证与署名

上游 README 声明项目采用 MIT 许可证。本分支补充了标准[许可证文本](LICENSE)，并在[署名说明](NOTICE.md)中记录其来源。原作者为 [JackKuo666](https://github.com/JackKuo666)，参考的 xuio、mikhailnov 和 HyperD1ve 的贡献也已在署名说明中列出。

本工具仅供研究使用。请遵守版权法律并负责任地使用本工具。作者不支持或鼓励任何侵犯版权的行为。仓库和发布版本只包含软件，不包含论文合集。
