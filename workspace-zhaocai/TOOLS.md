# TOOLS.md - 招财工具配置

## 数据源优先级

### A股实时行情
1. **push2.eastmoney.com**（东方财富，最准确，首选）
2. **qt.gtimg.cn**（腾讯财经，无需API Key）
3. **akshare stock_zh_a_spot_em()**（批量全A股）
4. **hq.sinajs.cn**（新浪，最后兜底，可能限流）

### 港美股
1. **qt.gtimg.cn**（腾讯，hk/us前缀）
2. **query1.finance.yahoo.com**（Yahoo Finance）

### 基金净值
1. **fundgz.1234567.com.cn**（天天基金盘中估值）
2. **fundmobapi.eastmoney.com**（批量GSZ）
3. **api.fund.eastmoney.com/f10/lsjz**（QDII历史净值）

### 外汇
1. **hq.sinajs.cn**（新浪，9种货币对）
2. **push2.eastmoney.com**（东方财富兜底）
3. **akshare currency_boc_safe()**（中行牌价，最终兜底）

## 持仓数据

统一从 `holdings.json` 读取，调仓后只需更新这一个文件。

## Workspace Skills（11个）

| 技能 | 用途 |
|------|------|
| a-stock-trading-assistant | 个股分析+六层决策框架 |
| fund-penetration-pnl | 基金穿透盈亏（合并版） |
| market-alert | 市场异动监控 |
| new-akshare-stock | akshare CLI |
| stock-price-query | 多市场查价（腾讯API） |
| tail-position-overnight | 尾盘选股 |
| fundamental-stock-analysis | 基本面分析（prompt） |
| investment-team | 投资团队调度 |
| minimax-image-understanding | 图片理解 |
| self-verify | 自检验证 |
| shared | 统一价格获取模块 |

## 关键脚本路径

- 市场异动: `skills/market-alert/scripts/scan_alert.py`
- 基金穿透: `skills/fund-penetration-pnl/scripts/fund_penetration_pnl.py`
- 收盘分析: `skills/fund-penetration-pnl/scripts/close_analysis.py`
- 持仓更新: `skills/market-alert/scripts/update_fund_holdings.py`
- 尾盘选股: `skills/tail-position-overnight/scripts/tail_screen.py`
