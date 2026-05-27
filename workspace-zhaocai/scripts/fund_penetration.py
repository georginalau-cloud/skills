#!/usr/bin/env python3
"""
fund_penetration.py — 基金穿透盈亏计算（自包含）
抓取基金季报重仓股 + 实时价格 → 计算穿透盈亏

两种模式：
  python3 fund_penetration.py                  # 盘中穿透估值（用缓存的重仓股数据）
  python3 fund_penetration.py --update         # 抓取最新季报重仓股（季报发布后运行）
  python3 fund_penetration.py --json           # JSON输出（供agent调用）
  python3 fund_penetration.py --fund 163402    # 只看单只基金

公式：
  占用资金 = A × B × C1% × D1%
  盈亏     = 占用资金 × E1%
  A  = 持有份额（holdings.json）
  B  = 最新NAV（天天基金）
  C1 = 基金股票总配置比例%（资产配置页）
  D1 = 该股占净值比例%（季报持仓）
  E1 = 该股今日涨跌幅%（push2/腾讯/新浪）

数据源：
  重仓股：天天基金 fundf10.eastmoney.com（季报持仓页）
  NAV：fundgz.1234567.com.cn（盘中估值）
  C1%：fundf10.eastmoney.com/zcpz（资产配置页）
  A股价格：push2.eastmoney.com > qt.gtimg.cn > hq.sinajs.cn
  港美股：Yahoo Finance
"""

import json
import re
import sys
import time
import argparse
import urllib.request
from pathlib import Path
from datetime import datetime

# ════════════════════════════════════════════════════════════
#  路径和配置
# ════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
HOLDINGS_PATH = WORKSPACE / "holdings.json"
CACHE_PATH = WORKSPACE / "scripts" / "fund_holdings_cache.json"

HEADERS = {
    "Referer": "https://fundf10.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# 不走代理的 opener（国内金融数据源直连）
_DIRECT_OPENER = None
def _get_opener():
    global _DIRECT_OPENER
    if _DIRECT_OPENER is None:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        https_handler = urllib.request.HTTPSHandler(context=ctx)
        proxy_handler = urllib.request.ProxyHandler({})
        _DIRECT_OPENER = urllib.request.build_opener(proxy_handler, https_handler)
    return _DIRECT_OPENER

def _urlget(url, timeout=12, encoding='utf-8'):
    """直连 GET 请求"""
    req = urllib.request.Request(url, headers=HEADERS)
    with _get_opener().open(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors='replace')


# ════════════════════════════════════════════════════════════
#  持仓加载
# ════════════════════════════════════════════════════════════

def load_funds() -> dict:
    """从 holdings.json 加载基金列表，返回 {code: {name, shares}}"""
    with open(HOLDINGS_PATH, encoding='utf-8') as f:
        data = json.load(f)
    funds = {}
    for code, info in data.get("funds", {}).items():
        if code.startswith("_") or not isinstance(info, dict) or "shares" not in info:
            continue
        funds[code] = {"name": info["name"], "shares": info["shares"]}
    return funds


# ════════════════════════════════════════════════════════════
#  季报重仓股抓取（--update 模式）
# ════════════════════════════════════════════════════════════

def fetch_fund_holdings(fund_code: str) -> dict:
    """从天天基金网抓取单只基金的最新季报全部持仓（不限TOP10）"""
    # topline=50 抓取尽可能多的持仓（天天基金最多展示全部披露的）
    url = (f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
           f"?type=jjcc&code={fund_code}&topline=50&year=&month=&r=0.{int(time.time()) % 100}")
    try:
        raw = _urlget(url, encoding='utf-8')
    except Exception as e:
        return {"error": f"请求失败: {e}"}

    # 解析 content:'...' 中的 HTML
    m = re.search(r"content:['\"](.+?)['\"],\s*arryear", raw, re.DOTALL)
    if not m:
        return {"error": "无季报数据（可能是新基金或QDII）", "raw_snippet": raw[:200]}

    html = m.group(1).replace("\\'", "'")

    # 提取报告期
    period_m = re.search(r'(\d{4})年(\d+)季度', html)
    period = f"{period_m.group(1)}Q{period_m.group(2)}" if period_m else "unknown"

    holdings = []
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 8:
            continue
        clean = [re.sub(r"<[^>]+>", "", c).strip().replace("&nbsp;", "").replace(",", "") for c in cells]
        try:
            seq = clean[0].strip()
            if not seq.isdigit():
                continue
            code = clean[1].strip().zfill(6)
            name = clean[2].strip()
            pct_str = clean[6].strip().replace("%", "")
            holdings.append({
                "code": code,
                "name": name,
                "pct": float(pct_str),  # D1%：占净值比例
            })
        except (ValueError, IndexError):
            continue

    # 同时尝试抓取债券持仓
    bonds = _fetch_fund_bonds(fund_code)

    return {"period": period, "holdings": holdings, "bonds": bonds}


def _fetch_fund_bonds(fund_code: str) -> list:
    """抓取基金债券持仓（季报披露的前5大债券）"""
    url = (f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
           f"?type=zqcc&code={fund_code}&topline=20&year=&month=&r=0.{int(time.time()) % 100}")
    try:
        raw = _urlget(url, encoding='utf-8')
    except Exception:
        return []

    m = re.search(r"content:['\"](.+?)['\"],\s*arryear", raw, re.DOTALL)
    if not m:
        return []

    html = m.group(1).replace("\\'", "'")
    bonds = []
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 5:
            continue
        clean = [re.sub(r"<[^>]+>", "", c).strip().replace("&nbsp;", "").replace(",", "") for c in cells]
        try:
            seq = clean[0].strip()
            if not seq.isdigit():
                continue
            code = clean[1].strip()
            name = clean[2].strip()
            pct_str = clean[3].strip().replace("%", "") if len(clean) > 3 else "0"
            bonds.append({
                "code": code,
                "name": name,
                "pct": float(pct_str) if pct_str else 0,
                "type": "bond",
            })
        except (ValueError, IndexError):
            continue
    return bonds


def fetch_fund_c1(fund_code: str) -> float:
    """抓取基金股票总配置比例 C1%（资产配置页）"""
    url = f"https://fundf10.eastmoney.com/zcpz_{fund_code}.html"
    try:
        raw = _urlget(url)
        # 找"股票占净值比例"后面的百分比
        m = re.search(r'股票占净值比例.*?([\d.]+)%', raw)
        if m:
            return float(m.group(1))
        # 备用：找表格第一行数据
        m2 = re.search(r'<td[^>]*class="tor"[^>]*>([\d.]+)%</td>', raw)
        if m2:
            return float(m2.group(1))
    except Exception:
        pass
    return 0.0


def update_all_holdings(funds: dict, target_fund: str = None):
    """抓取所有基金的季报重仓股，保存到缓存文件"""
    funds_to_update = {target_fund: funds[target_fund]} if target_fund else funds
    results = {}

    print(f"{'═'*60}")
    print(f"  📥 基金季报重仓股更新 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*60}")

    for i, (fid, info) in enumerate(funds_to_update.items(), 1):
        print(f"\n[{i}/{len(funds_to_update)}] {fid} {info['name']}...")

        # 抓重仓股
        h_result = fetch_fund_holdings(fid)
        if "error" in h_result:
            print(f"  ⚠️ 重仓股: {h_result['error']}")
            results[fid] = {"name": info["name"], "error": h_result["error"], "holdings": [], "bonds": [], "c1": 0}
        else:
            count = len(h_result["holdings"])
            bonds_count = len(h_result.get("bonds", []))
            print(f"  ✅ {h_result['period']} | {count}只重仓股" + (f" + {bonds_count}只债券" if bonds_count else ""))
            for h in h_result["holdings"][:3]:
                print(f"     {h['code']} {h['name']} {h['pct']:.2f}%")
            if count > 3:
                print(f"     ... 共{count}只")

            # 抓C1%
            c1 = fetch_fund_c1(fid)
            print(f"  C1(股票配置比例) = {c1:.1f}%")

            results[fid] = {
                "name": info["name"],
                "period": h_result["period"],
                "c1": c1,
                "holdings": h_result["holdings"],
                "bonds": h_result.get("bonds", []),
                "stock_count": count,
            }

        time.sleep(0.8)  # 限流

    # 合并旧缓存（保留未更新的基金）
    existing = _load_cache()
    existing.update(results)
    existing["_meta"] = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fund_count": len([k for k in existing if not k.startswith("_")]),
    }

    # 保存
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"\n{'═'*60}")
    print(f"  ✅ 已保存到 {CACHE_PATH.name}")
    success = sum(1 for k, v in results.items() if "error" not in v)
    print(f"  成功: {success}/{len(results)}")
    print(f"{'═'*60}")


def _load_cache() -> dict:
    """加载缓存的重仓股数据"""
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


# ════════════════════════════════════════════════════════════
#  实时价格获取
# ════════════════════════════════════════════════════════════

def _secid(code):
    """A股代码转 push2 secid"""
    if code.startswith(('6', '688')):
        return f"1.{code}"
    elif code.startswith(('0', '3', '15', '16')):
        return f"0.{code}"
    return None


def fetch_a_prices(codes: list) -> dict:
    """批量获取A股实时涨跌幅，返回 {code: change_pct}"""
    # P1: push2
    result = {}
    secids = []
    for c in codes:
        sid = _secid(c)
        if sid:
            secids.append(sid)

    if secids:
        BATCH = 80
        for i in range(0, len(secids), BATCH):
            batch = secids[i:i+BATCH]
            url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
                   f"?fltt=2&invt=2&fields=f2,f3,f12,f14&secids={','.join(batch)}")
            try:
                raw = _urlget(url)
                data = json.loads(raw)
                for item in data.get('data', {}).get('diff', []):
                    code = str(item.get('f12', '')).zfill(6)
                    chg = item.get('f3')
                    if chg is not None:
                        result[code] = float(chg)
            except Exception:
                pass

    # P2: 新浪兜底（缺失的）
    missing = [c for c in codes if c not in result and _secid(c)]
    if missing:
        symbols = []
        for c in missing:
            prefix = "sh" if c.startswith(('6', '688')) else "sz"
            symbols.append(f"{prefix}{c}")
        url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
        try:
            raw = _urlget(url, encoding='gbk')
            for line in raw.strip().split('\n'):
                if '=' not in line or '"' not in line:
                    continue
                key = line.split('=')[0].split('_')[-1]
                code = key.replace('sh', '').replace('sz', '')
                vals = line.split('"')[1].split(',')
                if len(vals) >= 4:
                    cur = float(vals[3]) if vals[3] else 0
                    prev = float(vals[2]) if vals[2] else 0
                    if cur > 0 and prev > 0:
                        result[code] = round((cur - prev) / prev * 100, 3)
        except Exception:
            pass

    return result


def fetch_hk_us_prices(codes: list) -> dict:
    """获取港美股涨跌幅（Yahoo Finance），返回 {code: change_pct}"""
    result = {}
    for code in codes:
        # 判断是港股还是美股
        symbol = None
        if code.startswith('0') and len(code) <= 5:
            symbol = f"{code.zfill(4)}.HK"
        elif code.isalpha():
            symbol = code.upper()
        else:
            # 尝试作为港股
            symbol = f"{code.zfill(4)}.HK"

        if not symbol:
            continue

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            meta = data["chart"]["result"][0]["meta"]
            cur = meta["regularMarketPrice"]
            prev = meta.get("previousClose") or meta.get("chartPreviousClose", cur)
            if prev > 0:
                result[code] = round((cur - prev) / prev * 100, 3)
            time.sleep(0.3)
        except Exception:
            pass

    return result


# ════════════════════════════════════════════════════════════
#  NAV 获取
# ════════════════════════════════════════════════════════════

def fetch_nav(fund_code: str) -> tuple:
    """获取基金NAV，返回 (nav, nav_change_pct)"""
    # P1: fundgz（盘中估值）
    url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js?rt={int(time.time())}"
    try:
        raw = _urlget(url)
        m = re.search(r'jsonpgz\((.+)\)', raw)
        if m and 'dwjz' in m.group(1):
            d = json.loads(m.group(1))
            return float(d['dwjz']), float(d.get('gszzl', 0))
    except Exception:
        pass

    # P2: lsjz（QDII/港美股基金）
    url2 = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex=1&pageSize=1"
    try:
        raw = _urlget(url2)
        data = json.loads(raw)
        items = data.get('Data', {}).get('LSJZList', [])
        if items:
            return float(items[0]['DWJZ']), float(items[0].get('JZZZL', 0))
    except Exception:
        pass

    return None, None


# ════════════════════════════════════════════════════════════
#  穿透盈亏计算
# ════════════════════════════════════════════════════════════

def calculate_penetration(funds: dict, target_fund: str = None, json_output: bool = False):
    """计算所有基金的穿透盈亏"""
    cache = _load_cache()
    if not cache or all(k.startswith("_") for k in cache):
        print("⚠️ 无重仓股缓存数据，请先运行: python3 fund_penetration.py --update")
        return

    funds_to_calc = {target_fund: funds[target_fund]} if target_fund else funds

    # Step 1: 获取所有基金 NAV
    print(f"📥 获取NAV...") if not json_output else None
    fund_navs = {}
    for fid in funds_to_calc:
        nav, nav_chg = fetch_nav(fid)
        fund_navs[fid] = (nav, nav_chg)

    # Step 2: 收集所有需要查价的股票代码
    all_a_codes = set()
    all_hk_us_codes = set()
    for fid in funds_to_calc:
        fdata = cache.get(fid, {})
        for h in fdata.get("holdings", []):
            code = h["code"]
            # 判断市场
            if code.startswith(('6', '0', '3', '688', '15', '16')):
                all_a_codes.add(code)
            else:
                all_hk_us_codes.add(code)

    # Step 3: 批量获取价格
    print(f"📥 获取价格（A股{len(all_a_codes)}只 + 港美股{len(all_hk_us_codes)}只）...") if not json_output else None
    a_prices = fetch_a_prices(list(all_a_codes))
    hk_us_prices = fetch_hk_us_prices(list(all_hk_us_codes)) if all_hk_us_codes else {}
    all_prices = {**a_prices, **hk_us_prices}
    print(f"  成功获取: {len(all_prices)}/{len(all_a_codes) + len(all_hk_us_codes)}") if not json_output else None

    # Step 4: 逐基金计算
    fund_results = {}
    grand_total = 0

    for fid, info in funds_to_calc.items():
        A = info["shares"]
        nav, nav_chg = fund_navs.get(fid, (None, None))
        fdata = cache.get(fid, {})
        c1 = fdata.get("c1", 0)
        holdings = fdata.get("holdings", [])

        if nav is None:
            fund_results[fid] = {"name": info["name"], "error": "NAV获取失败", "pnl": 0}
            continue
        if not holdings:
            fund_results[fid] = {"name": info["name"], "error": "无重仓股数据", "pnl": 0}
            continue
        if c1 == 0:
            # 没有C1数据，用默认90%（主动型基金通常80-95%）
            c1 = 90.0

        AB = A * nav  # 持仓市值
        rows = []
        for h in holdings:
            E1 = all_prices.get(h["code"], 0)
            D1 = h["pct"]
            my_mv = AB * (c1 / 100) * (D1 / 100)
            pnl = my_mv * E1 / 100
            rows.append({
                "code": h["code"],
                "name": h["name"],
                "D1": D1,
                "my_mv": round(my_mv, 0),
                "E1": E1,
                "pnl": round(pnl, 0),
            })

        total_pnl = sum(r["pnl"] for r in rows)
        grand_total += total_pnl

        fund_results[fid] = {
            "name": info["name"],
            "A": A,
            "B": nav,
            "nav_chg": nav_chg,
            "C1": c1,
            "AB": round(AB, 0),
            "period": fdata.get("period", "?"),
            "rows": sorted(rows, key=lambda x: -x["pnl"]),
            "pnl": round(total_pnl, 0),
        }

    # Step 5: 汇总个股（跨基金合并）
    stock_agg = {}
    for fid, res in fund_results.items():
        for r in res.get("rows", []):
            c = r["code"]
            if c not in stock_agg:
                stock_agg[c] = {"code": c, "name": r["name"], "my_mv": 0, "E1": r["E1"], "pnl": 0, "funds": []}
            stock_agg[c]["my_mv"] += r["my_mv"]
            stock_agg[c]["pnl"] += r["pnl"]
            stock_agg[c]["funds"].append(fid)

    # 输出
    if json_output:
        out = {
            "timestamp": datetime.now().isoformat(),
            "grand_total": round(grand_total, 0),
            "funds": {fid: {k: v for k, v in res.items() if k != "rows"} for fid, res in fund_results.items()},
            "fund_details": fund_results,
            "stock_summary": dict(sorted(stock_agg.items(), key=lambda x: -x[1]["pnl"])),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        _print_report(fund_results, stock_agg, grand_total)


def _print_report(fund_results: dict, stock_agg: dict, grand_total: float):
    """打印穿透报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'═'*70}")
    print(f"  📊 基金穿透盈亏 | {now}")
    print(f"  公式: 占用资金 = A×B×C1%×D1% → 盈亏 = 占用资金×E1%")
    print(f"{'═'*70}")

    for fid, res in fund_results.items():
        if "error" in res:
            print(f"\n  ⚠️ {res['name']}({fid}): {res['error']}")
            continue

        pnl_emoji = "🟢" if res["pnl"] >= 0 else "🔴"
        print(f"\n  【{res['name']}】{res.get('period','')} | NAV={res['B']} ({res.get('nav_chg',0):+.2f}%)")
        print(f"  A={res['A']:,.0f}份 C1={res['C1']:.1f}% → 市值={res['AB']:,.0f}元 → {pnl_emoji}{res['pnl']:+,.0f}元")
        print(f"  {'代码':<8}{'名称':<10}{'D1%':>6}{'占用资金':>10}{'E1涨跌':>8}{'盈亏':>9}")
        print(f"  {'─'*52}")

        for r in res.get("rows", []):
            flag = "🔴" if r["E1"] < -2 else ("🟢" if r["E1"] > 2 else "  ")
            print(f"  {r['code']:<8}{r['name']:<10}{r['D1']:>5.2f}%"
                  f"{r['my_mv']:>10,.0f}{r['E1']:>+7.2f}%{r['pnl']:>+8,.0f}元{flag}")

    # 跨基金重叠股
    overlaps = {k: v for k, v in stock_agg.items() if len(v["funds"]) > 1}
    if overlaps:
        print(f"\n{'─'*70}")
        print(f"  🔗 跨基金重叠股（影响放大）:")
        for code, s in sorted(overlaps.items(), key=lambda x: -abs(x[1]["pnl"])):
            print(f"  {s['name']}({code}) 占用{s['my_mv']:,.0f}元 "
                  f"E1={s['E1']:+.2f}% 合计{s['pnl']:+,.0f}元 "
                  f"[{len(s['funds'])}只基金持有]")

    # TOP5 贡献/拖累
    sorted_stocks = sorted(stock_agg.values(), key=lambda x: -x["pnl"])
    if sorted_stocks:
        print(f"\n{'─'*70}")
        print(f"  📈 TOP3贡献: ", end="")
        for s in sorted_stocks[:3]:
            print(f"{s['name']}({s['pnl']:+,.0f}) ", end="")
        print(f"\n  📉 TOP3拖累: ", end="")
        for s in sorted_stocks[-3:]:
            print(f"{s['name']}({s['pnl']:+,.0f}) ", end="")

    print(f"\n\n{'═'*70}")
    emoji = "💰" if grand_total >= 0 else "💸"
    print(f"  {emoji} 穿透合计: {grand_total:>+,.0f}元")
    print(f"  ⚠️ 估算数据，基于最新季报持仓比例，实际以账户为准")
    print(f"{'═'*70}\n")


# ════════════════════════════════════════════════════════════
#  命令行入口
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='基金穿透盈亏计算')
    parser.add_argument('--update', action='store_true', help='抓取最新季报重仓股（季报发布后运行）')
    parser.add_argument('--fund', type=str, help='只处理单只基金')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    args = parser.parse_args()

    funds = load_funds()
    if not funds:
        print("❌ 无法加载 holdings.json 或无基金持仓")
        sys.exit(1)

    if args.fund and args.fund not in funds:
        print(f"❌ 基金 {args.fund} 不在 holdings.json 中")
        sys.exit(1)

    if args.update:
        update_all_holdings(funds, target_fund=args.fund)
    else:
        calculate_penetration(funds, target_fund=args.fund, json_output=args.json)


if __name__ == "__main__":
    main()
