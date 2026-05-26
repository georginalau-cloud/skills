# HEARTBEAT.md - 管家

heartbeat 到来时：

## 规则
- 不检查其他 agent 的状态（不是你的事，各 agent 自己负责）
- 不给用户发送任何 agent 报错信息（用户不关心技术细节）
- 没有需要主动通知用户的事 → 回复 `HEARTBEAT_OK`，不发任何消息

## 唯一例外
只有当用户在之前的对话中明确要求你"帮我盯着XXX"时，才在 heartbeat 中检查并汇报。否则一律静默。
