# Session Summary — 2026-05-24 配置修复与部署同步

> 日期：2026-05-24
> 延续自：session-summary-0521.md
> 本次重点：openclaw.json 配置修复 + 部署同步流程 + 招财尾盘/短线 payload 重写

---

## 本次完成的工作

### 1. 基金尾盘分析 payload 重写

**文件**：`cron/jobs.json`（zhaocai-1445-fund-tail-analysis）

**问题**（来自5/22实际输出）：
1. 场内ETF只有总浮盈，没有当日盈亏金额
2. 场外基金"穿透贡献"列大部分是0元，定义不清
3. 穿透重仓股TOP5用的是隔夜美股数据，不是今天A股
4. 大盘数据胡说（"沪指站上3300点"未验证）
5. 短线验证没头没尾（不知道为什么跟踪这些标的）

**修复**：完整重写 payload，6个板块：
- 大盘概况（必须报上证指数具体点位）
- 场内ETF（每只含今日盈亏¥和总浮盈¥）
- 场外基金盘中估值（每只含今日预估盈亏¥，公式写死）
- 穿透重仓股（仅A股+港股，不含隔夜美股，含"对你的影响≈¥xx"）
- 尾盘操作建议（止盈/加仓/持有）
- 汇总（今日持仓总预估盈亏）

### 2. 短线验证 payload 重写

**问题**：输出没有上下文，看不懂为什么跟踪这些标的

**修复**：新格式要求先展示"推荐逻辑+关键价位"，再展示实时表现，最后给验证结论

### 3. openclaw.json 配置修复

**问题**：`openclaw doctor` 改坏了配置，导致所有 agent 无响应

**doctor 的破坏性改动**：
- 肌肉 heartbeat `{"enabled": false}` — openclaw 不认识 `enabled` key
- `tools.web.search` 里加了 `"fallback"` 和 `"tavily"` — openclaw 不支持

**修复**：
- heartbeat 改为空对象 `{}`（= 不启用）
- web search provider 直接改为 `"tavily"`（Brave 5美元免费额度用完了）
- tavily plugin entry 加在 `plugins.entries` 里（API key 用环境变量）

**重要教训**：
- openclaw 的 heartbeat 禁用方式是空对象 `{}`，不是 `{"enabled": false}`
- `tools.web.search` 只支持 `enabled` 和 `provider` 两个字段，不支持 `fallback`/`tavily` 等自定义字段
- 不要随便跑 `openclaw doctor --fix`，它会改坏自定义配置

### 4. Tavily 搜索兜底

**配置**：
- `tools.web.search.provider` = `"tavily"`
- `plugins.entries.tavily.config.webSearch.apiKey` = `"${TAVILY_API_KEY}"`
- `.env` 里加 `TAVILY_API_KEY=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`

### 5. NZD 定存套利计算器

**文件**：`workspace-zhaocai/scripts/nzd_deposit_calculator.py`

**机制**：汇丰香港"外币兑换+定存"捆绑优惠
- NZD 必须换出去才能享受利率（NZD 直接放着只有活期）
- 到期后不换回，直接换成下一个高利率货币继续定存（链式）
- 利率固定（AUD/GBP 14%年化1周，CAD/NZD 12.5%，USD 10.3%等）
- 风险 = 换汇点差 + 汇率波动

**脚本功能**：
- 获取当前持有货币对所有目标货币的汇率
- 计算每种方案的1周净收益（利息-点差）
- 多周滚动模拟
- 推荐最优方案

---

## 部署同步方法

openclaw 跑在另一台 MacBook 上（用户名 `georginalau`）。同步方式：

```bash
# 下载单个文件
curl -sL "https://raw.githubusercontent.com/georginalau-cloud/skills/main/[路径]" -o ~/.openclaw/[路径]

# 或者 clone 整个 repo 后批量复制
cd /tmp && git clone https://github.com/georginalau-cloud/skills.git
cp /tmp/skills/cron/jobs.json ~/.openclaw/cron/jobs.json
# ... 其他文件
rm -rf /tmp/skills
openclaw gateway restart
```

**注意**：GitHub raw CDN 有缓存（几分钟），push 后立即 curl 可能拿到旧版本。

---

## 需要同步到 openclaw 机器的文件完整列表

| 文件 | 目标路径 |
|------|---------|
| `cron/jobs.json` | `~/.openclaw/cron/jobs.json` |
| `openclaw.json` | `~/.openclaw/openclaw.json` |
| `workspace-zhaocai/SOUL.md` | `~/.openclaw/workspace-zhaocai/SOUL.md` |
| `workspace-zhaocai/HEARTBEAT.md` | `~/.openclaw/workspace-zhaocai/HEARTBEAT.md` |
| `workspace-zhaocai/scripts/portfolio_analyzer.py` | `~/.openclaw/workspace-zhaocai/scripts/portfolio_analyzer.py` |
| `workspace-zhaocai/scripts/nzd_deposit_calculator.py` | `~/.openclaw/workspace-zhaocai/scripts/nzd_deposit_calculator.py` |
| `workspace-zhaocai/scripts/stock_data.py` | `~/.openclaw/workspace-zhaocai/scripts/stock_data.py` |
| `workspace-zhaocai/skills/shared/price_fetcher.py` | `~/.openclaw/workspace-zhaocai/skills/shared/price_fetcher.py` |
| `workspace-suanming/SOUL.md` | `~/.openclaw/workspace-suanming/SOUL.md` |
| `workspace-suanming/skills/suanming-bazi-analyzer/src/07-bazi_chart_year.py` | 同路径 |
| `workspace-suanming/skills/suanming-bazi-analyzer/src/09-bazi_chart_day.py` | 同路径 |
| `workspace-suanming/skills/suanming-bazi-analyzer/lib/22-daily_fortune.py` | 同路径 |
| `workspace-guanjia/SOUL.md` | `~/.openclaw/workspace-guanjia/SOUL.md` |
| `workspace-jirou/SOUL.md` | `~/.openclaw/workspace-jirou/SOUL.md` |

---

## 待解决的问题

### 1. zhi_relations.py 分析顺序调整
用户要求：先分析原局地支之间的关系（existing_zhis），再分析新加入地支（大运/流年/流月/流日）与原局的关系。当前是反过来的。

### 2. GitHub 和本地 test-repo 可能不同步
用户发现 GitHub 上的内容和桌面 test-repo 不一致。需要重新 clone 确认。

### 3. 代理分流（未解决）
web_search 需要代理访问 Google，akshare 不能走代理访问国内金融接口。需要在代理工具里配规则分流。

### 4. Brave Search 额度
5美元免费额度用完了，当前已切换到 Tavily。下个月 Brave 额度重置后可以切回来。

---

## 下次 session 如何继续

1. 引用 `.kiro/context/session-summary-0524.md`
2. 重新 clone repo 到桌面确认内容一致性
3. 继续修 zhi_relations.py 的分析顺序
4. 观察 agent 输出是否改善
