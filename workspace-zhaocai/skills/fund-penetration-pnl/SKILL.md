---
name: fund-penetration-pnl
description: 基金持仓穿透收益计算（合并版）。包含：收盘穿透盈亏、盘中估值、尾盘分析。触发场景：用户说"算一下基金收益"、"穿透分析"、"基金持仓盈亏"、"盘中估值"、"尾盘调仓"。
---

# fund-penetration-pnl（合并版）

**本 skill 合并了原 fund-penetration、fund-intraday-estimator 的全部功能。**

**数据源优先级：push2.eastmoney.com（A股）> 腾讯（港美股）> Yahoo Finance（兜底）**
**持仓数据：统一从 `workspace-zhaocai/holdings.json` 读取，不再硬编码。**

---

## 数据来源

| 数据项 | 来源 |
|--------|------|
| A股价格/涨跌幅 | `push2.eastmoney.com/api/qt/ulist.np/get` |
| 港股/美股价格 | Yahoo Finance `query1.finance.yahoo.com` |
| 基金NAV | `fundgz.1234567.com.cn`（国内）<br>`api.fund.eastmoney.com/f10/lsjz`（QDII备用）|
| 股票配置比例C1 | `fundf10.eastmoney.com/zcpz_{code}.html` |
| Q1持仓明细 | `fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=30` |
| 持仓本地缓存 | `skills/market-alert/references/fund_holdings.json` |

---

## 公式（用户指定）

```
占用资金 = A × B × C1% × D1%
盈亏     = 占用资金 × E1%

A  = 持有份额（MEMORY.md）
B  = 最新NAV（fundgz）
C1 = 基金股票总配置比例%（资产配置页）
D1 = 该股Q1占净值比例%（季报持仓页）
E1 = 今日涨跌幅（push2 A股 / Yahoo Finance 港美股）
```

> ⚠️ 注意：不需要再乘以 Q1 基金规模换算。D1% 本身已经是"占净值比例"，即该股占基金净资产的百分比，直接参与计算。

---

## 价格获取

### push2（A股，精确）

```python
def secid(code):
    c = code.strip()
    if c.startswith('6') or c.startswith('688'):
        return f"1.{c}"
    elif c.startswith('0') or c.startswith('3'):
        return f"0.{c}"
    return None

def get_push2_prices(codes):
    a_codes = []
    for c in codes:
        if c.startswith(('6','0','3','688')):
            sid = secid(c)
            if sid:
                a_codes.append(sid)
    if not a_codes:
        return {}
    result = {}
    BATCH = 80
    for i in range(0, len(a_codes), BATCH):
        batch = a_codes[i:i+BATCH]
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&invt=2&fields=f2,f3,f12,f14&secids={','.join(batch)}")
        try:
            r = requests.get(url, headers={"Referer": "https://fund.eastmoney.com/","User-Agent": "Mozilla/5.0"}, timeout=10)
            for item in r.json().get('data', {}).get('diff', []):
                code = item['f12'].lstrip('0').zfill(6)
                result[code] = {'f2': item['f2'], 'f3': item['f3']}  # f2=最新价, f3=涨跌幅%
        except:
            pass
    return result
```

### Yahoo Finance（港股/美股）

```python
CODE_MAP_HK = {
    "000700": "0700.HK", "000883": "0883.HK", "000175": "0175.HK",
    "000857": "0857.HK", "001818": "01818.HK", "000939": "00939.HK",
    "002142": "002142.HK", "001299": "01299.HK", "001668": "01168.HK",
    "068690": "06086.HK", "001179": "01179.HK", "009988": "09988.HK",
}
CODE_MAP_US = {
    "00NVDA": "NVDA", "00AAPL": "AAPL", "00MSFT": "MSFT",
    "00AMZN": "AMZN", "0GOOGL": "GOOGL", "00META": "META",
    "00AVGO": "AVGO", "00NFLX": "NFLX", "00ASML": "ASML",
    "000TSM": "TSM", "0000MU": "MU", "00FUTU": "FUTU",
}
```

---

## 用户持仓

```python
MY_FUND_HOLDINGS = {
    "163402": {"name": "兴全趋势投资",       "shares": 134513.34},
    "006113": {"name": "汇添富创新医药A",     "shares": 1508.31},
    "519069": {"name": "汇添富价值精选A",    "shares": 1127.23},
    "166002": {"name": "中欧新蓝筹A",         "shares": 37630.83},
    "000979": {"name": "景顺长城沪港深精选A", "shares": 4638.32},
    "006751": {"name": "富国互联科技A",       "shares": 23739.17},
    "004477": {"name": "嘉实沪港深回报",      "shares": 35096.95},
    "001371": {"name": "富国沪港深价值精选A", "shares": 33887.86},
    "166005": {"name": "中欧价值发现A",       "shares": 11491.47},
    "160706": {"name": "沪深300LOF",         "shares": 18541.19},
    "001668": {"name": "汇添富全球移动互联A", "shares": 4206.06},
    "118001": {"name": "易方达亚洲精选",      "shares": 5978.46},
    "004965": {"name": "泓德致远混合A",        "shares": 2415.48},
    "450009": {"name": "国富中小盘A",         "shares": 1706.26},
}
```

---

## 完整输出格式

每次报告必须**逐只基金展开**，包含每只重仓股的：
`代码` `名称` `D1%（占净值比）` `占用资金` `E1%（今日涨跌）` `盈亏`

涨跌超 ±2% 标注 🔴🟢。

---

**输出模板：**

```
📊 基金穿透持仓 | {date} 收盘（push2实时数据）
公式：占用资金 = A × B × C1% × D1% → 盈亏 = 占用资金 × E1%

═══════════════════════════════════════════════════════

【{基金名称}】
A={持有份额}份 B={NAV} C1={股票配置比例}% → 市值={A×B:,.0f}元 → {合计盈亏}

  代码      名称           D1%      占用资金    E1涨跌      盈亏
  ──────────────────────────────────────────────────
  600xxx  耀皮玻璃       0.95%     1,088  +9.99%    +109元🟢
  600xxx  中天科技       3.69%     4,225  +1.15%     +49元🟢
  002371  北方华创       2.96%     3,389  -2.86%     -97元 🔴
  688041  海光信息       7.44%     8,519  -6.60%    -562元 🔴
  ...
  基金穿透合计:   -1,923元

═══════════════════════════════════════════════════════

【第二只基金】...（同样格式）...

═══════════════════════════════════════════════════════
  穿透总计: {grand_total:>+,.0f}元
⚠️ 估算数据，基于Q1持仓比例，实际以账户数据为准
```

> **占用资金 = A × B × C1% × D1%**  
> 例如：163402 持有 134,513.34 份，NAV=0.9542，C1=89.21%，海光信息 D1=7.44%  
> → 占用资金 = 134,513.34 × 0.9542 × 89.21% × 7.44% = **8,519元**  
> → 盈亏 = 8,519 × (-6.60%) = **-562元**

---

## 定时任务

- **14:50（每个交易日）**：跑 `fund_penetration_pnl.py`，输出完整格式，推送飞书
- 脚本路径：`skills/fund-penetration-pnl/scripts/fund_penetration_pnl.py`
- 数据源：push2（A股）+ Yahoo Finance（港美股）

## ⚠️ Self-Verify 输出前核查

使用本 skill 产出结论后、发给用户之前，必须完成以下核查：

1. **数据溯源**：所有结论必须能在原始数据/脚本输出中找到对应依据，禁止脑补
2. **不确定降级**：出现"绝对/肯定/永远"→ 改写为"可能/通常/大概率"
3. **矛盾检查**：是否与之前说过的内容矛盾？矛盾则明说"之前说错了"
4. **通过检查后再输出**
