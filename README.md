# Hotaru Code

Hotaru Code 用于在终端中提供 AI 编码助手能力。

它支持 TUI、交互式 Chat 和一次性 Run 三种使用模式，并具备工具调用、权限控制、会话持久化、MCP 扩展等能力。

## 功能概览

- 多种交互方式
  - `hotaru`：默认进入 TUI（Textual）
  - `hotaru chat`：交互式命令行聊天
  - `hotaru run "你的问题"`：一次性执行
- Agentic 工具调用循环
  - LLM 输出可触发工具执行，结果会回注到上下文继续推理
- 内置工具
  - `read`、`write`、`edit`、`bash`、`glob`、`grep`、`skill`
- 细粒度权限系统
  - 对 `bash`、`edit`、`read` 等按规则 `allow/ask/deny`
  - 支持“仅本次允许/始终允许/拒绝”交互
  - 内置重复工具调用（doom loop）保护
- Provider 与模型抽象
  - 支持 OpenAI、Anthropic 及 OpenAI-compatible 自定义服务
  - 通过 `provider/model` 选择模型
- MCP (Model Context Protocol)
  - 支持本地（stdio）和远程（HTTP/SSE）MCP 服务
  - MCP 工具会自动并入可调用工具列表
- Skill 系统
  - 支持从 `SKILL.md` 发现并加载领域技能
- 会话持久化
  - 会话与消息写入本地 JSON 存储，可继续/切换历史会话

## 安装与启动

### 1. 用户安装

```bash
# 安装已发布版本
uv tool install hotaru-code

# 确保可执行目录已加入 PATH（首次安装建议执行）
uv tool update-shell
```

安装后可直接运行：

```bash
hotaru
```

可选方式：

```bash
# 免安装临时运行
uvx --from hotaru-code hotaru

# 使用 pipx 安装
pipx install hotaru-code
```

### 2. 配置 API Key

至少配置一个可用 Provider 的密钥，例如：

```bash
# PowerShell
$env:OPENAI_API_KEY = "your-key"

# 或
$env:ANTHROPIC_API_KEY = "your-key"
```

### 3. 启动

```bash
# 默认进入 TUI
hotaru

# 交互式 chat
hotaru chat

# 一次性执行
hotaru run "请分析这个仓库的结构"
```

### 4. 本地开发安装（贡献者）

如果你在本仓库内开发：

```bash
uv sync
uv run hotaru
```

## 常用命令

```bash
hotaru --help
hotaru --version
hotaru providers           # 列出可用 provider 和模型
hotaru agents              # 列出 agent
hotaru sessions -n 20      # 列出最近会话
hotaru config --show       # 展示合并后的配置
hotaru config --path       # 展示配置目录
```

### `run` 子命令常用参数

```bash
hotaru run "修复 tests 失败" --model openai/gpt-4o-mini --agent build
hotaru run "总结这段日志" --json
hotaru run "重构这个函数" --yes
```

- `--model/-m`：指定 `provider/model`
- `--agent/-a`：指定 agent
- `--session/-s` / `--continue/-c`：继续会话
- `--file/-f`：附加文件
- `--json`：输出 JSON 事件流
- `--yes/-y`：自动通过权限请求

## 配置说明

Hotaru 会合并多来源配置（后者覆盖前者）：

1. 全局配置目录（`hotaru config --path` 可查看）
2. 项目目录向上查找的 `hotaru.json` / `hotaru.jsonc`
3. `.hotaru/hotaru.json` / `.hotaru/hotaru.jsonc`
4. 环境变量 `HOTARU_CONFIG_CONTENT`
5. 托管配置目录（最高优先级）

### 最小 `hotaru.json` 示例

```json
{
  "model": "openai/gpt-4o-mini",
  "default_agent": "build",
  "provider": {
    "openai": {
      "options": {
        "apiKey": "{env:OPENAI_API_KEY}"
      }
    }
  },
  "permission": {
    "bash": "ask",
    "edit": "ask",
    "read": {
      "*.env": "ask",
      "*.env.example": "allow"
    }
  }
}
```

### 自定义 OpenAI-compatible Provider 示例

```json
{
  "provider": {
    "my-provider": {
      "type": "openai",
      "name": "My Provider",
      "options": {
        "baseURL": "https://api.example.com/v1",
        "apiKey": "{env:MY_PROVIDER_API_KEY}"
      },
      "models": {
        "my-model": {
          "name": "My Model"
        }
      }
    }
  }
}
```

### MCP 示例（本地服务）

```json
{
  "mcp": {
    "filesystem": {
      "type": "local",
      "command": [
        "npx",
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "."
      ],
      "enabled": true,
      "timeout": 30
    }
  }
}
```

## 项目结构

- `src/hotaru/cli/`：CLI 入口与命令实现
- `src/hotaru/tui/`：Textual TUI
- `src/hotaru/session/`：消息、会话、处理循环
- `src/hotaru/tool/`：内置工具与注册中心
- `src/hotaru/provider/`：Provider/模型抽象
- `src/hotaru/mcp/`：MCP 客户端与认证
- `src/hotaru/permission/`：权限规则与交互
- `src/hotaru/skill/`：Skill 发现与加载

## 开发

```bash
# 运行测试
uv run pytest tests

# 构建包
uv build
```

## 说明

- Python 版本要求：`>=3.12`
- 包名：`hotaru-code`
- 命令行入口：`hotaru`


