# Session Summary — 2026-05-21 微观修复与招财重构

> 日期：2026-05-21
> 延续自：session-summary.md（2026-05-20 全面审计与修复）
> 本次重点：算命脚本逻辑修复 + 肌肉缓存/Garmin + 招财完整重构

---

## 本次完成的所有工作

### 1. 算命（suanming）— 日运胡说八道问题

**问题来源**：2026-05-21 早上 08:04 的日运推送出现多个错误：
- "木泄火气"（五行常识错误，木生火不是泄火）
- 巳午未三会火局缺失（流年午+流月巳+流日未凑齐三会，但 interactions 没输出）
- Self-verify 没有执行（SOUL.md 有规则但 LLM 跳过了）

**修复内容**：

| 文件 | 改动 |
|------|------|
| `src/07-bazi_chart_year.py` | `_calc_zhi_interactions` 加入三会局（SANHUI常量）+ 六害（HAI常量）检测 |
| `src/09-bazi_chart_day.py` | 从导入简化版 `_calc_zhi_interactions` 改为调用 `lib/zhi_relations.py` 的 `analyze_zhi_relations`，统一引擎 |
| `lib/22-daily_fortune.py` | `_compute_lucky` v3 完整重写：偏枯制衡 / 用神太旺泄气 / 忌色溯源（`avoid_reason`字段）/ 力量主导触发 |
| `lib/22-daily_fortune.py` | 调用处传入完整 `relations`/`ji_shen`/`xi_shen` 参数（之前缺失导致 v2 逻辑从未触发） |
| `lib/22-daily_fortune.py` | 食物推荐改为与幸运色同逻辑（新增 `WUXING_FOODS` 常量） |
| `cron/jobs.json` 算命日运 | Self-verify 强制化：15条核查项分 ABCD 四类（数据一致性/完整性/逻辑自洽/格式） |
| `cron/jobs.json` 算命日运 | LLM 发挥约束：明确发挥边界、禁止编造五行逻辑、忌色必须引用 avoid_reason |
| `workspace-suanming/SOUL.md` | 铁规增至9条：新增第3条（三会局不能遗漏）、第6条（忌色必须引用avoid_reason）、LLM发挥边界段落 |

**关键技术决策**：
- 两条路径（interactions 输出给 LLM + daily_fortune 计算幸运色）统一为同一个引擎 `lib/zhi_relations.py`，不会冲突
- `_compute_lucky` v3 的忌色逻辑：忌克用神的五行色 + 忌助忌神的五行色（不是简单的"忌绿色因为木泄火气"）
- 偏枯判断：某五行力量 ≥5.0 且超平均3倍 → 极端，需要制衡

---

### 2. 肌肉（jirou）— Garmin Token + 缓存问题

| 文件 | 改动 |
|------|------|
| `cron/jobs.json` jirou-2100 | 从"被动检查 token 状态"改为"主动调用 API 续期"（`gccli health summary`） |
| `workspace-jirou/SOUL.md` | 新增「缓存铁规」：识别后必须立即建文件 + 回复必须包含"✅ 已保存至 memory/pending/xxx.md" |

**Garmin Token 结论**：
- 2026年3月 Garmin 加了 Cloudflare TLS 指纹检测 + 短信 2FA，完全自动化不可能
- 优化方案：每天 21:00 主动调 API 续期 token，只要每天至少一次成功调用就不会过期
- 如果 token 硬性 24h 过期（不管有没有调用），只能接受每天手动一次

---

### 3. 招财（zhaocai）— 完整重构

**问题**：
1. 数据源频繁报错（代理拦截国内金融接口）
2. 持仓快扫只有涨跌幅，没有盈亏金额
3. 基金穿透只有个股涨跌，没有对资金池的实际贡献
4. 分析隔靴搔痒，没有真正帮助决策的信息

**修复内容**：

| 文件 | 改动 |
|------|------|
| `scripts/portfolio_analyzer.py` | **新建**核心计算引擎：均线(5/10/20/60/120)/MACD/RSI/PE/支撑压力位/盈亏/仓位占比/信号判断 |
| `skills/shared/price_fetcher.py` | 加入直连模式（`ProxyHandler({})`绕过系统代理）+ `_urlopen_with_fallback` + `fetch_a_stock_prices` 别名 |
| `HEARTBEAT.md` | 重写输出格式：盈亏金额+贡献排名+基金穿透资金贡献+风险提示+数据源故障处理规则 |
| `cron/jobs.json` 晨报 | 重写为6大板块：宏观环境/持仓现状/行业景气/调仓建议(技术+基本面+产业链)/新机会/NZD定存 |
| `cron/jobs.json` 收盘总结 | 重写为7大板块：成绩单/逐项盈亏/核心驱动/调仓执行/验证复盘/明日展望/投资精华 |
| `cron/jobs.json` 短线监控 | timeout 120→180s + 简化任务（只拉价格算涨跌，不做复杂分析） |
| `cron/jobs.json` 市场异动 | timeout 120→180s + 禁止发技术报错给用户 |
| `workspace-zhaocai/SOUL.md` | 新增：报错处理规则（不发技术细节）+ 飞书敏感词规避（避免"暴跌""崩盘"等触发 error 1027） |

**招财决策信息框架（5层）**：
1. 宏观环境（美联储/央行/政策/地缘）→ 决定大方向
2. 行业景气（产业链/供需/景气度）→ 决定板块配置
3. 资金情绪（北向/融资/成交/涨跌比）→ 决定操作时机
4. 个股深度（技术面+基本面+产业链+事件）→ 决定具体标的
5. 新机会（未持有但值得关注的）→ 扩展投资视野

**调仓建议模板**：每个建议必须包含技术面（均线/MACD/RSI/换手率/支撑压力位）+ 基本面（PE vs 行业均值/营收增速）+ 产业链逻辑 + 近期事件 + 具体操作（价位/股数/止损位）

---

### 4. 全局 — AGENTS.md 适配

4个 workspace 的 AGENTS.md 从通用英文模板重写为实际场景适配（飞书通信/cron任务/自检规则/数据文件命名等）。

---

### 5. 管家图片搜索能力（方案确定，待安装）

**问题**：管家搜索图片不精准 + 只能贴在文档末尾
**方案**：安装 `google-image-api-skill` + `feishu-block-ops`
**安装命令**：`clawhub install google-image-api-skill && clawhub install feishu-block-ops`
**状态**：待在 openclaw 机器上执行安装

---

## 未解决的问题

### 代理分流（web_search 需要代理，akshare 不能走代理）

**根因**：Mac 上系统代理开着，web_search 走代理能访问 Google，但 akshare 也被迫走代理导致国内接口失败。

**解决方案**：在代理工具（Clash/Surge/V2Ray）里配规则分流：
```
# 国内金融数据源 — 直连
DOMAIN-SUFFIX,eastmoney.com,DIRECT
DOMAIN-SUFFIX,sinajs.cn,DIRECT
DOMAIN-SUFFIX,sina.com.cn,DIRECT
DOMAIN-SUFFIX,gtimg.cn,DIRECT
DOMAIN-SUFFIX,1234567.com.cn,DIRECT

# 国外 — 走代理
DOMAIN-SUFFIX,google.com,PROXY
DOMAIN-SUFFIX,bing.com,PROXY
```

**状态**：需要用户确认使用什么代理工具后配置

---

## 下次 session 如何继续

1. 在 Kiro 中引用 `.kiro/context/session-summary-0521.md`
2. 告诉我要继续做什么
3. 可能的后续工作：
   - 代理分流配置
   - 管家安装 `google-image-api-skill` + `feishu-block-ops`
   - 招财 `portfolio_analyzer.py` 实际运行测试和调优
   - 观察算命日运输出是否改善（明天 08:00 的 cron 会是第一次验证）
   - 观察招财晨报/收盘总结是否符合预期
