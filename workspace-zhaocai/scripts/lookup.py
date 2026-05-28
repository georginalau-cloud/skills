#!/usr/bin/env python3
"""
lookup.py — 万能查询脚本（招财的"先查再说"工具）
用户问任何标的/板块/基金，招财必须先跑这个脚本拿到数据再回答。

用法：
    python3 lookup.py --stock 300750              # 查个股实时行情+技术面
    python3 lookup.py --stock 300750 600519 002475  # 批量查多只
    python3 lookup.py --fund 163402               # 查基金净值+盘中估值
    python3 lookup.py --sector 人工智能           # 查概念板块成分股TOP20
    python3 lookup.py --index                     # 查大盘指数
    python3 lookup.py --etf 159566                # 查ETF实时行情

所有输出都是确切的API数据，禁止LLM修改任何数字。
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

# ── 强制清除代理环境变量（国内金融接口不能走代理）──
import os as _os
for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY'):
    _os.environ.pop(_k, None)


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
#  个股查询
# ════════════════════════════════════════════════════════════

def lookup_stocks(codes: list) -> list:
    """批量查询个股/ETF实时行情"""
    results = []

    # push2 批量获取
    secids = []
    code_map = {}
    for c in codes:
        c = c.strip().replace('sh', '').replace('sz', '')
        if c.startswith(('6', '688', '5')):
            sid = f"1.{c}"
        else:
            sid = f"0.{c}"
        secids.append(sid)
        code_map[sid] = c

    if not secids:
        return results

    url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
           f"?fltt=2&invt=2&fields=f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21"
           f"&secids={','.join(secids)}")
    try:
        raw = _urlget(url)
        data = json.loads(raw)
        for item in data.get('data', {}).get('diff', []):
            code = str(item.get('f12', '')).zfill(6)
            results.append({
                "code": code,
                "name": item.get('f14', ''),
                "price": item.get('f2'),
                "change_pct": item.get('f3'),
                "change_amount": item.get('f4'),
                "volume_lot": item.get('f5'),       # 成交量（手）
                "amount_yuan": item.get('f6'),      # 成交额（元）
                "amplitude": item.get('f7'),        # 振幅%
                "turnover_rate": item.get('f8'),    # 换手率%
                "pe_ttm": item.get('f9'),           # 市盈率TTM
                "volume_ratio": item.get('f10'),    # 量比
                "high": item.get('f15'),
                "low": item.get('f16'),
                "open": item.get('f17'),
                "prev_close": item.get('f18'),
                "total_mv": item.get('f20'),        # 总市值
                "float_mv": item.get('f21'),        # 流通市值
                "source": "push2.eastmoney",
                "fetch_time": datetime.now().strftime("%H:%M:%S"),
            })
    except Exception as e:
        print(f"⚠️ push2失败: {e}", file=sys.stderr)

    # 补充缺失的（新浪兜底）
    fetched_codes = {r['code'] for r in results}
    missing = [c for c in codes if c not in fetched_codes]
    if missing:
        for r in _fetch_sina_stocks(missing):
            results.append(r)

    return results


def _fetch_sina_stocks(codes: list) -> list:
    """新浪兜底"""
    symbols = []
    for c in codes:
        prefix = "sh" if c.startswith(('6', '688', '5')) else "sz"
        symbols.append(f"{prefix}{c}")

    results = []
    url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
    try:
        raw = _urlget(url, encoding='gbk')
        for line in raw.strip().split('\n'):
            if '=' not in line or '"' not in line:
                continue
            key = line.split('=')[0].split('_')[-1]
            code = key.replace('sh', '').replace('sz', '')
            vals = line.split('"')[1].split(',')
            if len(vals) < 9:
                continue
            try:
                cur = float(vals[3]) if vals[3] else 0
                prev = float(vals[2]) if vals[2] else 0
                results.append({
                    "code": code,
                    "name": vals[0],
                    "price": cur,
                    "change_pct": round((cur - prev) / prev * 100, 2) if prev else 0,
                    "prev_close": prev,
                    "high": float(vals[4]) if vals[4] else 0,
                    "low": float(vals[5]) if vals[5] else 0,
                    "volume_lot": int(vals[8]) if vals[8] else 0,
                    "amount_yuan": float(vals[9]) if len(vals) > 9 and vals[9] else 0,
                    "source": "sina",
                    "fetch_time": datetime.now().strftime("%H:%M:%S"),
                })
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return results


# ════════════════════════════════════════════════════════════
#  基金净值查询
# ════════════════════════════════════════════════════════════

def lookup_fund(fund_code: str) -> dict:
    """查询基金净值+盘中估值"""
    result = {"code": fund_code, "source": "eastmoney"}

    # P1: fundgz 盘中估值
    url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js?rt={int(time.time())}"
    try:
        raw = _urlget(url)
        m = re.search(r'jsonpgz\((.+)\)', raw)
        if m and 'dwjz' in m.group(1):
            d = json.loads(m.group(1))
            result.update({
                "name": d.get('name', ''),
                "nav": float(d['dwjz']),
                "nav_date": d.get('jzrq', ''),
                "gsz": float(d.get('gsz', 0)),       # 盘中估值
                "gszzl": float(d.get('gszzl', 0)),   # 估算涨跌幅%
                "gsz_time": d.get('gztime', ''),
                "source": "fundgz",
            })
            return result
    except Exception:
        pass

    # P2: lsjz（QDII基金）
    url2 = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex=1&pageSize=1"
    try:
        raw = _urlget(url2)
        data = json.loads(raw)
        items = data.get('Data', {}).get('LSJZList', [])
        if items:
            latest = items[0]
            result.update({
                "name": "",
                "nav": float(latest['DWJZ']),
                "nav_date": latest['FSRQ'],
                "gszzl": float(latest.get('JZZZL', 0)),
                "source": "lsjz",
            })
            return result
    except Exception:
        pass

    result["error"] = "无法获取净值数据"
    return result


# ════════════════════════════════════════════════════════════
#  概念板块成分股
# ════════════════════════════════════════════════════════════

def lookup_sector(keyword: str, top: int = 20) -> dict:
    """查询概念板块成分股TOP N"""
    # Step 1: 搜索板块代码
    search_url = (f"https://push2.eastmoney.com/api/qt/slist/get"
                  f"?spt=1&np=1&fltt=2&invt=2&fields=f12,f14"
                  f"&fid=f3&fs=m:90&_={int(time.time()*1000)}")

    # 用板块列表接口找匹配的板块
    list_url = (f"https://push2.eastmoney.com/api/qt/clist/get"
                f"?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3"
                f"&fs=m:90+t:2+f:!50"
                f"&fields=f12,f14,f3,f20,f128,f136")
    try:
        raw = _urlget(list_url)
        data = json.loads(raw)
        items = data.get('data', {}).get('diff', [])

        # 模糊匹配板块名
        matched = None
        for item in items:
            name = item.get('f14', '')
            if keyword in name:
                matched = item
                break

        if not matched:
            return {"error": f"未找到包含'{keyword}'的概念板块", "available_top10": [i.get('f14','') for i in items[:10]]}

        sector_code = matched.get('f12', '')
        sector_name = matched.get('f14', '')

    except Exception as e:
        return {"error": f"板块搜索失败: {e}"}

    # Step 2: 获取板块成分股
    stocks_url = (f"https://push2.eastmoney.com/api/qt/clist/get"
                  f"?pn=1&pz={top}&po=1&np=1&fltt=2&invt=2&fid=f3"
                  f"&fs=b:{sector_code}+f:!50"
                  f"&fields=f2,f3,f4,f8,f9,f12,f14,f20,f21")
    try:
        raw = _urlget(stocks_url)
        data = json.loads(raw)
        stocks = []
        for item in data.get('data', {}).get('diff', []):
            stocks.append({
                "code": str(item.get('f12', '')).zfill(6),
                "name": item.get('f14', ''),
                "price": item.get('f2'),
                "change_pct": item.get('f3'),
                "turnover_rate": item.get('f8'),
                "pe_ttm": item.get('f9'),
                "total_mv": item.get('f20'),
                "float_mv": item.get('f21'),
            })
        return {
            "sector_name": sector_name,
            "sector_code": sector_code,
            "sector_change_pct": matched.get('f3', 0),
            "stocks": stocks,
            "fetch_time": datetime.now().strftime("%H:%M:%S"),
            "source": "push2.eastmoney",
        }
    except Exception as e:
        return {"error": f"成分股获取失败: {e}"}


# ════════════════════════════════════════════════════════════
#  大盘指数
# ════════════════════════════════════════════════════════════

def lookup_indexes() -> list:
    """查询A股主要指数"""
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
#  输出格式化
# ════════════════════════════════════════════════════════════

def print_stocks(results: list):
    """打印个股查询结果"""
    for r in results:
        if 'error' in r:
            print(f"❌ {r.get('code','?')}: {r['error']}")
            continue
        chg = r.get('change_pct', 0) or 0
        emoji = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
        price = r.get('price', 0) or 0
        pe = r.get('pe_ttm', '-')
        mv = r.get('total_mv')
        mv_str = f"{mv/1e8:.0f}亿" if mv and mv > 0 else "-"
        turnover = r.get('turnover_rate', '-')
        print(f"{emoji} {r['name']}({r['code']}) ¥{price:.2f} {chg:+.2f}%"
              f" | PE={pe} | 市值{mv_str} | 换手{turnover}%"
              f" [{r.get('source','')} {r.get('fetch_time','')}]")


def print_fund(r: dict):
    """打印基金查询结果"""
    if 'error' in r:
        print(f"❌ {r['code']}: {r['error']}")
        return
    nav = r.get('nav', 0)
    gsz = r.get('gsz', 0)
    gszzl = r.get('gszzl', 0)
    print(f"📊 {r.get('name','')}({r['code']})")
    print(f"   最新净值: {nav:.4f} ({r.get('nav_date','')})")
    if gsz:
        print(f"   盘中估值: {gsz:.4f} ({gszzl:+.2f}%) [{r.get('gsz_time','')}]")
    print(f"   [{r.get('source','')}]")


def print_sector(r: dict):
    """打印板块查询结果"""
    if 'error' in r:
        print(f"❌ {r['error']}")
        if 'available_top10' in r:
            print(f"   可用板块: {', '.join(r['available_top10'])}")
        return
    print(f"🔥 {r['sector_name']}（{r['sector_code']}）{r['sector_change_pct']:+.2f}%")
    print(f"   成分股TOP{len(r['stocks'])}（按涨幅排序）:")
    print(f"   {'代码':<8}{'名称':<10}{'现价':>8}{'涨跌%':>8}{'PE':>8}{'市值':>10}")
    print(f"   {'─'*52}")
    for s in r['stocks']:
        price = s.get('price', 0) or 0
        chg = s.get('change_pct', 0) or 0
        pe = s.get('pe_ttm', '-')
        mv = s.get('total_mv')
        mv_str = f"{mv/1e8:.0f}亿" if mv and mv > 0 else "-"
        print(f"   {s['code']:<8}{s['name']:<10}{price:>8.2f}{chg:>+7.2f}%{str(pe):>8}{mv_str:>10}")
    print(f"   [{r.get('source','')} {r.get('fetch_time','')}]")


# ════════════════════════════════════════════════════════════
#  命令行入口
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='万能查询（招财必须先跑再说）')
    parser.add_argument('--stock', nargs='+', help='查个股/ETF（支持多个代码）')
    parser.add_argument('--fund', type=str, help='查基金净值')
    parser.add_argument('--sector', type=str, help='查概念板块成分股（关键词）')
    parser.add_argument('--index', action='store_true', help='查大盘指数')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    parser.add_argument('--top', type=int, default=20, help='板块成分股数量')
    args = parser.parse_args()

    if args.stock:
        results = lookup_stocks(args.stock)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_stocks(results)

    elif args.fund:
        result = lookup_fund(args.fund)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_fund(result)

    elif args.sector:
        result = lookup_sector(args.sector, top=args.top)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_sector(result)

    elif args.index:
        results = lookup_indexes()
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print("📊 大盘指数:")
            for r in results:
                emoji = "🟢" if r['change_pct'] > 0 else "🔴"
                print(f"  {emoji} {r['name']}: {r['current']:,.2f} ({r['change_pct']:+.2f}%)")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
