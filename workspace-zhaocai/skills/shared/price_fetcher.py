#!/usr/bin/env python3
"""
统一价格获取模块 — 所有招财 skill 共用
数据源优先级：push2(东方财富) > 腾讯 > akshare > 新浪

用法：
    from shared.price_fetcher import get_a_stock_prices, get_hk_us_prices, get_fund_nav
"""

import json
import re
import time
import urllib.request
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://fund.eastmoney.com/",
}

# ─── 持仓数据加载 ───────────────────────────────────────────────

def load_holdings():
    """从统一的 holdings.json 加载持仓数据"""
    holdings_path = Path(__file__).parent.parent.parent / "holdings.json"
    if not holdings_path.exists():
        # 兜底：尝试 workspace 根目录
        holdings_path = Path(__file__).parent.parent.parent / "holdings.json"
    if holdings_path.exists():
        with open(holdings_path, encoding='utf-8') as f:
            return json.load(f)
    return {"stocks": {}, "etfs": {}, "funds": {}}


# ─── A股价格（push2 优先）───────────────────────────────────────

def _secid(code):
    """将A股代码转为 push2 secid 格式"""
    c = code.strip()
    if c.startswith(('6', '688')):
        return f"1.{c}"
    elif c.startswith(('0', '3', '15', '16')):
        return f"0.{c}"
    return None


def get_a_stock_prices(codes: list) -> dict:
    """
    获取A股实时价格（含涨跌幅）
    返回: {code: {"price": float, "change_pct": float, "name": str}}
    
    优先级: push2 > 腾讯 > akshare > 新浪
    """
    result = _fetch_push2(codes)
    
    # 检查缺失
    missing = [c for c in codes if c not in result]
    if missing:
        tencent_result = _fetch_tencent_a(missing)
        result.update(tencent_result)
    
    missing = [c for c in codes if c not in result]
    if missing:
        sina_result = _fetch_sina(missing)
        result.update(sina_result)
    
    return result


def _fetch_push2(codes: list) -> dict:
    """P1: 东方财富 push2（最准确）"""
    secids = []
    code_map = {}
    for c in codes:
        sid = _secid(c)
        if sid:
            secids.append(sid)
            code_map[sid] = c
    
    if not secids:
        return {}
    
    result = {}
    BATCH = 80
    for i in range(0, len(secids), BATCH):
        batch = secids[i:i+BATCH]
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&invt=2&fields=f2,f3,f12,f14&secids={','.join(batch)}")
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            for item in data.get('data', {}).get('diff', []):
                code = str(item.get('f12', '')).zfill(6)
                price = item.get('f2')
                change_pct = item.get('f3')
                name = item.get('f14', '')
                if price is not None and change_pct is not None:
                    result[code] = {
                        "price": float(price),
                        "change_pct": float(change_pct),
                        "name": name,
                        "source": "push2"
                    }
        except Exception:
            pass
    return result


def _fetch_tencent_a(codes: list) -> dict:
    """P2: 腾讯财经（无需API Key）"""
    symbols = []
    for c in codes:
        if c.startswith(('6', '688')):
            symbols.append(f"sh{c}")
        else:
            symbols.append(f"sz{c}")
    
    if not symbols:
        return {}
    
    result = {}
    url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk', errors='ignore')
        
        for line in raw.strip().split(';'):
            if '~' not in line:
                continue
            parts = line.split('~')
            if len(parts) < 35:
                continue
            code = parts[2].strip()
            name = parts[1].strip()
            try:
                price = float(parts[3])
                change_pct = float(parts[32])
                if price > 0:
                    result[code] = {
                        "price": price,
                        "change_pct": change_pct,
                        "name": name,
                        "source": "tencent"
                    }
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return result


def _fetch_sina(codes: list) -> dict:
    """P4: 新浪财经（最后兜底）"""
    symbols = []
    for c in codes:
        if c.startswith(('6', '688')):
            symbols.append(f"sh{c}")
        else:
            symbols.append(f"sz{c}")
    
    if not symbols:
        return {}
    
    result = {}
    url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
    try:
        req = urllib.request.Request(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk', errors='ignore')
        
        for line in raw.strip().split('\n'):
            if '=' not in line:
                continue
            key = line.split('=')[0].split('_')[-1].strip()
            code = key.replace('sh', '').replace('sz', '')
            vals = line.split('"')[1].split(',') if '"' in line else []
            if len(vals) < 6:
                continue
            try:
                name = vals[0]
                cur = float(vals[3]) if vals[3] else 0
                prev = float(vals[2]) if vals[2] else 0
                if cur > 0 and prev > 0:
                    change_pct = (cur - prev) / prev * 100
                    result[code] = {
                        "price": cur,
                        "change_pct": round(change_pct, 2),
                        "name": name,
                        "source": "sina"
                    }
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return result


# ─── 港美股价格（腾讯优先）──────────────────────────────────────

def get_hk_us_prices(codes: list, market: str = "hk") -> dict:
    """
    获取港股/美股价格
    market: "hk" 或 "us"
    返回: {code: {"price": float, "change_pct": float, "name": str}}
    
    优先级: 腾讯 > Yahoo Finance
    """
    result = _fetch_tencent_hk_us(codes, market)
    
    missing = [c for c in codes if c not in result]
    if missing:
        yahoo_result = _fetch_yahoo(missing, market)
        result.update(yahoo_result)
    
    return result


def _fetch_tencent_hk_us(codes: list, market: str) -> dict:
    """P1: 腾讯财经港美股"""
    symbols = []
    for c in codes:
        if market == "hk":
            symbols.append(f"hk{c.zfill(5)}")
        else:
            symbols.append(f"us{c.upper()}")
    
    if not symbols:
        return {}
    
    result = {}
    url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk', errors='ignore')
        
        for line in raw.strip().split(';'):
            if '~' not in line:
                continue
            parts = line.split('~')
            if len(parts) < 35:
                continue
            code = parts[2].strip()
            name = parts[1].strip()
            try:
                price = float(parts[3])
                change_pct = float(parts[32])
                if price > 0:
                    result[code] = {
                        "price": price,
                        "change_pct": change_pct,
                        "name": name,
                        "source": "tencent"
                    }
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return result


def _fetch_yahoo(codes: list, market: str) -> dict:
    """P2: Yahoo Finance（港美股兜底）"""
    result = {}
    for code in codes:
        if market == "hk":
            symbol = f"{code.zfill(4)}.HK"
        else:
            symbol = code.upper()
        
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            meta = data["chart"]["result"][0]["meta"]
            cur = meta["regularMarketPrice"]
            prev = meta.get("previousClose") or meta.get("chartPreviousClose", cur)
            change_pct = (cur - prev) / prev * 100 if prev else 0
            result[code] = {
                "price": cur,
                "change_pct": round(change_pct, 2),
                "name": symbol,
                "source": "yahoo"
            }
            time.sleep(0.3)  # Rate limit
        except Exception:
            pass
    return result


# ─── 基金净值 ──────────────────────────────────────────────────

def get_fund_nav(fund_code: str) -> dict:
    """
    获取基金净值和盘中估值
    返回: {"nav": float, "gsz": float, "gszzl": float, "date": str, "source": str}
    
    优先级: fundgz > lsjz(QDII)
    """
    # P1: fundgz（国内基金盘中估值）
    try:
        url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js?rt={int(time.time())}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode('utf-8')
        m = re.search(r'jsonpgz\((.+)\)', raw)
        if m and 'dwjz' in m.group(1):
            d = json.loads(m.group(1))
            return {
                "nav": float(d['dwjz']),
                "gsz": float(d.get('gsz', 0)),
                "gszzl": float(d.get('gszzl', 0)),
                "date": d.get('jzrq', ''),
                "name": d.get('name', ''),
                "source": "fundgz"
            }
    except Exception:
        pass
    
    # P2: lsjz（QDII基金/港美股基金）
    try:
        url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex=1&pageSize=1"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        items = data.get('Data', {}).get('LSJZList', [])
        if items:
            latest = items[0]
            return {
                "nav": float(latest['DWJZ']),
                "gsz": 0,
                "gszzl": float(latest.get('JZZZL', 0)),
                "date": latest['FSRQ'],
                "name": "",
                "source": "lsjz"
            }
    except Exception:
        pass
    
    return {"nav": 0, "gsz": 0, "gszzl": 0, "date": "", "name": "", "source": "failed"}


# ─── 基金股票配置比例 C1% ──────────────────────────────────────

def get_fund_stock_ratio(fund_code: str) -> float:
    """获取基金股票总配置比例 C1%（从资产配置页抓取）"""
    try:
        url = f"https://fundf10.eastmoney.com/zcpz_{fund_code}.html"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode('utf-8')
        # 找第一个百分比数字（通常是股票占比）
        m = re.search(r'股票占净值比例.*?([\d.]+)%', raw)
        if m:
            return float(m.group(1))
        # 备用：找表格中第一行第二列的百分比
        m2 = re.search(r'<td[^>]*>([\d.]+)%</td>', raw)
        if m2:
            return float(m2.group(1))
    except Exception:
        pass
    return 0.0


if __name__ == "__main__":
    # 测试
    print("=== 测试 A 股价格获取 ===")
    prices = get_a_stock_prices(["600519", "300896", "000001"])
    for code, data in prices.items():
        print(f"  {code}: {data['name']} ¥{data['price']} ({data['change_pct']:+.2f}%) [{data['source']}]")
    
    print("\n=== 测试基金净值获取 ===")
    nav = get_fund_nav("163402")
    print(f"  163402: NAV={nav['nav']} GSZ={nav['gsz']} ({nav['gszzl']:+.2f}%) [{nav['source']}]")
    
    print("\n=== 测试持仓加载 ===")
    h = load_holdings()
    print(f"  个股: {len(h.get('stocks', {}))}只")
    print(f"  ETF: {len(h.get('etfs', {}))}只")
    print(f"  基金: {len(h.get('funds', {}))}只")
