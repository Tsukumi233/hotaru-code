# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
