---
name: fundamental-stock-analysis
description: A股基本面分析 using Tushare data. Support stock tickers (600519, 000001, etc.), peer ranking, and fundamentals-based verdict. Default region: A-shares (CN).
---

# fundamental-stock-analysis

1. Read `references/playbook.md` before starting analysis.
2. Follow the playbook steps exactly (input parse -> data collection -> quick screen -> scoring -> rating -> output).
3. For multi-ticker requests, analyze each ticker first, then rank peers and select best pick with invalidation triggers.
4. Always include confidence level and call out stale/conflicting data explicitly.
5. Do not append any machine-readable JSON block in user-facing output.
6. Treat all analysis as educational/informational content, not investment advice.

## Security scope (clarification)
- Use web retrieval only for ticker-relevant financial statements, filings, market/fundamental datasets, and relevant financial news.
- Do not request, handle, or expose credentials/secrets.
- Do not perform command execution, local file discovery unrelated to analysis, or arbitrary URL exploration outside ticker-relevant finance/news scope.

## Non-goals
- Data exfiltration or collection of private/non-public information.
- Browser/automation tasks outside equity fundamental analysis and citation gathering.

## Output discipline
- Keep conclusions decisive and risk-aware.
- Separate business quality, balance-sheet safety, and valuation.
- Never fabricate missing metrics; mark `NA`.


## ⚠️ Self-Verify 输出前核查

使用本 skill 产出结论后、发给用户之前，必须完成以下核查：

1. **数据溯源**：所有结论必须能在原始数据/脚本输出中找到对应依据，禁止脑补
2. **不确定降级**：出现"绝对/肯定/永远"→ 改写为"可能/通常/大概率"
3. **矛盾检查**：是否与之前说过的内容矛盾？矛盾则明说"之前说错了"
4. **通过检查后再输出**
