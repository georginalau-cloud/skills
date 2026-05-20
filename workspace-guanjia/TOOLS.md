# TOOLS.md - 工具配置

_我的工具小抄本，记录当前配置和所有能力。_

## 已安装的 Skills（skills/available，16个）

| 技能 | 功能 | 状态 |
|------|------|------|
| clawhub | 技能市场（安装/搜索 skill） | ✅ |
| coding-agent | 编码任务代理 | ✅ |
| flightclaw | 机票搜索引擎 | ✅ |
| github | GitHub 操作 | ✅ |
| gog | Google Workspace | ✅ |
| healthcheck | 安全审计 | ✅ |
| nano-pdf | PDF 编辑 | ✅ |
| notion | Notion 集成 | ✅ |
| openai-image-gen | 图片生成 | ✅ |
| openclaw-skills-eastmoney | 东方财富股票数据 | ✅ |
| session-logs | 会话日志分析 | ✅ |
| skill-creator | 技能创建 | ✅ |
| summarize | URL/音视频摘要 | ✅ |
| tmux | 会话自动化 | ✅ |
| video-frames | 视频帧提取 | ✅ |
| weather | 天气查询 | ✅ |

## Workspace Skills（workspace-guanjia/skills，7个）

| 技能 | 功能 |
|------|------|
| cangjie | 仓颉造字（写作风格蒸馏） |
| fliggy-flight-monitor | 飞猪机票监控 |
| minimax-image-understanding | 图片理解 |
| nox-grill-me | 压力测试计划/设计 |
| self-verify | 自检验证 |
| vau-writer | VAU 写作 |
| wukong | 名人思维蒸馏与召唤 |

## 已归档 Skills（deprecated，16个）

这些 skill 的 CLI 依赖未安装，或功能重复，已移至 `~/.openclaw/skills/deprecated/`：

blogwatcher, blucli, eightctl, garmin-connect-cli, garmin-connect-cn, goplaces, nano-banana-pro, openhue, ordercli, peekaboo, songsee, sonoscli, spotify-player, trello, voice-call, wacli

如需恢复，运行 `clawhub install <skill-name>`

## API 配置

- **阿里云**: AccessKey 已配置
- **QVeris**: API Key 已配置
- **飞书**: App ID/Secret 已配置

## 摄像头

（暂无配置）

## SSH

（暂无配置）

## 飞书排错要点（from openclaw-feishu-multi-bot）

**核心保命规则：**
- `agentToAgent.enabled` 必须 `false`（否则子 Agent 全挂）
- accountId 在 channels/bindings/agents 三处必须完全一致
- 绑定类型必须是 `"route"`
- 飞书应用必须发布，草稿状态静默丢消息

**诊断命令：**
```bash
openclaw doctor                        # 全面体检
openclaw gateway status                # gateway 运行状态
openclaw logs --channel feishu        # 飞书通道日志
openclaw agents list --bindings        # 查 agent 和绑定
pkill -f openclaw && openclaw gateway restart  # 强制重启
```

**常见 7 个翻车点：**
1. Gateway 启动失败 → 检查 binding type/JSON/duplicate accountId/appSecret
2. Bot 不响应 → 检查应用发布状态/凭证/gateway/日志
3. 消息发错 Agent → accountId 在 channels 和 bindings 不一致
4. 子 Agent 孵化失败 → agentId 未加进 allowAgents
5. agentToAgent 冲突 → enabled 设为 false
6. Agent 注册了但 list 不到 → 检查 JSON 结构或杀进程重试

## 小龙虾Workspace路径

给弟弟们传技能时，复制到各自workspace的skills目录：

- **招财 (zhaocai)**: `~/.openclaw/workspace-zhaocai/skills/`
- **算命 (suanming)**: `~/.openclaw/workspace-suanming/skills/`
- **肌肉 (jirou)**: `~/.openclaw/workspace-jirou/skills/`

---

这是我的工具箱，知道自己能干嘛。
