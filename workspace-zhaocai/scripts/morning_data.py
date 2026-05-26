#!/usr/bin/env python3
"""
morning_data.py — 晨报数据采集脚本
盘前运行（08:30），采集所有晨报需要的数据，输出结构化 JSON。
LLM 只能基于此 JSON 写报告，禁止编造任何数字。

用法：
    python3 morning_data.py              # 完整晨报数据
    python3 morning_data.py --json       # 纯JSON（供agent调用）
    python3 morning_data.py --section macro   # 只跑宏观部分

输出包含：
  1. 持仓快照（昨收价、盈亏、仓位占比）
  2. 隔夜美股/港股
  3. 外汇（USD/CNY、NZD相关）
  4. 持仓个股技术面快照（均线、MACD、RSI）
"""

import json
import sys
import time
import re
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
HOLDINGS_PATH = WORKSPACE / "holdings.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
}

_OPENER = None
def _get_opener():
    global _OPENER
    if _OPENER is None:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        https_handler = urllib.request.HTTPSHandler(context=ctx)
        proxy_handler = urllib.request.ProxyHandler({})
        _OPENER = urllib.request.build_opener(proxy_handler, https_handler)
    return _OPENER

def _urlget(url, timeout=10, encoding='utf-8'):
    req = urllib.request.Request(url, headers=HEADERS)
    with _get_opener().open(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors='replace')


# ════════════════════════════════════════════════════════════
#  持仓数据
# ════════════════════════════════════════════════════════════

def load_holdings():
    with open(HOLDINGS_PATH, encoding='utf-8') as f:
        return json.load(f)


def fetch_stock_snapshot(codes: list) -> dict:
    """获取个股/ETF昨收+最新价（盘前=昨收）"""
    secids = []
    for c in codes:
        if c.startswith(('6', '688', '5')):
            secids.append(f"1.{c}")
        else:
            secids.append(f"0.{c}")

    result = {}
    BATCH = 80
    for i in range(0, len(secids), BATCH):
        batch = secids[i:i+BATCH]
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&invt=2&fields=f2,f3,f4,f12,f14,f15,f16,f17,f18&secids={','.join(batch)}")
        try:
            raw = _urlget(url)
            data = json.loads(raw)
            for item in data.get('data', {}).get('diff', []):
                code = str(item.get('f12', '')).zfill(6)
                result[code] = {
                    "name": item.get('f14', ''),
                    "price": item.get('f2'),       # 最新价（盘前=昨收）
                    "change_pct": item.get('f3'),   # 涨跌幅
                    "high": item.get('f15'),
                    "low": item.get('f16'),
                    "open": item.get('f17'),
                    "prev_close": item.get('f18'),
                }
        except Exception as e:
            print(f"  ⚠️ push2获取失败: {e}", file=sys.stderr)

    return result


def build_portfolio_snapshot(holdings: dict, prices: dict) -> dict:
    """构建持仓快照"""
    snapshot = {"stocks": [], "etfs": [], "total_mv": 0, "total_cost": 0, "total_pnl": 0}

    for code, info in holdings.get("stocks", {}).items():
        p = prices.get(code, {})
        price = p.get("price") or p.get("prev_close") or 0
        if not price:
            continue
        mv = price * info["shares"]
        cost_total = info["cost"] * info["shares"]
        pnl = mv - cost_total
        snapshot["stocks"].append({
            "code": code, "name": info["name"],
            "price": price, "shares": info["shares"], "cost": info["cost"],
            "mv": round(mv, 0), "pnl": round(pnl, 0),
            "pnl_pct": round(pnl / cost_total * 100, 2) if cost_total else 0,
        })
        snapshot["total_mv"] += mv
        snapshot["total_cost"] += cost_total

    for code, info in holdings.get("etfs", {}).items():
        p = prices.get(code, {})
        price = p.get("price") or p.get("prev_close") or 0
        if not price:
            continue
        mv = price * info["shares"]
        cost_total = info["cost"] * info["shares"]
        pnl = mv - cost_total
        snapshot["etfs"].append({
            "code": code, "name": info["name"],
            "price": price, "shares": info["shares"], "cost": info["cost"],
            "mv": round(mv, 0), "pnl": round(pnl, 0),
            "pnl_pct": round(pnl / cost_total * 100, 2) if cost_total else 0,
        })
        snapshot["total_mv"] += mv
        snapshot["total_cost"] += cost_total

    snapshot["total_pnl"] = round(snapshot["total_mv"] - snapshot["total_cost"], 0)
    snapshot["total_pnl_pct"] = round(snapshot["total_pnl"] / snapshot["total_cost"] * 100, 2) if snapshot["total_cost"] else 0
    snapshot["total_mv"] = round(snapshot["total_mv"], 0)
    return snapshot


# ════════════════════════════════════════════════════════════
#  隔夜美股
# ════════════════════════════════════════════════════════════

def fetch_us_indexes() -> dict:
    """获取美股三大指数（新浪）"""
    symbols = "int_dji,int_nasdaq,int_sp500"
    url = f"https://hq.sinajs.cn/list={symbols}"
    result = {}
    try:
        raw = _urlget(url, encoding='gbk')
        # 格式: var hq_str_int_dji="道琼斯,46247.29,299.97,0.65";
        for line in raw.strip().split('\n'):
            if '=""' in line:
                continue
            m = re.search(r'hq_str_(int_\w+)="([^"]*)"', line)
            if not m:
                continue
            sym = m.group(1)
            parts = m.group(2).split(',')
            if len(parts) >= 4:
                names = {"int_dji": "道琼斯", "int_nasdaq": "纳斯达克", "int_sp500": "标普500"}
                name = names.get(sym, parts[0])
                try:
                    result[name] = {
                        "current": float(parts[1]),
                        "change": float(parts[2]),
                        "change_pct": float(parts[3]),
                    }
                except ValueError:
                    pass
    except Exception:
        pass
    return result


# ════════════════════════════════════════════════════════════
#  外汇
# ════════════════════════════════════════════════════════════

def fetch_forex() -> dict:
    """获取主要汇率"""
    # 新浪外汇接口用小写代码
    pairs = {
        "fx_susdcny": "美元/人民币",
        "fx_snzdcny": "纽元/人民币",
        "fx_snzdusd": "纽元/美元",
        "fx_shkdcny": "港币/人民币",
    }
    symbols = ",".join(pairs.keys())
    url = f"https://hq.sinajs.cn/list={symbols}"
    result = {}
    try:
        raw = _urlget(url, encoding='gbk')
        for line in raw.strip().split('\n'):
            if '=""' in line:
                continue
            m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
            if not m:
                continue
            sym = m.group(1)
            name = pairs.get(sym, sym)
            parts = m.group(2).split(',')
            # 格式: 时间,买入价,卖出价,最低价,... 或 时间,现价,买入,卖出,...
            if len(parts) >= 4:
                try:
                    # 取第二个字段作为当前汇率
                    rate = float(parts[1])
                    result[name] = {
                        "pair": sym.replace("fx_s", "").upper(),
                        "rate": rate,
                    }
                except ValueError:
                    pass
    except Exception:
        pass
    return result


# ════════════════════════════════════════════════════════════
#  A股大盘指数
# ════════════════════════════════════════════════════════════

def fetch_a_indexes() -> dict:
    """获取A股主要指数（昨收）"""
    symbols = "s_sh000001,s_sz399001,s_sz399006"
    url = f"https://hq.sinajs.cn/list={symbols}"
    result = {}
    names = {"s_sh000001": "上证指数", "s_sz399001": "深证成指", "s_sz399006": "创业板指"}
    try:
        raw = _urlget(url, encoding='gbk')
        for sym, name in names.items():
            pattern = rf'hq_str_{re.escape(sym)}="([^"]*)"'
            m = re.search(pattern, raw)
            if m:
                parts = m.group(1).split(',')
                if len(parts) >= 4:
                    result[name] = {
                        "current": float(parts[1]),
                        "change": float(parts[2]),
                        "change_pct": float(parts[3]),
                    }
    except Exception:
        pass
    return result


# ════════════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════════════

def collect_all() -> dict:
    """采集所有晨报数据"""
    holdings = load_holdings()

    # 持仓代码
    stock_codes = list(holdings.get("stocks", {}).keys())
    etf_codes = list(holdings.get("etfs", {}).keys())
    all_codes = stock_codes + etf_codes

    print("📥 采集持仓价格...", file=sys.stderr)
    prices = fetch_stock_snapshot(all_codes)

    print("📥 采集美股指数...", file=sys.stderr)
    us_indexes = fetch_us_indexes()

    print("📥 采集外汇...", file=sys.stderr)
    forex = fetch_forex()

    print("📥 采集A股指数...", file=sys.stderr)
    a_indexes = fetch_a_indexes()

    # 构建持仓快照
    portfolio = build_portfolio_snapshot(holdings, prices)

    return {
        "_meta": {
            "generated_at": datetime.now().isoformat(),
            "source": "morning_data.py",
            "note": "所有数字来自实时API，LLM禁止修改任何数值",
        },
        "a_indexes": a_indexes,
        "us_indexes": us_indexes,
        "forex": forex,
        "portfolio": portfolio,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description='晨报数据采集')
    parser.add_argument('--json', action='store_true', help='纯JSON输出')
    parser.add_argument('--section', choices=['macro', 'portfolio', 'all'], default='all')
    args = parser.parse_args()

    data = collect_all()

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        # 人类可读格式
        print(f"\n{'═'*60}")
        print(f"  📊 晨报数据采集 | {data['_meta']['generated_at'][:16]}")
        print(f"{'═'*60}")

        # A股指数
        print(f"\n  【A股指数（昨收）】")
        for name, d in data.get("a_indexes", {}).items():
            print(f"  {name}: {d['current']:,.2f} ({d['change_pct']:+.2f}%)")

        # 美股
        print(f"\n  【隔夜美股】")
        for name, d in data.get("us_indexes", {}).items():
            print(f"  {name}: {d['current']:,.2f} ({d['change_pct']:+.2f}%)")

        # 外汇
        print(f"\n  【外汇】")
        for name, d in data.get("forex", {}).items():
            print(f"  {name}: {d['rate']:.4f}")

        # 持仓
        p = data["portfolio"]
        print(f"\n  【持仓快照】")
        print(f"  总市值: ¥{p['total_mv']:,.0f}")
        print(f"  累计浮盈: ¥{p['total_pnl']:+,.0f} ({p['total_pnl_pct']:+.2f}%)")
        print(f"\n  个股({len(p['stocks'])}只):")
        for s in sorted(p['stocks'], key=lambda x: -x['pnl']):
            print(f"    {s['name']:<8} ¥{s['price']:.3f} | 浮盈¥{s['pnl']:+,.0f}({s['pnl_pct']:+.1f}%)")
        print(f"\n  ETF({len(p['etfs'])}只):")
        for s in sorted(p['etfs'], key=lambda x: -x['pnl']):
            print(f"    {s['name']:<12} ¥{s['price']:.3f} | 浮盈¥{s['pnl']:+,.0f}({s['pnl_pct']:+.1f}%)")

        print(f"\n{'═'*60}")
        print(f"  ⚠️ 以上数据来自API实时采集，LLM报告中的数字必须与此一致")
        print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
