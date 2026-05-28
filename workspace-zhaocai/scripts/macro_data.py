#!/usr/bin/env python3
"""
macro_data.py — 宏观数据采集（补充晨报的数字部分）
采集美股、大宗商品、北向资金、美元指数等宏观数据。
LLM 用这些数字写宏观环境分析，禁止编造。

用法：
    python3 macro_data.py           # 人类可读
    python3 macro_data.py --json    # JSON输出

数据源：
  - 美股三大指数：新浪（int_dji/int_nasdaq/int_sp500）
  - 大宗商品：新浪期货（黄金/原油/铜）
  - 美元指数：新浪（hf_DINIW）
  - 北向资金：东方财富 push2
  - 外汇：新浪（fx_susdcny/fx_snzdcny）
"""

import json
import sys
import re
import urllib.request
import ssl
import argparse
from datetime import datetime

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

def _urlget(url, timeout=10, encoding='utf-8'):
    req = urllib.request.Request(url, headers=HEADERS)
    with _get_opener().open(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors='replace')


# ════════════════════════════════════════════════════════════

def fetch_us_indexes() -> dict:
    """美股三大指数"""
    url = "https://hq.sinajs.cn/list=int_dji,int_nasdaq,int_sp500"
    result = {}
    try:
        raw = _urlget(url, encoding='gbk')
        for line in raw.strip().split('\n'):
            if '=""' in line:
                continue
            m = re.search(r'hq_str_(int_\w+)="([^"]*)"', line)
            if not m:
                continue
            parts = m.group(2).split(',')
            if len(parts) >= 4:
                names = {"int_dji": "道琼斯", "int_nasdaq": "纳斯达克", "int_sp500": "标普500"}
                name = names.get(m.group(1), parts[0])
                result[name] = {
                    "current": float(parts[1]),
                    "change": float(parts[2]),
                    "change_pct": float(parts[3]),
                }
    except Exception:
        pass
    return result


def fetch_commodities() -> dict:
    """大宗商品（黄金/原油/铜）"""
    # 新浪期货代码：hf_GC=黄金, hf_CL=原油, hf_HG=铜
    symbols = "hf_GC,hf_CL,hf_HG"
    url = f"https://hq.sinajs.cn/list={symbols}"
    names = {"hf_GC": "黄金(美元/盎司)", "hf_CL": "原油(美元/桶)", "hf_HG": "铜(美元/磅)"}
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
            parts = m.group(2).split(',')
            if len(parts) >= 1:
                name = names.get(sym, sym)
                try:
                    current = float(parts[0])
                    # 新浪期货格式不统一，尝试取买入价
                    prev = float(parts[7]) if len(parts) > 7 and parts[7] else current
                    chg_pct = (current - prev) / prev * 100 if prev else 0
                    result[name] = {
                        "current": current,
                        "change_pct": round(chg_pct, 2),
                    }
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass
    return result


def fetch_usd_index() -> dict:
    """美元指数"""
    url = "https://hq.sinajs.cn/list=hf_DINIW"
    try:
        raw = _urlget(url, encoding='gbk')
        if '=""' not in raw:
            m = re.search(r'"([^"]*)"', raw)
            if m:
                parts = m.group(1).split(',')
                if len(parts) >= 1:
                    current = float(parts[0])
                    prev = float(parts[7]) if len(parts) > 7 and parts[7] else current
                    return {
                        "current": current,
                        "change_pct": round((current - prev) / prev * 100, 2) if prev else 0,
                    }
    except Exception:
        pass
    return {}


def fetch_forex() -> dict:
    """主要汇率"""
    pairs = {"fx_susdcny": "美元/人民币", "fx_snzdcny": "纽元/人民币", "fx_shkdcny": "港币/人民币"}
    url = f"https://hq.sinajs.cn/list={','.join(pairs.keys())}"
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
            if len(parts) >= 2:
                try:
                    result[name] = {"rate": float(parts[1])}
                except ValueError:
                    pass
    except Exception:
        pass
    return result


def fetch_northbound() -> dict:
    """北向资金（沪股通+深股通净流入）"""
    url = ("https://push2.eastmoney.com/api/qt/kamt.rtmin/get"
           "?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56")
    try:
        raw = _urlget(url)
        data = json.loads(raw)
        s2n = data.get("data", {}).get("s2n", [])  # 沪股通分时
        n2s = data.get("data", {}).get("n2s", [])  # 深股通分时

        # 格式: "HH:MM,净买入(万),买入额(万),卖出额(万),..."
        # 找最后一条有效数据（非"-"）
        sh_net = 0
        for item in reversed(s2n):
            parts = item.split(',')
            if len(parts) >= 2 and parts[1] != '-' and parts[1]:
                sh_net = float(parts[1])
                break

        sz_net = 0
        for item in reversed(n2s):
            parts = item.split(',')
            if len(parts) >= 2 and parts[1] != '-' and parts[1]:
                sz_net = float(parts[1])
                break

        total_net = sh_net + sz_net  # 万元
        return {
            "sh_net_wan": sh_net,
            "sz_net_wan": sz_net,
            "total_net_yi": round(total_net / 10000, 2),  # 万→亿
            "date": data.get("data", {}).get("s2nDate", ""),
        }
    except Exception as e:
        return {"error": f"北向资金数据获取失败: {e}"}


def collect_all() -> dict:
    """采集所有宏观数据"""
    return {
        "_meta": {
            "generated_at": datetime.now().isoformat(),
            "source": "macro_data.py",
            "note": "所有数字来自API，LLM禁止修改",
        },
        "us_indexes": fetch_us_indexes(),
        "commodities": fetch_commodities(),
        "usd_index": fetch_usd_index(),
        "forex": fetch_forex(),
        "northbound": fetch_northbound(),
    }


def main():
    parser = argparse.ArgumentParser(description='宏观数据采集')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    args = parser.parse_args()

    data = collect_all()

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print(f"\n{'═'*55}")
    print(f"  🌍 宏观数据 | {data['_meta']['generated_at'][:16]}")
    print(f"{'═'*55}")

    print(f"\n  【美股】")
    for name, d in data.get("us_indexes", {}).items():
        emoji = "🟢" if d["change_pct"] > 0 else "🔴"
        print(f"  {emoji} {name}: {d['current']:,.2f} ({d['change_pct']:+.2f}%)")

    print(f"\n  【大宗商品】")
    for name, d in data.get("commodities", {}).items():
        print(f"  {name}: {d['current']:.2f} ({d['change_pct']:+.2f}%)")

    usd = data.get("usd_index", {})
    if usd:
        print(f"\n  【美元指数】{usd.get('current', 0):.2f} ({usd.get('change_pct', 0):+.2f}%)")

    print(f"\n  【外汇】")
    for name, d in data.get("forex", {}).items():
        print(f"  {name}: {d['rate']:.4f}")

    nb = data.get("northbound", {})
    if "error" not in nb:
        print(f"\n  【北向资金】({nb.get('date', '')})")
        print(f"  沪股通: {nb.get('sh_net_wan', 0)/10000:+.2f}亿")
        print(f"  深股通: {nb.get('sz_net_wan', 0)/10000:+.2f}亿")
        print(f"  合计: {nb.get('total_net_yi', 0):+.2f}亿")
    else:
        print(f"\n  【北向资金】{nb.get('error', '暂不可用')}")

    print(f"\n{'═'*55}\n")


if __name__ == "__main__":
    main()
