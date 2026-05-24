# 招财 Agent

## 启动指令
每次会话开始（包括 heartbeat 和 cron 触发），先读取 workspace 中的 `AGENTS.md`，按其中的启动顺序加载上下文（SOUL.md → USER.md → MEMORY.md）。不问许可，直接读。

## 共享资源
- 共享记忆：~/.openclaw/workspace-shared/memory/
- 共享技能：~/.openclaw/workspace-shared/skills/
- 权限：可读 + 可写 user-profiles.md, common-knowledge.md
- 不可写：team-rules.md（联系管家）

## 写入规范
- 写入前检查锁
- 财运相关偏好写入 user-profiles.md
