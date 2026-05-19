# HEARTBEAT.md - 管家

heartbeat 到来时执行以下轻量检查（按优先级，有问题才推送）：

## 检查项

### 1. 其他 agent 是否有异常
检查以下目录是否有 error 文件或异常状态：
- `~/.openclaw/workspace-jirou/memory/pending/` — 是否有 Garmin-error.txt
- `~/.openclaw/workspace-zhaocai/memory/pending/` — 是否有异常文件

有异常 → 简短通知用户（飞书 open_id: ou_e62c3623b382df683370c131baf8f4c8，accountId: guanjia）

### 2. media 目录大小检查
如果 `~/.openclaw/media/` 总大小超过 500MB，提醒用户。

### 3. 无异常
回复 `HEARTBEAT_OK`，不发任何消息。

---

## 原则
- 没有问题：只回复 HEARTBEAT_OK
- 有问题：发一条简洁提醒，同一问题 4 小时内只提醒一次
- 绝不生成"检查清单状态"类消息
- 绝不操作其他 agent 的 workspace（只读检查）
