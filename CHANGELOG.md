# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0](https://github.com/Tsukumi233/hotaru-code/compare/v1.1.0...v1.2.0) (2026-02-28)


### Features

* **mcp:** implement oauth e2e flow across core/cli/server/tui ([83a1ece](https://github.com/Tsukumi233/hotaru-code/commit/83a1ece78b70a595fd93e8a514c040fb76f2d99e))
* 添加示例 agent 配置文件 ([d1d9e31](https://github.com/Tsukumi233/hotaru-code/commit/d1d9e312f9c56ba9ec493ff2f9862c8ac11cbc1f))


### Bug Fixes

* comment out unused 'once' method in Bus class ([5061823](https://github.com/Tsukumi233/hotaru-code/commit/5061823596859c5def4ce53e909e219e56cb338a))
* update architecture diagram ([700d7a8](https://github.com/Tsukumi233/hotaru-code/commit/700d7a8a9b971943372d24f808efa47f8a3e7726))
* update README.md ([6c7f89f](https://github.com/Tsukumi233/hotaru-code/commit/6c7f89fd5786895d39eb527a9e0a9fc154c90ae9))

## [1.1.0](https://github.com/Tsukumi233/hotaru-code/compare/v1.0.0...v1.1.0) (2026-02-25)


### Features

* Add reasoning_text handling in ProviderTransform and update related processing logic ([e57650b](https://github.com/Tsukumi233/hotaru-code/commit/e57650b1155a58561799c43609c4c596d9efbcd3))
* **cli:** extend web command with logging options for level, format, and access log ([2b8b6fa](https://github.com/Tsukumi233/hotaru-code/commit/2b8b6fab1ad894715edd029d19936ce11b710228))
* **diagnostics:** refactor diagnostics handling and add debounce logic ([272254b](https://github.com/Tsukumi233/hotaru-code/commit/272254bfcbdc2b2e781a574bb24c4586b021c051))
* Enhance model state management with persistence option ([a9f53dc](https://github.com/Tsukumi233/hotaru-code/commit/a9f53dcb583dbc0fcab81c1240b40116498dd8d8))
* Enhance provider and session handling with strict schema validation ([7cb7717](https://github.com/Tsukumi233/hotaru-code/commit/7cb7717f29c4965e147db4ecab18e320881fb3b7))
* Enhance schema normalization by removing titles and flattening nullable types ([aae28ed](https://github.com/Tsukumi233/hotaru-code/commit/aae28ed24d51ceaccb463c15e47d23c55304a521))
* Introduce ToolResolver for effective tool resolution and refactor session processing ([f046434](https://github.com/Tsukumi233/hotaru-code/commit/f046434ef20fbf8e662176dff1e7ff158021c81b))
* **logging:** implement runtime logging configuration and bootstrap logic ([2b8b6fa](https://github.com/Tsukumi233/hotaru-code/commit/2b8b6fab1ad894715edd029d19936ce11b710228))
* **openai:** add text sanitization and error handling in streaming process ([4a8fece](https://github.com/Tsukumi233/hotaru-code/commit/4a8fece7b0ac9552a68dc7c04dfbdd937ef59ca4))
* **provider:** add fallback logic for interleaved field in message transformation and enhance related tests ([a3fbd1b](https://github.com/Tsukumi233/hotaru-code/commit/a3fbd1bb7251130e0dab1d393c648df3bdaa5e83))
* **provider:** add provider configuration application and related tests ([106aaf8](https://github.com/Tsukumi233/hotaru-code/commit/106aaf864a9d10ffe7abc505c5852b831da0f3fb))
* **provider:** refactor provider connection payload structure and update related tests ([c04bf10](https://github.com/Tsukumi233/hotaru-code/commit/c04bf105e4ca3a2b6b57edb0a786014b65e00e9a))
* **runtime:** implement instance context management and runtime binding helpers ([929a1c0](https://github.com/Tsukumi233/hotaru-code/commit/929a1c01c9f62dc07a61194a97dc8114fd092f79))
* **sanitization:** add text sanitization for control characters in OpenAI SDK and session processor ([3da06be](https://github.com/Tsukumi233/hotaru-code/commit/3da06be36153c40dc6401722ef5987455d98b128))
* **server:** add access logging middleware and enhance server startup logging ([2b8b6fa](https://github.com/Tsukumi233/hotaru-code/commit/2b8b6fab1ad894715edd029d19936ce11b710228))
* **session:** add session index management and related tests ([b0205e3](https://github.com/Tsukumi233/hotaru-code/commit/b0205e331299088321981ef5da5e67b277554832))
* update agent and config to remove legacy fields, refactor related tests ([57e74f4](https://github.com/Tsukumi233/hotaru-code/commit/57e74f4c1d4c98f9ceae592b201472e079cf480c))
* Update max_tokens to use ProviderTransform constant and enhance prompt verbosity examples ([23a8b10](https://github.com/Tsukumi233/hotaru-code/commit/23a8b10999e20a0b3aeedfafb7557d61bcbdadf3))


### Bug Fixes

* enhance timeout configuration for AsyncClient ([7c3870c](https://github.com/Tsukumi233/hotaru-code/commit/7c3870c183c9594f1170483977a1081b303fe9ab))
* **permission:** guard pending queue against concurrent replies ([7322c18](https://github.com/Tsukumi233/hotaru-code/commit/7322c185d471949b07642776ad53ec9e71971354))
* **server:** replace KeyError 404 mapping with explicit NotFoundError ([96d8804](https://github.com/Tsukumi233/hotaru-code/commit/96d8804756de328c4b7a87bf3348b7b56b45f611))
* **session:** re-raise unexpected turn errors ([77240c1](https://github.com/Tsukumi233/hotaru-code/commit/77240c1b0aa0a5abc28489777654a824f94b63dd))
* **tui:** move API server lifecycle management to CLI ([9cd526b](https://github.com/Tsukumi233/hotaru-code/commit/9cd526b76b1c53243957941b02e365825942a8cc))

## [1.0.0](https://github.com/Tsukumi233/hotaru-code/compare/v0.2.1...v1.0.0) (2026-02-22)


### ⚠ BREAKING CHANGES

* v1 request bodies no longer accept legacy camelCase alias fields (for example projectID/providerID/modelID/parentID/messageIDs and provider connect camelCase payload aliases).

### Features

* add auto-scroll functionality and theme management ([ab54edf](https://github.com/Tsukumi233/hotaru-code/commit/ab54edfe8faa74202004554afdcddf5adf7167ac))
* add Hotaru WebUI with React and Vite ([48ed9e9](https://github.com/Tsukumi233/hotaru-code/commit/48ed9e9aa3798895a4acfca8816f2f34109eae4e))
* add PTY session management with WebSocket support and API endpoints ([e96269f](https://github.com/Tsukumi233/hotaru-code/commit/e96269f66fd26a9888aefb48de3d1eac908fc62b))
* add QuestionCard, ResizeHandle, Sidebar, StatusBadge, ToolPart components ([ab54edf](https://github.com/Tsukumi233/hotaru-code/commit/ab54edfe8faa74202004554afdcddf5adf7167ac))
* **client:** add typed api client for v1 contract ([29a514a](https://github.com/Tsukumi233/hotaru-code/commit/29a514a4c99eae774a8cf9b91ecb78a1d29f504c))
* decouple server request context and event streams ([c1d9da0](https://github.com/Tsukumi233/hotaru-code/commit/c1d9da00f45a61dbfa35fb89763ce5e767585d56))
* enhance storage system with transaction support and cross-process consistency tests ([bb9d2ff](https://github.com/Tsukumi233/hotaru-code/commit/bb9d2ff6cc239c647f4f7a3ddb796a931980213a))
* implement hooks for session, messages, permissions, providers, and pty management ([ab54edf](https://github.com/Tsukumi233/hotaru-code/commit/ab54edfe8faa74202004554afdcddf5adf7167ac))
* implement session retry mechanism with exponential backoff for LLM streaming ([9e8ae45](https://github.com/Tsukumi233/hotaru-code/commit/9e8ae4546ee7393495cca0d08ca1a887a6be9399))
* implement shared prompt context and part callbacks for improved orchestration ([9d8013f](https://github.com/Tsukumi233/hotaru-code/commit/9d8013fdc6dad561ffe874a56b001ea8c9eee00e))
* **server:** add versioned api routes over app services ([81b1dae](https://github.com/Tsukumi233/hotaru-code/commit/81b1dae3638fe5bb60ac80b72644e632b89af06d))
* **tui:** enhance PromptInput with multi-line support and slash command handling ([bd3c559](https://github.com/Tsukumi233/hotaru-code/commit/bd3c559d762735536409e7670d6656beaa69c369))


### Bug Fixes

* **tui:** sync streaming behavior ([f436bd4](https://github.com/Tsukumi233/hotaru-code/commit/f436bd4028816dbb26bdb9f6d1360374c82ca63a))
* utility functions for message normalization and upserting ([ab54edf](https://github.com/Tsukumi233/hotaru-code/commit/ab54edfe8faa74202004554afdcddf5adf7167ac))


### Documentation

* **plan:** add loose-coupling design and execution plan ([99b7f27](https://github.com/Tsukumi233/hotaru-code/commit/99b7f278a13227d8e9dae8228f56aed2eead52c4))


### Code Refactoring

* remove legacy request aliases and unify slash parsing ([67a552d](https://github.com/Tsukumi233/hotaru-code/commit/67a552d68328593fe573a31a16b827a6b8cecd7f))

## [0.2.1](https://github.com/Tsukumi233/hotaru-code/compare/v0.2.0...v0.2.1) (2026-02-17)


### Bug Fixes

* test ci release ([14d5dfb](https://github.com/Tsukumi233/hotaru-code/commit/14d5dfb9229c72f2d26dc24e1e377d2d62e5004a))

## [0.2.0](https://github.com/Tsukumi233/hotaru-code/compare/0.1.0...v0.2.0) (2026-02-17)


### Features

* add /init command to initialize AGENTS.md ([2f6fb0c](https://github.com/Tsukumi233/hotaru-code/commit/2f6fb0c6d2d70708e14687ac8da42b8398016103))
* Add session summary utilities and TUI message adapters ([76ff0a1](https://github.com/Tsukumi233/hotaru-code/commit/76ff0a14ec923e1a30e7d782e0db062879271181))
* initial release ([42dace6](https://github.com/Tsukumi233/hotaru-code/commit/42dace61fcabb7c4c437518ebca19207d79b59b6))
* **provider:** centralize transform pipeline and add moonshot preset ([cd241f2](https://github.com/Tsukumi233/hotaru-code/commit/cd241f218063e1162fe502e979c62af43b16d8e7))
* **session:** add step-level snapshot/patch and reasoning stream persistence ([f1805b7](https://github.com/Tsukumi233/hotaru-code/commit/f1805b7240f7f4445f6e1bd40bd0575ba680d3e5))
* **tui:** rebuild runtime status flow and bump version to 0.2.1 ([5f0dabe](https://github.com/Tsukumi233/hotaru-code/commit/5f0dabef2d62dbe44e08df7b9979e49b90f60e6a))
* 添加指令加载功能，支持合并和去重配置中的指令数组 ([d40a587](https://github.com/Tsukumi233/hotaru-code/commit/d40a58705a1168a16a59696225aca57e5eee4540))


### Bug Fixes

* 弃用类属性 更新 GlobalPath 属性调用以使用方法形式 ([eea820f](https://github.com/Tsukumi233/hotaru-code/commit/eea820f7ec82a37848fe87b279fa52bf65a01493))

## [0.2.0] - 2026-02-15

### Changed
- **BREAKING CHANGES**: This release includes breaking changes that may affect existing configurations and integrations.

## [0.1.1] - 2026-02-14

### Added
- Added CHANGELOG.md to track version history

### Changed
- Updated package metadata for PyPI release

## [0.1.0] - 2026-02-13

### Added
- Initial release of Hotaru Code
- TUI mode with Textual interface
- Interactive Chat mode
- One-time Run mode
- Built-in agents: build, plan, general, explore
- Tool calling capabilities (file operations, bash, task, webfetch, etc.)
- Provider support for OpenAI, Anthropic, and OpenAI-compatible APIs
- MCP (Model Context Protocol) support
- Skill system for extensibility
- Session persistence
- Permission system with allow/ask/deny rules
- LSP (Language Server Protocol) integration (experimental)
- Configuration management with multiple sources
- Agent creation and management
- Markdown-based agent configurations

[0.2.0]: https://github.com/Tsukumi233/hotaru-code/compare/0.1.1...0.2.0
[0.1.1]: https://github.com/Tsukumi233/hotaru-code/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/Tsukumi233/hotaru-code/releases/tag/0.1.0
