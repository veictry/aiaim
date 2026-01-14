# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2025-01-14

### Added
- **CLI 子命令支持**: 新增 `create-chat` 子命令，创建新会话并绑定到当前 shell
- **Chat ID 绑定**: 新增 `--chat-id` 选项，支持绑定 Agent Chat ID 到会话
- **Session 选项**: 新增 `--session/-s` 选项，显式指定或切换会话
- **Session 锁定**: 支持 shell 锁定到特定 session，后续命令自动使用

### Changed
- 重构 CLI 架构，使用 `click.Group` 支持子命令
- 改进 Shell Session 识别逻辑，使用 TTY、终端 Session ID 等更稳定的方式
- 简化 session ID 和 chat ID 的显示（不再截断）
- 移除未使用的 imports

### Fixed
- 修复跨命令 shell session 识别不稳定的问题

## [0.2.1] - 2025-01-14

### Fixed
- 版本号更新

## [0.2.0] - 2025-01-14

### Added
- **Continue Mode**: 新增 `--continue` 参数，支持从上次停止的地方继续执行
  - `agend --continue` - 继续上一个会话（默认 10 轮迭代）
  - `agend --continue 5` - 继续并指定迭代轮数
  - `agend --continue --resume <session_id>` - 继续特定会话
- **Session List**: 新增 `--list` 参数，查看最近的会话列表
- **File Input**: 新增 `--file` 参数，从文件读取任务内容
- Shell session 锁定功能，支持在同一 shell 中追踪会话

### Changed
- 项目重命名：从 `aiaim` 更名为 `agend`
- 简化 CLI 接口，合并为单一命令入口
- 优化会话管理，使用 SQLite 存储会话索引

### Fixed
- 改进 JSON 解析的健壮性
- 修复迭代结果持久化问题

## [0.1.2] - 2025-01-13

### Added
- 迭代结果持久化到 JSON 文件
- 更健壮的 JSON 解析逻辑

### Fixed
- 修复 Supervisor 输出解析失败的问题

## [0.1.1] - 2025-01-12

### Added
- Chat session 恢复功能：Worker Agent 可以使用 `--resume` 恢复之前的对话
- Todo 持久化：Supervisor 检查结果会保存到文件
- 会话管理系统：使用 SQLite 追踪会话状态

### Changed
- Worker 和 Supervisor 使用独立的 Agent CLI 实例
- Supervisor 不再共享 Worker 的 chat session

## [0.1.0] - 2025-01-11

### Added
- 初始版本发布
- Supervisor/Worker 模式的基础实现
- 支持 `cursor-cli` 作为 Agent 后端
- 实时输出流式显示
- 可配置的迭代次数和延迟
- Rich 终端美化输出
- Python API 和 CLI 双重接口
