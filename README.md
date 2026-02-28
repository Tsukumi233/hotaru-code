# Hotaru Code

AI-powered coding agent with TUI, WebUI, and one-shot CLI interfaces. Supports multi-provider LLM integration, 20+ built-in tools, MCP protocol extensions, configurable permission system, and multi-agent orchestration.

---

## Architecture Diagrams

### 1. System Architecture Overview

Full-stack layered architecture from user interfaces down to storage.

```mermaid
flowchart TB
    User["User"]

    subgraph Entry["Interface Layer"]
        CLI["Typer CLI<br/><code>cli/main.py</code>"]
        TUI["Textual TUI<br/><code>tui/app.py</code>"]
        WebUI["React WebUI<br/><code>frontend/</code>"]
    end

    subgraph Transport["Transport Layer"]
        SDKCtx["SDKContext<br/>(TUI → HTTP Client)"]
        Server["FastAPI Server<br/>SSE + WebSocket<br/><code>server/app.py</code>"]
        AppSvc["App Services<br/><code>app_services/*</code>"]
    end

    subgraph Session["Session Orchestration"]
        Orch["PromptOrchestration<br/>(model/agent/session resolve)"]
        SysPr["SystemPrompt<br/>+ InstructionPrompt"]
        SP["SessionPrompt<br/>(multi-turn loop)"]
        Proc["SessionProcessor<br/>(single-step execution)"]
        TR["TurnRunner<br/>(stream consumption)"]
        TE["ToolExecutor<br/>(dispatch + permission)"]
        Compact["Compaction<br/>(context overflow pruning)"]
    end

    subgraph LLMLayer["LLM Adapter"]
        LLM["LLM<br/>(unified streaming)"]
        Xform["ProviderTransform<br/>(message normalization)"]
        Retry["SessionRetry<br/>(exponential backoff)"]
        OAI["OpenAI SDK"]
        ANT["Anthropic SDK"]
    end

    subgraph Tools["Tool & Extension Layer"]
        ToolReg["ToolRegistry<br/>(20+ built-in tools)"]
        Perm["Permission Engine<br/>(allow / ask / deny)"]
        MCP["MCP Manager<br/>(stdio + HTTP/SSE)"]
        Skill["Skill Discovery"]
        TaskT["Task Tool<br/>(subagent delegation)"]
    end

    subgraph Core["Core Infrastructure"]
        Agent["Agent Registry<br/>(build/plan/general/explore)"]
        Provider["Provider Registry"]
        Config["ConfigManager<br/>(multi-source merge)"]
        Bus["Event Bus<br/>(ContextVar-scoped)"]
        Store["SQLite Storage<br/>(WAL mode)"]
    end

    User --> CLI & TUI & WebUI
    CLI -->|default| TUI
    CLI -->|run| Orch
    CLI -->|web| Server
    TUI --> SDKCtx --> Server
    WebUI -.->|HTTP/SSE/WS| Server
    Server --> AppSvc --> SP
    AppSvc --> Agent & Provider

    Orch --> SysPr --> SP
    SP --> Proc --> TR --> LLM
    TR --> TE --> ToolReg & MCP
    SP --> Compact
    ToolReg --> Perm
    TaskT --> SP

    LLM --> Xform --> OAI & ANT
    LLM --> Retry

    Agent & Provider & Skill & MCP --> Config
    Perm --> Bus
    SP -.-> Store
    Perm -.-> Store
```

### 2. Agentic Loop — Session Processing Sequence

The core ReAct loop: the LLM generates text/tool-calls, tools execute, results feed back until completion.

```mermaid
sequenceDiagram
    participant U as User / Interface
    participant SP as SessionPrompt
    participant P as SessionProcessor
    participant TR as TurnRunner
    participant LLM as LLM Adapter
    participant TE as ToolExecutor
    participant Perm as Permission
    participant API as Provider API

    U->>SP: prompt(user_message)
    SP->>SP: persist user message
    SP->>P: process(user_message, system_prompt)

    loop Agentic Loop (until stop or max_turns)
        P->>P: prepare turn (resolve agent, tools, ruleset)
        P->>TR: run(stream_input)
        TR->>LLM: stream(messages, tools, system)
        LLM->>API: HTTP streaming request

        loop Stream Chunks
            API-->>LLM: text / tool_call / reasoning delta
            LLM-->>TR: StreamChunk

            alt Text chunk
                TR-->>U: on_text(delta)
            else Tool call complete
                TR->>TE: execute_tool(name, input)
                TE->>Perm: check permission

                alt Allowed
                    Perm-->>TE: ok
                else Ask
                    Perm-->>U: permission.asked (via Bus)
                    U-->>Perm: reply (once / always / reject)
                end

                TE-->>TR: tool result
                TR-->>U: on_tool_end(output)
            else Reasoning chunk
                TR-->>U: on_reasoning_delta(text)
            end
        end

        TR-->>P: ProcessorResult

        alt Has tool calls → continue
            P->>P: append assistant + tool_result messages
        else No tool calls → stop
            P-->>SP: final result
        end
    end

    SP->>SP: check compaction overflow
    SP->>SP: generate title (async)
    SP->>SP: persist assistant message
    SP-->>U: complete response
```

### 3. Multi-Interface Architecture

Three interfaces sharing one backend through different transport paths.

```mermaid
flowchart LR
    subgraph Interfaces
        CLI["<b>CLI Run</b><br/>hotaru run 'prompt'<br/><i>One-shot, stdout</i>"]
        TUI["<b>TUI</b><br/>hotaru<br/><i>Textual, interactive</i>"]
        WebUI["<b>WebUI</b><br/>hotaru web<br/><i>React + Vite</i>"]
    end

    subgraph Transport
        Direct["Direct Invocation<br/>(in-process)"]
        HTTP["FastAPI HTTP<br/>/v1/sessions/*<br/>/v1/providers/*<br/>/v1/agents/*"]
        SSE["SSE Stream<br/>/v1/events"]
        WS["WebSocket<br/>/v1/ptys/{id}"]
    end

    subgraph Backend["Shared Backend"]
        AppCtx["AppContext<br/>(service container)"]
        SessionLoop["Session Loop"]
        ToolExec["Tool Execution"]
        Storage["SQLite Storage"]
    end

    CLI --> Direct --> AppCtx
    TUI -->|SDKContext<br/>→ HotaruAPIClient| HTTP & SSE
    WebUI --> HTTP & SSE & WS

    HTTP --> AppCtx
    SSE --> AppCtx
    WS --> AppCtx

    AppCtx --> SessionLoop --> ToolExec --> Storage
```

### 4. Tool Execution Pipeline

From LLM tool_call to execution result, including permission check and doom loop detection.

```mermaid
flowchart TB
    TC["LLM emits tool_call<br/>(name, input, id)"]

    TC --> Allowed{"Tool in<br/>allowed_tools?"}
    Allowed -->|No| Err1["Error: Unknown tool"]
    Allowed -->|Yes| Resolve{"Built-in tool?"}

    Resolve -->|Yes| DoomCheck["DoomLoopDetector<br/>check recent N signatures"]
    Resolve -->|No| MCPCheck{"MCP tool?"}

    MCPCheck -->|Yes| MCPExec["MCP Client<br/>call_tool(name, args)"]
    MCPCheck -->|No| Err2["Error: Unknown tool"]

    DoomCheck --> DoomResult{"Repeated<br/>≥ threshold?"}
    DoomResult -->|Yes| AskDoom["Permission.ask<br/>(doom_loop)"]
    DoomResult -->|No| PermCheck
    AskDoom -->|Approved| PermCheck
    AskDoom -->|Rejected| Blocked["Error: blocked"]

    PermCheck["PermissionGuard.check<br/>(tool permissions)"]
    PermCheck --> Evaluate{"Evaluate ruleset"}

    Evaluate -->|allow| Execute
    Evaluate -->|deny| DeniedErr["DeniedError"]
    Evaluate -->|ask| HumanLoop["Publish PermissionAsked<br/>await Future"]

    HumanLoop -->|once / always| Execute
    HumanLoop -->|reject| RejectedErr["RejectedError"]

    Execute["tool.execute(parsed_input, ctx)<br/>→ ToolResult"]
    MCPExec --> Result
    Execute --> Result["Return {output, title, metadata}"]

    style TC fill:#e1f5fe
    style Execute fill:#e8f5e9
    style Result fill:#e8f5e9
    style Err1 fill:#ffebee
    style Err2 fill:#ffebee
    style DeniedErr fill:#ffebee
    style RejectedErr fill:#ffebee
    style Blocked fill:#ffebee
```

### 5. Permission System — Human-in-the-Loop Flow

Multi-scope permission memory with configurable persistence.

```mermaid
flowchart TB
    ToolCall["Tool attempts action<br/>(e.g. bash, edit)"]

    ToolCall --> BuildPatterns["Build permission patterns<br/>(tool type + file path / command)"]
    BuildPatterns --> MergeRules["Merge rulesets:<br/>1. Agent default rules<br/>2. User config rules<br/>3. Approved memory rules"]

    MergeRules --> EvalLoop["For each pattern:<br/>evaluate(permission, pattern, merged)"]

    EvalLoop --> Match{"Last matching rule?"}

    Match -->|allow| Pass["Proceed"]
    Match -->|deny| Deny["Raise DeniedError"]
    Match -->|ask / no match| AskUser

    AskUser["Create PermissionRequest<br/>Bus.publish(PermissionAsked)<br/>await asyncio.Future"]

    AskUser --> UI["UI shows permission dialog"]

    UI --> Reply{"User reply?"}

    Reply -->|once| Resolve["Resolve Future → proceed"]
    Reply -->|always| Remember["Remember approval →<br/>resolve this + auto-resolve<br/>other matching pending"]
    Reply -->|reject| Reject["Reject Future →<br/>also reject ALL pending<br/>for this session"]

    Remember --> Scope{"Memory scope?"}
    Scope -->|turn| Volatile["Discarded after this request"]
    Scope -->|session| InMem["In-memory per session"]
    Scope -->|project| ProjMem["In-memory per project"]
    Scope -->|persisted| Disk["SQLite persistent storage"]

    style Pass fill:#e8f5e9
    style Deny fill:#ffebee
    style Reject fill:#ffebee
```

### 6. Provider Transform Pipeline

How messages are normalized across different LLM providers before API calls.

```mermaid
flowchart LR
    subgraph Input["Raw Messages"]
        Msgs["OpenAI-format messages<br/>(role, content, tool_calls)"]
    end

    subgraph Transform["ProviderTransform Pipeline"]
        direction TB
        T1["1. Normalize tool_call_id<br/>(Mistral: alphanum 9 chars<br/>Claude: no special chars)"]
        T2["2. Apply interleaved reasoning<br/>(Moonshot reasoning_content<br/>Anthropic thinking blocks)"]
        T3["3. Remap provider_options<br/>(sdk_key resolution)"]
        T4["4. Inject cache controls<br/>(Anthropic: cacheControl<br/>OpenAI: cache_control<br/>Bedrock: cachePoint)"]
        T5["5. Strip empty content<br/>(Anthropic rejects empty)"]
        T1 --> T2 --> T3 --> T4 --> T5
    end

    subgraph Output["Provider-Specific"]
        OAI["OpenAI SDK<br/>system as first message<br/>function tool_calls"]
        ANT["Anthropic SDK<br/>system as separate param<br/>tool_use / tool_result blocks"]
    end

    Input --> Transform
    T5 -->|api_type=openai| OAI
    T5 -->|api_type=anthropic| ANT
```

### 7. MCP Integration Architecture

Model Context Protocol client supporting local (stdio) and remote (HTTP/SSE) servers with OAuth.

```mermaid
flowchart TB
    subgraph Config["hotaru.json"]
        LocalCfg["type: local<br/>command: [npx, ..., server]"]
        RemoteCfg["type: remote<br/>url: https://..."]
    end

    subgraph MCPManager["MCP Manager"]
        Init["init() — read config<br/>create clients sequentially"]
        State["MCPState<br/>clients + status per server"]
    end

    subgraph LocalTransport["Local Transport"]
        Stdio["stdio_client<br/>(stdin/stdout pipes)"]
        LocalProc["Child process<br/>(MCP server)"]
    end

    subgraph RemoteTransport["Remote Transport"]
        HTTP["streamable_http_client<br/>(try first)"]
        SSEFallback["sse_client<br/>(fallback)"]
        OAuth["OAuth flow<br/>(if 401/403)"]
    end

    subgraph Protocol["MCP Protocol"]
        Session["ClientSession<br/>initialize()"]
        ListTools["list_tools()"]
        CallTool["call_tool(name, args)"]
        ListPrompts["list_prompts()"]
        ReadResource["read_resource(uri)"]
    end

    subgraph Integration["Hotaru Integration"]
        ToolResolver["ToolResolver<br/>prefix: {client}_{tool}"]
        ToolExec["ToolExecutor<br/>route to MCP client"]
        ToolDefs["Tool definitions<br/>injected into LLM context"]
    end

    Config --> Init --> State
    LocalCfg --> Stdio --> LocalProc
    RemoteCfg --> HTTP
    HTTP -->|fail| SSEFallback
    HTTP -->|401/403| OAuth

    Stdio & HTTP & SSEFallback --> Session
    Session --> ListTools & CallTool & ListPrompts & ReadResource

    ListTools --> ToolResolver --> ToolDefs
    CallTool --> ToolExec
```

### 8. AppContext Lifecycle — Startup Sequence

Phased startup with health tracking and rollback on critical failures.

```mermaid
sequenceDiagram
    participant Entry as CLI / TUI / Web
    participant Ctx as AppContext
    participant Bus as Event Bus
    participant Cfg as ConfigManager
    participant DB as SQLite Storage
    participant Tools as ToolRegistry
    participant MCP as MCP Manager
    participant LSP as LSP Manager
    participant Skills as Skill Discovery
    participant Agents as Agent Registry

    Entry->>Ctx: AppContext()
    Note over Ctx: Constructs all subsystems:<br/>Bus, Config, Permission, Question,<br/>Skills, Agents, Tools, MCP, LSP, Runner

    Entry->>Ctx: startup()

    rect rgb(230, 245, 255)
        Note over Ctx: Phase A — Bind context vars
        Ctx->>Bus: Bus.provide(bus)
        Ctx->>Cfg: ConfigManager.provide(config)
    end

    rect rgb(230, 255, 230)
        Note over Ctx: Phase B — Config + Storage
        Ctx->>Cfg: load() (merge all config sources)
        Ctx->>DB: initialize() (WAL mode, migrations)
    end

    rect rgb(255, 245, 230)
        Note over Ctx: Phase C — Tools (sync, fast)
        Ctx->>Tools: init() (register 20+ built-in tools)
    end

    rect rgb(255, 230, 230)
        Note over Ctx: Phase D — MCP + LSP (parallel, health-tracked)
        par
            Ctx->>MCP: init() [critical=true]
            MCP-->>Ctx: ready / failed
        and
            Ctx->>LSP: init() [critical=false]
            LSP-->>Ctx: ready / failed
        end

        alt Critical failure
            Ctx->>Ctx: rollback_startup()
            Ctx-->>Entry: RuntimeError
        else Degraded (LSP failed)
            Note over Ctx: status = "degraded"
        else All ready
            Note over Ctx: status = "ready"
        end
    end

    rect rgb(240, 230, 255)
        Note over Ctx: Phase E — Skills + Agents (parallel)
        par
            Ctx->>Skills: init()
        and
            Ctx->>Agents: init()
        end
    end

    Ctx-->>Entry: started = true
```

### 9. Subagent Delegation (Task Tool)

The Task tool spawns isolated child sessions with scoped agents and tool sets.

```mermaid
flowchart TB
    subgraph Parent["Parent Session (build agent)"]
        LLM1["LLM decides to delegate"]
        TaskCall["Task Tool call:<br/>subagent_type=explore<br/>prompt='find all API routes'"]
    end

    subgraph Resolution["Task Resolution"]
        AgentLookup["Agent Registry lookup<br/>(explore → subagent mode)"]
        ModelResolve["Resolve model<br/>(agent override or inherit parent)"]
        ChildSession["Create child Session<br/>(new session_id, same project)"]
    end

    subgraph Child["Child Session (explore agent)"]
        ChildProc["SessionProcessor<br/>(scoped tools, own ruleset)"]
        ChildLLM["LLM streaming"]
        ChildTools["Restricted tool set:<br/>grep, glob, list, read, bash"]
        ChildLoop["Agentic loop<br/>(independent turns)"]
    end

    subgraph Return["Result Aggregation"]
        ChildResult["Child final text output"]
        ParentResume["Injected as tool_result<br/>into parent messages"]
    end

    LLM1 --> TaskCall
    TaskCall --> AgentLookup --> ModelResolve --> ChildSession
    ChildSession --> ChildProc --> ChildLLM --> ChildTools
    ChildTools --> ChildLoop --> ChildResult
    ChildResult --> ParentResume

    style Parent fill:#e3f2fd
    style Child fill:#fff3e0
    style Return fill:#e8f5e9
```

### 10. Storage Architecture

SQLite with WAL mode, namespace-routed tables, and automatic JSON migration.

```mermaid
flowchart TB
    subgraph Callers
        Session["Session"]
        MsgStore["MessageStore"]
        Permission["Permission"]
        Project["Project"]
    end

    subgraph StorageAPI["Storage API"]
        Read["read(key)"]
        Write["write(key, data)"]
        Update["update(key, fn)<br/>(BEGIN IMMEDIATE)"]
        Tx["transaction(ops[])"]
        List["list(prefix)"]
    end

    subgraph KeyRouting["Namespace Routing"]
        Router{"key[0] →<br/>table mapping"}
        T1["sessions"]
        T2["session_index"]
        T3["messages"]
        T4["parts"]
        T5["permission_approval"]
        T6["kv (fallback)"]
    end

    subgraph SQLite["SQLite (WAL mode)"]
        DB["storage.db<br/>PRAGMA journal_mode=WAL<br/>PRAGMA synchronous=NORMAL<br/>PRAGMA busy_timeout=5000"]
        Migration["JSON → SQLite<br/>auto-migration on first run"]
    end

    Session & MsgStore & Permission & Project --> StorageAPI
    StorageAPI --> Router
    Router --> T1 & T2 & T3 & T4 & T5 & T6
    T1 & T2 & T3 & T4 & T5 & T6 --> DB
    DB --- Migration
```

### 11. Configuration Merge Strategy

Multi-source configuration with layered priority resolution.

```mermaid
flowchart LR
    subgraph Sources["Config Sources (low → high priority)"]
        direction TB
        S1["1. Global config dir<br/><code>~/.config/hotaru/</code>"]
        S2["2. Project <code>hotaru.json</code><br/>(walk up from cwd)"]
        S3["3. <code>.hotaru/hotaru.json</code><br/>(walk up from cwd)"]
        S4["4. Env var<br/><code>HOTARU_CONFIG_CONTENT</code>"]
        S5["5. Managed config dir<br/>(highest priority)"]
    end

    subgraph Merge["ConfigManager.load()"]
        Deep["Deep merge<br/>(later overrides earlier)"]
        Env["Resolve <code>{env:VAR}</code><br/>placeholders in values"]
        Validate["Pydantic validation<br/>→ AppConfig"]
    end

    subgraph Consumers["Consumers"]
        Agents["Agent definitions<br/>+ permissions"]
        Providers["Provider registry<br/>+ API keys"]
        Tools["Tool enablement<br/>(experimental flags)"]
        Perms["Permission rules"]
        MCPCfg["MCP server configs"]
    end

    S1 --> Deep
    S2 --> Deep
    S3 --> Deep
    S4 --> Deep
    S5 --> Deep
    Deep --> Env --> Validate
    Validate --> Agents & Providers & Tools & Perms & MCPCfg
```

### 12. WebUI Frontend Architecture

React SPA communicating with FastAPI backend via REST + SSE.

```mermaid
flowchart TB
    subgraph Frontend["React Frontend (Vite)"]
        App["App.tsx"]

        subgraph Hooks["Custom Hooks"]
            useSession["useSession<br/>(session CRUD)"]
            useMessages["useMessages<br/>(message list + apply)"]
            useEvents["useEvents<br/>(SSE subscription)"]
            useProviders["useProviders<br/>(model/agent select)"]
            usePermissions["usePermissions<br/>(HITL dialogs)"]
            usePty["usePty<br/>(terminal mgmt)"]
        end

        subgraph Components["UI Components"]
            Layout["Layout"]
            Header["Header<br/>(model/agent/theme)"]
            Sidebar["Sidebar<br/>(session list)"]
            ChatView["ChatView<br/>(messages + composer)"]
            PermCard["PermissionCard"]
            QuestCard["QuestionCard"]
            Terminal["TerminalPanel<br/>(xterm.js via WS)"]
        end
    end

    subgraph API["api.ts"]
        SessAPI["sessions.*<br/>list/create/send/interrupt"]
        ProvAPI["providers.*<br/>list/models"]
        PermAPI["permissions.*<br/>list/reply"]
        QuestAPI["questions.*<br/>list/reply/reject"]
        PtyAPI["pty.*<br/>create/close/resize"]
    end

    subgraph Backend["FastAPI Backend (:4096)"]
        REST["REST Endpoints<br/>/v1/sessions<br/>/v1/providers<br/>/v1/agents"]
        SSE["SSE Stream<br/>/v1/events"]
        WS["WebSocket<br/>/v1/ptys/{id}"]
    end

    App --> Hooks --> API
    App --> Components
    useEvents -.->|EventSource| SSE
    SessAPI & ProvAPI & PermAPI & QuestAPI --> REST
    PtyAPI --> REST
    Terminal -.-> WS
    SSE -.->|real-time events| useEvents
```

### 13. Event Bus System

ContextVar-scoped pub/sub with typed Pydantic event schemas.

```mermaid
flowchart TB
    subgraph Publishers
        PermPub["Permission<br/>PermissionAsked<br/>PermissionReplied"]
        MCPPub["MCP<br/>ToolsChanged<br/>BrowserOpenFailed"]
        SessionPub["Session<br/>MessageCreated<br/>PartUpdated"]
        PtyPub["PTY<br/>PtyOutput<br/>PtyExit"]
    end

    subgraph Bus["Event Bus (ContextVar-scoped)"]
        Registry["Event Registry<br/>BusEvent.define(type, schema)"]
        PubSub["Bus.publish(event, props)<br/>Bus.subscribe(event, callback)"]
        Wildcard["Wildcard subscriber<br/>Bus.subscribe_all(callback)"]
    end

    subgraph Subscribers
        SSEBridge["EventService<br/>→ SSE stream"]
        TUIBridge["TUI event handler<br/>→ widget updates"]
        AutoResolve["Permission auto-resolve<br/>(on 'always' reply)"]
    end

    Publishers --> PubSub
    PubSub --> Subscribers
    Registry --> PubSub
    Wildcard --> SSEBridge

    style Bus fill:#fff8e1
```

---

## Feature Overview

Hotaru Code is an AI coding assistant.

It provides TUI, WebUI, and one-shot Run mode with tool calling, permission control, session persistence, MCP extensions, LSP support, and Skill/Agent configuration.

### Multi-Interface Modes

- `hotaru` — default TUI (Textual)
- `hotaru web` — WebUI (HTTP + SSE)
- `hotaru run "your prompt"` — one-shot execution
- Built-in `/init` command for generating/updating `AGENTS.md`

### Agent + Permission System

- Built-in agents: `build`, `plan`, `general`, `explore` (+ hidden internal agents)
- Custom Markdown agents from `.hotaru/agents/` directories
- Permission rules: `allow / ask / deny` with glob patterns
- Fine-grained control over `bash`, `edit`, external directory access
- Doom loop detection for repeated tool calls

### Built-in Tools

| Category | Tools |
|----------|-------|
| File & Code | `list`, `glob`, `grep`, `read`, `edit`, `write`, `multiedit`, `apply_patch` |
| Execution | `bash`, `task`, `todoread`, `todowrite`, `question` |
| Web | `webfetch` |
| Extensions | `skill`, `lsp` (experimental) |
| Experimental | `websearch`, `codesearch`, `batch`, `plan_enter`, `plan_exit` |

### Provider / MCP / Skill Extensions

- **Provider**: OpenAI, Anthropic, and OpenAI-compatible custom services
- **MCP**: Local (stdio) and remote (HTTP/SSE) with OAuth support
- **Skill**: Local directory discovery + remote skill index
- **Persistence**: Sessions/messages stored in SQLite, recoverable across restarts

---

## Installation

### From source (development)

```bash
uv sync
uv run hotaru --help
uv run hotaru
```

### As CLI tool (published)

```bash
uv tool install hotaru-code
uv tool update-shell
hotaru --help
```

Or one-off:

```bash
uvx --from hotaru-code hotaru --help
```

### Configure API Key

At least one provider key is required (or use `/connect` for custom API):

```bash
# macOS/Linux
export OPENAI_API_KEY="your-key"
# or
export ANTHROPIC_API_KEY="your-key"
```

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY = "your-key"
# or
$env:ANTHROPIC_API_KEY = "your-key"
```

---

## Usage

### TUI Mode

```bash
hotaru                                          # default TUI
hotaru --model openai/gpt-5 --agent build       # specify model/agent
hotaru --directory ../another-repo --prompt "read project structure"
hotaru tui --continue                            # resume last session
```

### Run Mode (one-shot)

```bash
hotaru run "analyze this repo"
hotaru run "fix tests" --model openai/gpt-5 --agent build --yes
hotaru run "generate release notes" -f CHANGELOG.md -f docs/release.md
hotaru run "summarize this log" --json           # JSON event stream output
cat error.log | hotaru run "summarize and fix"   # stdin input
```

### WebUI Mode

```bash
hotaru web                                       # default 127.0.0.1:4096
hotaru web --host 0.0.0.0 --port 8080 --open    # custom host/port + open browser
```

Frontend development:

```bash
cd frontend && npm ci && npm run build           # output → src/hotaru/webui/dist
```

### Session & Config Management

```bash
hotaru providers            # list available providers/models
hotaru agents               # list visible agents
hotaru sessions -n 20       # list recent sessions
hotaru config --show        # display merged config
hotaru config --path        # show config directory
hotaru agent create --description "Code reviewer" --mode primary
```

---

## Configuration

Hotaru merges configs from multiple sources (later overrides earlier):

1. Global config dir (`hotaru config --path`)
2. `hotaru.json` / `hotaru.jsonc` (walk up from cwd)
3. `.hotaru/hotaru.json` / `.hotaru/hotaru.jsonc` (walk up from cwd, including `~/.hotaru`)
4. Environment variable `HOTARU_CONFIG_CONTENT`
5. Managed config directory (highest priority)

### Minimal `hotaru.json`

```json
{
  "model": "openai/gpt-5",
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
      "*.env.*": "ask",
      "*.env.example": "allow"
    }
  },
  "permission_memory_scope": "session",
  "continue_loop_on_deny": false
}
```

### Permission Memory Scope

- `turn` — discarded after current request
- `session` — in-memory per session (default)
- `project` — in-memory per project (cleared on restart)
- `persisted` — same as project but persisted to SQLite

### Custom Provider

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
        "my-model": { "name": "My Model" }
      }
    }
  }
}
```

### MCP Server

```json
{
  "mcp": {
    "filesystem": {
      "type": "local",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."],
      "enabled": true,
      "timeout": 30
    }
  }
}
```

### Markdown Agent (`.hotaru/agents/reviewer.md`)

```markdown
---
description: Use this agent when you need strict code review.
mode: primary
model: openai/gpt-5
tools:
  bash: false
  edit: false
---
You are a reviewer agent. Focus on correctness, regression risk, and test gaps.
```

### Experimental Features

```json
{
  "experimental": {
    "plan_mode": true,
    "enable_exa": false,
    "lsp_tool": false,
    "batch_tool": false
  }
}
```

---

## Project Structure

```
src/hotaru/
├── cli/           CLI entry point and subcommands (Typer)
├── tui/           Terminal UI (Textual) — screens, widgets, dialogs
├── server/        FastAPI HTTP server — routes, SSE, WebSocket
├── session/       Session loop, processor, LLM adapter, compaction
├── tool/          20+ built-in tools and ToolRegistry
├── provider/      Provider registry, transform layer, SDK wrappers
├── agent/         Agent registry and Markdown agent loading
├── permission/    Permission engine (allow/ask/deny rules)
├── mcp/           MCP client (stdio and HTTP/SSE) + OAuth
├── skill/         Skill discovery and loading
├── lsp/           LSP client and server management
├── core/          Config, event bus, global paths, context
├── storage/       SQLite storage with WAL mode
├── project/       Project/instance management
├── runtime/       AppContext lifecycle container
├── app_services/  Service layer for HTTP routes
├── api_client/    HTTP client for TUI → Server communication
├── pty/           PTY session management for WebSocket terminal
├── shell/         Shell execution utilities
├── patch/         Patch application
├── command/       Slash command system
├── snapshot/      Snapshot tracking
├── question/      Question/answer HITL system
└── webui/dist/    Built React frontend assets
frontend/          React + TypeScript WebUI source
tests/             Mirrors src/hotaru/ structure
```

## Development

```bash
uv run pytest tests     # run tests
uv build                # build package
```

## Technical Details

- Python `>=3.12`, package name `hotaru-code`, entry point `hotaru`
- Backend: FastAPI + Uvicorn, SQLite (WAL), asyncio
- Frontend: React + TypeScript + Vite, xterm.js for terminal
- LLM SDKs: `anthropic`, `openai` (OpenAI-compatible)
- MCP: `mcp` SDK (ClientSession, stdio/HTTP/SSE transports)
- TUI: Textual framework
