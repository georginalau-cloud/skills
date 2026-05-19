#!/usr/bin/env python3
"""
fund_penetration_pnl.py
计算用户基金持仓的穿透收益

公式（用户指定）：
  某股占用资金 = A × B × C1% × D1%
  某股当日盈亏 = 占用资金 × E1%
  A  = 持有份额（MEMORY.md）
  B  = 最新NAV（天天基金接口）
  C1 = 基金股票总配置比例%（资产配置页）
  D1 = 该股Q1占净值比例%（季报持仓页）
  E1 = 该股今日涨跌幅（新浪/Yahoo Finance）
"""
import sys, json, re, time, requests
from pathlib import Path
from bs4 import BeautifulSoup

# ── 用户基金持仓（从统一 holdings.json 读取）──────────────────
import pathlib as _pathlib
_HOLDINGS_PATH = _pathlib.Path(__file__).parent.parent.parent.parent / "holdings.json"

def _load_holdings():
    if _HOLDINGS_PATH.exists():
        with open(_HOLDINGS_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {"stocks": {}, "etfs": {}, "funds": {}}

_H = _load_holdings()
MY_FUND_HOLDINGS = {code: {"name": info["name"], "shares": info["shares"]}
                    for code, info in _H.get("funds", {}).items()}

FUND_HOLDINGS_PATH = Path(__file__).parent.parent.parent / "market-alert" / "references" / "fund_holdings.json"

# ── 价格获取 ───────────────────────────────────────────────

def secid(code):
    """将基金持仓代码转为 push2 secid 格式"""
    c = code.strip()
    if c.startswith('6') or c.startswith('688'):
        return f"1.{c}"
    elif c.startswith('0') or c.startswith('3'):
        return f"0.{c}"
    return None

def get_push2_prices(codes):
    """通过 push2.eastmoney.com 获取 A 股实时涨跌幅，精确度远高于新浪"""
    secids = {}
    a_codes = []
    for c in codes:
        if c.startswith(('6','0','3','688')):
            sid = secid(c)
            if sid:
                secids[c] = sid
                a_codes.append(sid)
    if not a_codes:
        return {}
    result = {}
    # 东方财富限制每批最多80个
    BATCH = 80
    for i in range(0, len(a_codes), BATCH):
        batch = a_codes[i:i+BATCH]
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&invt=2&fields=f2,f3,f12,f14&secids={','.join(batch)}")
        try:
            r = requests.get(url, headers={"Referer": "https://fund.eastmoney.com/",
                                              "User-Agent": "Mozilla/5.0"}, timeout=10)
            for item in r.json().get('data', {}).get('diff', []):
                code = item['f12'].lstrip('0').zfill(6)
                result[code] = {'f2': item['f2'], 'f3': item['f3']}
        except Exception:
            pass
    return result

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

def get_yahoo_prices(codes_hk, codes_us):
    result = {}
    for c in set(codes_hk):
        yf = CODE_MAP_HK.get(c)
        if not yf: continue
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{yf}?interval=1d&range=2d",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            d = r.json()["chart"]["result"][0]["meta"]
            cur = d["regularMarketPrice"]
            prev = d.get("previousClose") or d.get("chartPreviousClose", cur)
            for raw, yf2 in CODE_MAP_HK.items():
                if yf2 == yf: result[raw] = {'cur': cur, 'prev': prev, 'chg': (cur-prev)/prev*100}
            time.sleep(0.2)
        except: pass
    for c in set(codes_us):
        yf = CODE_MAP_US.get(c)
        if not yf: continue
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{yf}?interval=1d&range=2d",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            d = r.json()["chart"]["result"][0]["meta"]
            cur = d["regularMarketPrice"]
            prev = d.get("previousClose") or d.get("chartPreviousClose", cur)
            for raw, yf2 in CODE_MAP_US.items():
                if yf2 == yf: result[raw] = {'cur': cur, 'prev': prev, 'chg': (cur-prev)/prev*100}
            time.sleep(0.2)
        except: pass
    return result

# ── 基金数据 ───────────────────────────────────────────────

def get_fund_nav(fund_code):
    """获取基金NAV和日涨幅，fundgz优先，lsjz作备用（QDII基金用lsjz）"""
    # 方法1: fundgz（国内基金可用）
    try:
        url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js?rt={int(time.time())}"
        r = requests.get(url, headers={"Referer": "https://fund.eastmoney.com/","User-Agent":"Mozilla/5.0"}, timeout=8)
        m = re.search(r'jsonpgz\((.+)\)', r.text)
        if m and 'dwjz' in m.group(1):
            d = json.loads(m.group(1))
            return float(d['dwjz']), float(d['gszzl']), d['jzrq']
    except: pass
    # 方法2: lsjz（QDII基金/港美股基金用这个）
    try:
        url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex=1&pageSize=1"
        r = requests.get(url, headers={"Referer": "https://fundf10.eastmoney.com/","User-Agent":"Mozilla/5.0"}, timeout=8)
        d = r.json()
        items = d.get('Data', {}).get('LSJZList', [])
        if items:
            latest = items[0]
            return float(latest['DWJZ']), float(latest.get('JZZZL', 0)), latest['FSRQ']
    except: pass
    return None, None, None

def get_fund_c1(fund_code):
    """从资产配置页抓基金股票总配置比例C1%"""
    try:
        url = f"https://fundf10.eastmoney.com/zcpz_{fund_code}.html"
        headers = {"Referer": "https://fundf10.eastmoney.com/", "User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(r.text, 'lxml')
        for t in soup.find_all('table'):
            rows = t.find_all('tr')
            for row in rows[1:2]:  # 最新一期
                cells = row.find_all('td')
                if len(cells) >= 2:
                    text = cells[1].get_text(strip=True)
                    if '%' in text:
                        return float(text.replace('%',''))
    except: pass
    return None

def load_fund_holdings():
    if not FUND_HOLDINGS_PATH.exists(): return {}
    with open(FUND_HOLDINGS_PATH) as f:
        raw = json.load(f)
    result = {}
    for fid, finfo in raw.get('fund_holdings', {}).items():
        holdings = [{'code': h['code'], 'name': h['name'],
                     'mv': h.get('market_value',0), 'pct': h['percent']}
                    for h in finfo.get('holdings', [])]
        result[fid] = {'name': finfo.get('name',''), 'holdings': holdings}
    return result

# ── 主逻辑 ───────────────────────────────────────────────

def run(json_output=False, target_fund=None):
    print("=" * 70)
    print(" 基金穿透收益计算 | " + time.strftime("%Y-%m-%d %H:%M"))
    print("=" * 70)

    fund_holdings = load_fund_holdings()
    if not fund_holdings:
        print("⚠️ 未找到Q1穿透数据，请先运行 update_fund_holdings.py")
        return

    funds_to_run = MY_FUND_HOLDINGS if not target_fund else {target_fund: MY_FUND_HOLDINGS[target_fund]}

    # Step 1: 获取所有基金的NAV和C1
    print("\n📥 获取基金NAV和股票配置比例...")
    fund_meta = {}
    for fid in funds_to_run:
        nav, nav_chg, date = get_fund_nav(fid)
        c1 = get_fund_c1(fid)
        fund_meta[fid] = {'nav': nav, 'nav_chg': nav_chg, 'date': date, 'c1': c1}
        status = "OK" if nav and c1 else "缺失"
        print(f"  {fid} {funds_to_run[fid]['name'][:8]}: NAV={nav} C1={c1}% [{status}]")

    # Step 2: 收集所有穿透股代码
    all_codes = set()
    a_codes, hk_codes, us_codes = [], [], []
    for fid in fund_holdings:
        for h in fund_holdings[fid]['holdings']:
            c = h['code']
            if c not in all_codes:
                all_codes.add(c)
                if c in CODE_MAP_HK: hk_codes.append(c)
                elif c in CODE_MAP_US: us_codes.append(c)
                else: a_codes.append(c)

    print(f"\n📥 获取{len(all_codes)}只穿透股价格（A股{len(a_codes)} 港股{len(hk_codes)} 美股{len(us_codes)}）...")
    push2 = get_push2_prices(a_codes)
    yahoo = get_yahoo_prices(hk_codes, us_codes)
    prices = {**push2, **yahoo}
    print(f"  成功获取: {len(prices)}/{len(all_codes)}")

    # Step 3: 逐基金计算
    # 公式: 占用资金 = A × B × C1% × D1%  盈亏 = 占用资金 × E1%
    fund_results = {}
    grand_total = 0

    for fid, info in funds_to_run.items():
        A = info['shares']
        B = fund_meta[fid]['nav']
        C1 = fund_meta[fid]['c1']
        if B is None or C1 is None:
            print(f"\n  ⚠️ {info['name']} 数据不全，跳过")
            continue

        AB = A * B
        holdings = fund_holdings.get(fid, {}).get('holdings', [])

        rows = []
        for h in holdings:
            E1 = prices.get(h['code'], {}).get('f3', 0.0)
            if not E1 and prices.get(h['code']):
                E1 = prices[h['code']].get('chg', 0.0)
            D1 = h['pct']
            my_mv = AB * (C1/100) * (D1/100)
            pnl = my_mv * E1 / 100
            rows.append({'code': h['code'], 'name': h['name'],
                         'D1': D1, 'my_mv': my_mv, 'E1': E1, 'pnl': pnl})

        total_pnl = sum(r['pnl'] for r in rows)
        grand_total += total_pnl

        fund_results[fid] = {
            'name': info['name'], 'A': A, 'B': B, 'C1': C1,
            'AB': AB, 'rows': rows, 'total_pnl': total_pnl,
        }

    # Step 4: 汇总个股
    stock_agg = {}
    for fid, res in fund_results.items():
        for r in res['rows']:
            c = r['code']
            if c not in stock_agg:
                stock_agg[c] = {'code': c, 'name': r['name'], 'my_mv': r['my_mv'],
                                'E1': r['E1'], 'pnl': r['pnl'], 'funds': [fid]}
            else:
                stock_agg[c]['my_mv'] += r['my_mv']
                stock_agg[c]['pnl'] += r['pnl']
                stock_agg[c]['funds'].append(fid)

    if json_output:
        out = {fid: {k:v for k,v in res.items() if k!='rows'} for fid,res in fund_results.items()}
        out['stock_summary'] = stock_agg
        out['grand_total'] = grand_total
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # Step 5: 输出
    print(f"\n{'='*70}")
    print(" 表1：各基金穿透重仓股明细")
    print(f"{'='*70}")
    for fid, res in fund_results.items():
        print(f"\n【{res['name']}】")
        print(f"  A={res['A']:,}份 B={res['B']} C1={res['C1']}% → 市值={res['AB']:,.0f}元")
        print(f"  {'代码':<8}{'名称':<10}{'D1%':>6}{'占用资金':>10}{'E1涨跌':>8}{'盈亏':>9}")
        print(f"  {'─'*50}")
        for r in sorted(res['rows'], key=lambda x: -x['pnl']):
            flag = " 🔴" if r['E1'] < -1 else ("🟢" if r['E1'] > 1 else "")
            print(f"  {r['code']:<8}{r['name']:<10}{r['D1']:>5.2f}%{r['my_mv']:>10,.0f}{r['E1']:>+7.2f}%{r['pnl']:>+8,.0f}元{flag}")
        print(f"  基金穿透合计: {res['total_pnl']:>+8,.0f}元")

    print(f"\n{'='*70}")
    print(" 表2：穿透重仓股 — 合计盈亏排序")
    print(f"{'='*70}")
    print(f"  {'代码':<8}{'名称':<10}{'占用资金':>10}{'E1涨跌':>8}{'合计盈亏':>9}{'持有基金'}")
    print(f"  {'─'*55}")
    for s in sorted(stock_agg.values(), key=lambda x: -x['pnl']):
        fs = "+".join(f[:6] for f in s['funds'])
        flag = " ◀重叠" if len(s['funds']) > 1 else ""
        print(f"  {s['code']:<8}{s['name']:<10}{s['my_mv']:>10,.0f}{s['E1']:>+7.2f}%{s['pnl']:>+8,.0f}元 {fs}{flag}")

    print(f"\n{'─'*55}")
    print(f"  {'穿透总计':>40}  {grand_total:>+9,.0f}元")
    print(f"\n{'='*70}")
    print(f"  📊 穿透合计: {grand_total:>+,.0f}元")
    print(f"  ⚠️ 估算数据，基于Q1持仓比例，实际以账户数据为准")
    print(f"{'='*70}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--fund', type=str)
    args = parser.parse_args()
    run(json_output=args.json, target_fund=args.fund)
