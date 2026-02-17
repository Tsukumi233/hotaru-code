# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
