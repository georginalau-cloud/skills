#!/usr/bin/env python3
"""
close_report.py — 收盘总结数据（一次性输出，LLM只需排版）
15:30收盘后运行，输出完整的收盘数据JSON。
LLM禁止修改任何数字，只负责润色和排版。

用法：
    python3 close_report.py          # 人类可读格式
    python3 close_report.py --json   # JSON输出（供agent调用）

输出包含：
  1. 大盘指数（上证/深证/创业板/科创50）
  2. 个股逐项盈亏（9只）
  3. ETF逐项盈亏（4只）
  4. 基金穿透盈亏（25只）
  5. 汇总（今日总盈亏、累计浮盈）
"""

import json
import sys
import re
import time
import argparse
import urllib.request
import ssl
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
HOLDINGS_PATH = WORKSPACE / "holdings.json"
CACHE_PATH = WORKSPACE / "scripts" / "fund_holdings_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
}

_OPENER = None
def _get_opener():
    global _OPENER
    if _OPENER is None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ctx)
        )
    return _OPENER

def _urlget(url, timeout=12, encoding='utf-8'):
    req = urllib.request.Request(url, headers=HEADERS)
    with _get_opener().open(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors='replace')


# ════════════════════════════════════════════════════════════
#  大盘指数
# ════════════════════════════════════════════════════════════

def fetch_indexes() -> list:
    symbols = "s_sh000001,s_sz399001,s_sz399006,s_sh000688"
    url = f"https://hq.sinajs.cn/list={symbols}"
    names = {"s_sh000001": "上证指数", "s_sz399001": "深证成指",
             "s_sz399006": "创业板指", "s_sh000688": "科创50"}
    results = []
    try:
        raw = _urlget(url, encoding='gbk')
        for sym, name in names.items():
            m = re.search(rf'hq_str_{re.escape(sym)}="([^"]*)"', raw)
            if m:
                parts = m.group(1).split(',')
                if len(parts) >= 4:
                    results.append({
                        "name": name,
                        "current": float(parts[1]),
                        "change": float(parts[2]),
                        "change_pct": float(parts[3]),
                    })
    except Exception:
        pass
    return results


# ════════════════════════════════════════════════════════════
#  持仓行情（个股+ETF）
# ════════════════════════════════════════════════════════════

def fetch_holdings_prices(holdings: dict) -> dict:
    """获取所有个股+ETF的收盘价"""
    all_codes = list(holdings.get("stocks", {}).keys()) + list(holdings.get("etfs", {}).keys())

    secids = []
    for c in all_codes:
        if c.startswith(('6', '688', '5')):
            secids.append(f"1.{c}")
        else:
            secids.append(f"0.{c}")

    result = {}
    BATCH = 80
    for i in range(0, len(secids), BATCH):
        batch = secids[i:i+BATCH]
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&invt=2&fields=f2,f3,f4,f12,f14,f18&secids={','.join(batch)}")
        try:
            raw = _urlget(url)
            data = json.loads(raw)
            for item in data.get('data', {}).get('diff', []):
                code = str(item.get('f12', '')).zfill(6)
                result[code] = {
                    "price": item.get('f2'),
                    "change_pct": item.get('f3'),
                    "change_amount": item.get('f4'),
                    "prev_close": item.get('f18'),
                }
        except Exception:
            pass

    return result


def build_stock_report(holdings: dict, prices: dict) -> list:
    """构建个股盈亏报告"""
    results = []
    for code, info in holdings.get("stocks", {}).items():
        p = prices.get(code, {})
        price = p.get("price", 0)
        prev = p.get("prev_close", 0)
        chg_pct = p.get("change_pct", 0)
        if not price:
            results.append({"code": code, "name": info["name"], "error": "无数据"})
            continue
        today_pnl = round((price - prev) * info["shares"], 0) if prev else 0
        total_pnl = round((price - info["cost"]) * info["shares"], 0)
        total_pnl_pct = round((price - info["cost"]) / info["cost"] * 100, 2) if info["cost"] else 0
        results.append({
            "code": code,
            "name": info["name"],
            "price": price,
            "change_pct": chg_pct,
            "shares": info["shares"],
            "cost": info["cost"],
            "today_pnl": today_pnl,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
        })
    results.sort(key=lambda x: x.get("today_pnl", 0), reverse=True)
    return results


def build_etf_report(holdings: dict, prices: dict) -> list:
    """构建ETF盈亏报告"""
    results = []
    for code, info in holdings.get("etfs", {}).items():
        p = prices.get(code, {})
        price = p.get("price", 0)
        prev = p.get("prev_close", 0)
        chg_pct = p.get("change_pct", 0)
        if not price:
            results.append({"code": code, "name": info["name"], "error": "无数据"})
            continue
        today_pnl = round((price - prev) * info["shares"], 0) if prev else 0
        total_pnl = round((price - info["cost"]) * info["shares"], 0)
        total_pnl_pct = round((price - info["cost"]) / info["cost"] * 100, 2) if info["cost"] else 0
        results.append({
            "code": code,
            "name": info["name"],
            "price": price,
            "change_pct": chg_pct,
            "shares": info["shares"],
            "cost": info["cost"],
            "today_pnl": today_pnl,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
        })
    results.sort(key=lambda x: x.get("today_pnl", 0), reverse=True)
    return results


# ════════════════════════════════════════════════════════════
#  基金穿透
# ════════════════════════════════════════════════════════════

def build_fund_report(holdings: dict) -> dict:
    """基金穿透盈亏（调用 fund_penetration.py 的逻辑）"""
    # 直接导入 fund_penetration 的函数
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from fund_penetration import load_funds, fetch_nav, _load_cache, fetch_a_prices, _secid
    except ImportError:
        return {"error": "fund_penetration.py 导入失败"}

    funds = load_funds()
    cache = _load_cache()

    if not cache or all(k.startswith("_") for k in cache):
        return {"error": "无重仓股缓存，请先运行 fund_penetration.py --update"}

    # 获取所有基金NAV
    fund_results = []
    grand_total = 0

    for fid, info in funds.items():
        nav, nav_chg = fetch_nav(fid)
        if nav is None:
            fund_results.append({"code": fid, "name": info["name"], "nav": None, "pnl": 0, "error": "NAV获取失败"})
            continue

        fdata = cache.get(fid, {})
        c1 = fdata.get("c1", 90.0)
        fund_holdings = fdata.get("holdings", [])
        AB = info["shares"] * nav

        if not fund_holdings:
            # 没有穿透数据，只报NAV变动
            pnl_est = round(AB * nav_chg / 100, 0) if nav_chg else 0
            fund_results.append({
                "code": fid, "name": info["name"],
                "nav": nav, "nav_chg": nav_chg,
                "shares": info["shares"], "mv": round(AB, 0),
                "pnl": pnl_est, "method": "nav_change",
            })
            grand_total += pnl_est
            continue

        # 有穿透数据，用穿透计算
        all_codes = [h["code"] for h in fund_holdings if h["code"].startswith(('6','0','3','688','15','16'))]
        prices = fetch_a_prices(all_codes) if all_codes else {}

        total_pnl = 0
        for h in fund_holdings:
            E1 = prices.get(h["code"], 0)
            my_mv = AB * (c1 / 100) * (h["pct"] / 100)
            pnl = my_mv * E1 / 100
            total_pnl += pnl

        fund_results.append({
            "code": fid, "name": info["name"],
            "nav": nav, "nav_chg": nav_chg,
            "shares": info["shares"], "mv": round(AB, 0),
            "pnl": round(total_pnl, 0), "method": "penetration",
        })
        grand_total += total_pnl

    return {"funds": fund_results, "grand_total": round(grand_total, 0)}


# ════════════════════════════════════════════════════════════
#  汇总
# ════════════════════════════════════════════════════════════

def build_full_report() -> dict:
    """构建完整收盘报告"""
    holdings = json.load(open(HOLDINGS_PATH, encoding='utf-8'))

    # 大盘
    indexes = fetch_indexes()

    # 个股+ETF
    prices = fetch_holdings_prices(holdings)
    stocks = build_stock_report(holdings, prices)
    etfs = build_etf_report(holdings, prices)

    # 基金
    fund_report = build_fund_report(holdings)

    # 汇总
    stock_today = sum(s.get("today_pnl", 0) for s in stocks if "error" not in s)
    etf_today = sum(e.get("today_pnl", 0) for e in etfs if "error" not in e)
    fund_today = fund_report.get("grand_total", 0) if isinstance(fund_report, dict) else 0

    stock_total = sum(s.get("total_pnl", 0) for s in stocks if "error" not in s)
    etf_total = sum(e.get("total_pnl", 0) for e in etfs if "error" not in e)

    total_today = stock_today + etf_today + fund_today
    total_accumulated = stock_total + etf_total  # 基金累计浮盈需要另算

    return {
        "_meta": {
            "generated_at": datetime.now().isoformat(),
            "source": "close_report.py",
            "note": "所有数字来自API，LLM禁止修改",
        },
        "indexes": indexes,
        "stocks": stocks,
        "etfs": etfs,
        "funds": fund_report,
        "summary": {
            "today_pnl_stocks": stock_today,
            "today_pnl_etfs": etf_today,
            "today_pnl_funds": fund_today,
            "today_pnl_total": total_today,
            "total_pnl_stocks_etfs": stock_total + etf_total,
        },
    }


# ════════════════════════════════════════════════════════════
#  输出
# ════════════════════════════════════════════════════════════

def print_report(data: dict):
    """人类可读格式"""
    print(f"\n{'═'*60}")
    print(f"  📊 收盘总结 | {data['_meta']['generated_at'][:16]}")
    print(f"{'═'*60}")

    # 指数
    print(f"\n  【大盘指数】")
    for idx in data.get("indexes", []):
        emoji = "🟢" if idx["change_pct"] > 0 else "🔴"
        print(f"  {emoji} {idx['name']}: {idx['current']:,.2f} ({idx['change_pct']:+.2f}%)")

    # 个股
    print(f"\n  【个股（{len(data['stocks'])}只）】")
    for s in data["stocks"]:
        if "error" in s:
            print(f"  ❌ {s['name']}: {s['error']}")
            continue
        emoji = "🟢" if s["change_pct"] > 0 else ("🔴" if s["change_pct"] < 0 else "⚪")
        print(f"  {emoji} {s['name']:<8} ¥{s['price']:.2f} {s['change_pct']:+.2f}%"
              f" | 今日{s['today_pnl']:+,.0f} | 总{s['total_pnl']:+,.0f}({s['total_pnl_pct']:+.1f}%)")

    # ETF
    print(f"\n  【ETF（{len(data['etfs'])}只）】")
    for e in data["etfs"]:
        if "error" in e:
            print(f"  ❌ {e['name']}: {e['error']}")
            continue
        emoji = "🟢" if e["change_pct"] > 0 else ("🔴" if e["change_pct"] < 0 else "⚪")
        print(f"  {emoji} {e['name']:<12} ¥{e['price']:.3f} {e['change_pct']:+.2f}%"
              f" | 今日{e['today_pnl']:+,.0f} | 总{e['total_pnl']:+,.0f}({e['total_pnl_pct']:+.1f}%)")

    # 基金
    fr = data.get("funds", {})
    if "error" in fr:
        print(f"\n  【基金】⚠️ {fr['error']}")
    else:
        print(f"\n  【基金穿透（{len(fr.get('funds',[]))}只）】")
        for f in sorted(fr.get("funds", []), key=lambda x: -x.get("pnl", 0)):
            if f.get("error"):
                print(f"  ⚠️ {f['name']}: {f['error']}")
                continue
            emoji = "🟢" if f["pnl"] > 0 else ("🔴" if f["pnl"] < 0 else "⚪")
            method = "穿透" if f.get("method") == "penetration" else "估值"
            print(f"  {emoji} {f['name']:<12} NAV={f['nav']:.4f}({f.get('nav_chg',0):+.2f}%)"
                  f" | 今日{f['pnl']:+,.0f}元 [{method}]")
        print(f"  基金合计: {fr.get('grand_total',0):+,.0f}元")

    # 汇总
    s = data["summary"]
    print(f"\n{'─'*60}")
    print(f"  💰 今日盈亏：")
    print(f"     个股: {s['today_pnl_stocks']:+,.0f}")
    print(f"     ETF:  {s['today_pnl_etfs']:+,.0f}")
    print(f"     基金: {s['today_pnl_funds']:+,.0f}")
    print(f"     ────────────")
    total = s['today_pnl_total']
    emoji = "💰" if total >= 0 else "💸"
    print(f"  {emoji} 合计: {total:+,.0f}元")
    print(f"\n  📊 个股+ETF累计浮盈: {s['total_pnl_stocks_etfs']:+,.0f}元")
    print(f"{'═'*60}\n")


def main():
    parser = argparse.ArgumentParser(description='收盘总结数据')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    args = parser.parse_args()

    data = build_full_report()

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_report(data)


if __name__ == "__main__":
    main()
