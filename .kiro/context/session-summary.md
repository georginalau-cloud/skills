# Session Summary — OpenClaw Repo 全面审计与修复

> 最后更新：2026-05-20
> 涉及 session：2 次（前一次 128 条消息 + 本次）

---

## 项目概况

- **Repo 位置**：`/Users/georgina.liu/Desktop/test-repo`
- **远程仓库**：`git@github.com:georginalau-cloud/skills.git` (main 分支)
- **用途**：OpenClaw 多 agent 系统的配置、脚本、workspace 文件
- **4 个 Agent**：管家(guanjia)、肌肉(jirou)、算命(suanming)、招财(zhaocai)
- **通信渠道**：飞书（每个 agent 有独立 accountId 和用户 open_id）

---

## 已完成的所有工作

### Task 1: 肌肉 phantom heartbeat
- 问题：jirou 不断发"检查清单状态"消息
- 修复：`openclaw.json` 设置 `heartbeat: { enabled: false }`

### Task 2: 肌肉 workflow 重写
- Garmin 抓取从 23:59 改到次日 06:00，07:00 兜底
- 07:55 生成+发送日报（原来分两步）
- 文件命名改为 `type-YYYY-MM-DD.md`
- 用户可随时发数据，到时间点自动跳过提醒

### Task 3: 招财 workflow + heartbeat 重写
- heartbeat 扩展为全持仓监控（9股+4ETF+14基金+8外汇+大宗）
- 7 个 cron job（晨报08:30/尾盘14:45/收盘15:30/异动每小时/短线每半小时/国际金融4次/基金穿透周一）
- NZD 存款策略分析
- 外汇监控：NZD/AUD/CAD/HKD/KRW/GBP/EUR

### Task 4: 管家修复
- 日记 cron 移除政治内容触发
- 机票监控（上海-首尔、上海-曼谷，周四19:00+出发/周日21:00-回/≤1500元）
- mentionMode 改为 default
- SOUL.md 强化路由规则和自检

### Task 5: 算命日运修复
- cron payload 重写为严格5步流程
- 移除 `thinking: "high"`
- SOUL.md 新增7条铁规

### Task 6: bazi 脚本增强
- `daily_fortune.py`：力量导向幸运色 + 通关逻辑
- `zhi_relations.py`：天干透出检查 + 三合拱（仅缺旺支中神）
- `wuyu_analyzer.py`：通关6关系 + SCENE_WEIGHTS + 正官/七杀区分
- `ganzhi_calculator.py`：拱合权重 0.8

### Task 7: 全 skill self-verify
- 22 个 skill 添加标准化 self-verify 块

### Task 8: 招财 skill 整合（13→11）
- 删除重复 skill，创建 `holdings.json` 统一数据源
- 创建 `skills/shared/price_fetcher.py`（4级 fallback）
- 清理冗余脚本

### Task 9: Repo 清理
- 删除 TradingAgents-CN (36.9MB)、stray files、browser cache
- .gitignore 添加 `browser/` 和 `**/.openclaw/`

### Task 10: 全面审计（28项问题全部修复）
- P0×12：逻辑错误/数据错误（路径错误、时间矛盾、数据源错误等）
- P1×9：不一致/冗余（文件命名、消息流程描述、死代码等）
- P2×7：内容缺失（AGENTS.md 模板未适配、英文未翻译等）

---

## Repo 架构说明

```
agents/xxx/agent/          ← 系统级配置（OpenClaw 引擎读取）
  ├── AGENTS.md            ← 多 agent 协作权限
  ├── bootstrap.yaml       ← cron/heartbeat 配置摘要
  ├── models.json          ← 可用 LLM 模型
  └── auth-profiles.json   ← 飞书账号绑定

workspace-xxx/             ← Agent 运行时工作区（agent session 中读取）
  ├── AGENTS.md            ← 行为手册（会话启动读取顺序）
  ├── SOUL.md              ← 身份定义 + 核心流程
  ├── IDENTITY.md          ← 简短身份卡片
  ├── USER.md              ← 用户信息
  ├── MEMORY.md            ← 长期记忆
  ├── TOOLS.md             ← 工具配置细节
  ├── WORKFLOW.md          ← 工作流规则（jirou 有）
  ├── RULES.md             ← 业务规则（jirou 有）
  ├── HEARTBEAT.md         ← heartbeat 配置
  ├── scripts/             ← 运行脚本
  ├── skills/              ← skill 代码
  └── memory/              ← 运行时数据（pending/reports）

cron/jobs.json             ← 所有定时任务配置
openclaw.json              ← OpenClaw 全局配置（heartbeat 等）
```

---

## 关键技术细节

### 飞书用户 ID
| Agent | accountId | 用户 open_id |
|-------|-----------|-------------|
| 管家 | guanjia | ou_e62c3623b382df683370c131baf8f4c8 |
| 肌肉 | jirou | ou_aaf284a8365c85e8b792bb77b9bc8d59 |
| 算命 | suanming | ou_f9095feb1adeb3f3997725460bcdd87d |
| 招财 | zhaocai | ou_e47f62cad7fec339fba10ae6e1f5a3c9 |

### 数据源优先级（A股）
push2.eastmoney → qt.gtimg.cn → akshare → hq.sinajs.cn

### 八字脚本入口
```bash
/opt/homebrew/bin/python3 ~/.openclaw/workspace-suanming/skills/suanming-bazi-analyzer/bin/bazi
```

### 沛柔八字（机密）
己巳年 丁丑月 癸酉日 己未时（坤造）

---

## 用户偏好/要求

- 所有内容必须准确无误，不要流于表面
- 不要 placeholder，不要错误数据，不要文件间矛盾
- 拱合只适用于三合缺旺支（中神），不是三会拱或相邻夹拱
- 正官(+2稳定权力) vs 七杀(+1压力需制化) 在禄维度不同
- 五运分析层级：原局(底色) → 大运(背景) → 流年(太岁) → 流月(应期) → 流日(焦点)
- 推送命令：`git push git@github.com:georginalau-cloud/skills.git HEAD:main --force`

---

## 下次 session 如何继续

1. 在 Kiro 中用 `#File` 引用此文件，或直接说"读一下 .kiro/context/session-summary.md"
2. 告诉我你要继续做什么
3. 我会基于这个摘要接上之前的工作

---

## 🔴 当前进行中的工作（2026-05-21）

### 问题 1：Garmin Token 每天过期
- **状态**：待开始
- **方案**：用 `python-garminconnect` + `garth` 库替代 `gccli`，支持 token 持久化 + 自动 refresh
- **文件**：新建 `workspace-jirou/scripts/garmin_fetch.py`

### 问题 2：算命日运胡说八道
- **状态**：部分完成
- **已完成**：
  - `src/07-bazi_chart_year.py` 的 `_calc_zhi_interactions` 已加入三会局 + 六害检测 ✅
  - 自刑格式已修正为 `午午自刑` ✅
- **待完成**：
  - `lib/22-daily_fortune.py`：`_compute_lucky` 调用时缺少 `relations`/`ji_shen`/`xi_shen` 参数，导致力量主导逻辑从未触发。需要在调用处用 `lib/zhi_relations.py` 的 `analyze_zhi_relations` 获取完整关系后传入
  - 幸运色"火太旺需要制衡"逻辑：`_compute_lucky` 的 v2 逻辑已经有通关处理（忌神极旺时用通关五行色），但因为没传 `relations` 所以从未生效
  - Self-verify 强制化：cron payload 已有 self-verify 步骤，但需要加入"三会局是否遗漏"检查项
  - LLM 发挥约束：需要在 SOUL.md 或 cron payload 中明确"禁止给出与脚本数据矛盾的延展"

### 问题 3：招财数据源 + 持仓盈亏
- **状态**：待开始
- **报错原因分析**：
  - "代理问题" = openclaw 机器的网络代理不稳定，导致 akshare/东方财富等接口全部失败
  - "output new_sensitive" = 飞书内容安全审核拦截（可能是某些股票名称或数据触发）
  - "基金盘中估值中断" = 天天基金 API 不稳定或被限流
- **需要修的东西**：
  1. 网络代理问题：需要在 `price_fetcher.py` 中加入直连模式（bypass proxy），或者在 openclaw 机器上修复代理
  2. 持仓快扫增加盈亏金额：`scan_alert.py` 输出需要加入 `(现价-成本)*持仓数 = 浮盈/亏 ¥xxx` 和 `今日盈亏 = (现价-昨收)*持仓数`
  3. 基金穿透增加资金贡献：个股涨跌 × 该股在基金中的持仓比例 × 你持有的基金份额 = 对你的实际盈亏贡献

### 管家图片搜索能力（之前讨论的）
- **状态**：方案已确定，待安装
- **方案**：安装 `google-image-api-skill` + `feishu-block-ops`
- **安装命令**：`clawhub install google-image-api-skill && clawhub install feishu-block-ops`
