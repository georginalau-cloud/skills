# ⛔ HEARTBEAT 已永久禁用

**肌肉的 heartbeat 功能已于 2026-05-18 永久禁用。**

所有定时任务由 cron/jobs.json 管理，不再使用 heartbeat session。

---

## 禁止事项

- 禁止生成"检查清单状态"类消息
- 禁止生成带有"✅ ❌ 🧹 📊"等 emoji 的状态列表
- 禁止在 heartbeat 中生成或发送任何数据完整性报告
- 如发现此类消息正在发出，立即停止并静默

---

## 如果你是被 heartbeat session 唤醒的

直接回复 `HEARTBEAT_OK`，不做任何其他操作，不发任何消息。
