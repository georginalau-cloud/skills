#!/usr/bin/env python3
"""
A股持仓行情查询脚本
数据来源：4级 fallback（push2东方财富 → 腾讯 → akshare → 新浪）
持仓数据：从 workspace-zhaocai/holdings.json 统一读取
"""
import json
import os
import sys
import requests
from datetime import datetime
from pathlib import Path

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
})

# ── 持仓数据加载 ──────────────────────────────────────────────
WORKSPACE = Path(__file__).resolve().parent.parent
HOLDINGS_FILE = WORKSPACE / "holdings.json"

# 尝试加载 shared/price_fetcher.py
sys.path.insert(0, str(WORKSPACE / "skills" / "shared"))
try:
    from price_fetcher import fetch_a_stock_prices
    HAS_PRICE_FETCHER = True
except ImportError:
    HAS_PRICE_FETCHER = False


def load_holdings() -> dict:
    """从 holdings.json 加载持仓数据，返回 {code_with_prefix: {name, qty, cost}}"""
    if not HOLDINGS_FILE.exists():
        print(f"❌ 持仓文件不存在：{HOLDINGS_FILE}")
        sys.exit(1)

    with open(HOLDINGS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    holdings = {}

    # 个股
    for code, info in data.get("stocks", {}).items():
        prefix = "sh" if code.startswith(("6", "5")) else "sz"
        holdings[f"{prefix}{code}"] = {
            "name": info["name"],
            "qty": info["shares"],
            "cost": info["cost"],
        }

    # 场内 ETF
    for code, info in data.get("etfs", {}).items():
        prefix = "sh" if code.startswith(("5", "6")) else "sz"
        # 特殊处理：400xxx 是三板
        if code.startswith("4"):
            prefix = "sh"
        holdings[f"{prefix}{code}"] = {
            "name": info["name"],
            "qty": info["shares"],
            "cost": info["cost"],
        }

    return holdings


# ── 行情获取（新浪兜底） ──────────────────────────────────────
SINA_URL = "https://hq.sinajs.cn/list="


def fetch_prices_sina(codes_str: str) -> dict:
    """批量获取新浪行情，返回 {code: {name, current, prev_close}}"""
    r = SESSION.get(SINA_URL + codes_str, timeout=15)
    r.encoding = 'gbk'
    result = {}
    for line in r.text.strip().split('\n'):
        if '=' not in line or len(line.split('"')) < 2:
            continue
        raw_code = line.split('=')[0].split('_')[-1]
        data = line.split('"')[1]
        fields = data.split(',')
        if len(fields) < 4 or not fields[0]:
            continue
        result[raw_code] = {
            "name": fields[0],
            "current": float(fields[3]),
            "prev_close": float(fields[2]),
        }
    return result


def main():
    holdings = load_holdings()
    codes_str = ",".join(holdings.keys())

    # 尝试使用 price_fetcher（4级 fallback），失败则回退到新浪
    prices = {}
    if HAS_PRICE_FETCHER:
        try:
            # price_fetcher 接受不带前缀的代码列表
            raw_codes = [k[2:] for k in holdings.keys()]
            prices_raw = fetch_a_stock_prices(raw_codes)
            # 转换为本脚本格式
            for code_with_prefix in holdings.keys():
                raw_code = code_with_prefix[2:]
                if raw_code in prices_raw:
                    p = prices_raw[raw_code]
                    prices[code_with_prefix] = {
                        "name": p.get("name", holdings[code_with_prefix]["name"]),
                        "current": p["current"],
                        "prev_close": p["prev_close"],
                    }
        except Exception as e:
            print(f"⚠️ price_fetcher 失败，回退到新浪：{e}")
            prices = {}

    if not prices:
        prices = fetch_prices_sina(codes_str)

    print(f"📊 持仓快照 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    total_pl = 0
    for code_key, info in holdings.items():
        if code_key not in prices:
            print(f"❌ {info['name']}({code_key}): 数据不可用")
            continue
        p = prices[code_key]
        current = p['current']
        if current == 0 or p['prev_close'] == 0:
            print(f"⚠️ {info['name']}({code_key}): 停牌或无数据")
            continue
        pct = (current - p['prev_close']) / p['prev_close'] * 100
        pl = (current - info['cost']) * info['qty']
        total_pl += pl
        emoji = "📈" if pl >= 0 else "📉"
        print(f"{emoji} {info['name']}: 现价={current:.3f} {pct:+.2f}% | 浮盈{pl:+,.0f}")

    print("=" * 55)
    emoji = "💰" if total_pl >= 0 else "💸"
    print(f"{emoji} 合计浮盈: {total_pl:+,.0f} 元")


if __name__ == "__main__":
    main()
