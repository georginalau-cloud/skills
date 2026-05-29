#!/usr/bin/env python3
"""
risk_monitor.py — 风控官（持仓风险扫描）
计算组合风险指标，输出止损预警和仓位建议。

指标体系：
  1. 单只集中度：单只占总市值比例（>20%预警）
  2. 板块集中度：同板块合计占比（>30%预警）
  3. 最大回撤：各标的从最高点回撤幅度
  4. VaR(95%)：基于历史波动率的单日最大亏损估算
  5. 止损预警：浮亏超-15%且均线空头的标的
  6. 波动率：各标的年化波动率
  7. 风险等级：L1(低)-L5(极高)

用法：
    python3 risk_monitor.py             # 完整风控报告
    python3 risk_monitor.py --json      # JSON输出
    python3 risk_monitor.py --alerts    # 只输出预警项
"""

import json
import sys
import math
import argparse
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
HOLDINGS_PATH = WORKSPACE / "holdings.json"


def load_holdings():
    with open(HOLDINGS_PATH, encoding='utf-8') as f:
        return json.load(f)


def fetch_hist(code: str, days: int = 60, market: str = "a") -> list:
    """获取历史收盘价
    market: "a"=A股(akshare), "hk"=港股(yahoo), "us"=美股(yahoo)
    """
    if market == "a":
        return _fetch_hist_a(code, days)
    else:
        return _fetch_hist_yahoo(code, days, market)


def _fetch_hist_a(code: str, days: int = 60) -> list:
    """A股历史数据（akshare）"""
    import akshare as ak
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date=start, end_date=end, adjust="qfq")
        if df.empty:
            return []
        return df['收盘'].tolist()[-days:]
    except Exception:
        return []


def _fetch_hist_yahoo(code: str, days: int = 60, market: str = "hk") -> list:
    """港美股历史数据（Yahoo Finance）"""
    import urllib.request, ssl, json as _json
    if market == "hk":
        symbol = f"{code.zfill(4)}.HK"
    else:
        symbol = code.upper()

    # Yahoo Finance chart API: 获取近N天日K
    period1 = int((datetime.now() - timedelta(days=days + 5)).timestamp())
    period2 = int(datetime.now().timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}&period2={period2}&interval=1d"

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        with opener.open(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        # 过滤 None 值
        return [c for c in closes if c is not None][-days:]
    except Exception:
        return []


def calc_volatility(closes: list) -> float:
    """年化波动率"""
    if len(closes) < 10:
        return 0
    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    if not returns:
        return 0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    daily_vol = math.sqrt(variance)
    annual_vol = daily_vol * math.sqrt(252)
    return round(annual_vol * 100, 2)  # 百分比


def calc_max_drawdown(closes: list) -> float:
    """最大回撤（从最高点到当前的跌幅）"""
    if not closes:
        return 0
    peak = max(closes)
    current = closes[-1]
    dd = (current - peak) / peak * 100
    return round(dd, 2)


def calc_var_95(closes: list, position_value: float) -> float:
    """VaR(95%) — 单日最大可能亏损"""
    if len(closes) < 20:
        return 0
    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    returns.sort()
    # 95% VaR = 第5百分位的收益率
    idx = max(0, int(len(returns) * 0.05))
    var_pct = returns[idx]
    var_amount = position_value * abs(var_pct)
    return round(var_amount, 0)


def analyze_risk() -> dict:
    """完整风控分析"""
    holdings = load_holdings()
    import akshare as ak

    # 获取实时价格
    all_codes = list(holdings.get("stocks", {}).keys()) + list(holdings.get("etfs", {}).keys())

    # 港股和美股也纳入风控扫描

    # 用 push2 获取价格
    prices = {}
    try:
        import urllib.request, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))

        secids = []
        for c in all_codes:
            if c.startswith(('6', '688', '5')):
                secids.append(f"1.{c}")
            else:
                secids.append(f"0.{c}")

        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&invt=2&fields=f2,f12,f14&secids={','.join(secids)}")
        req = urllib.request.Request(url, headers={"Referer": "https://fund.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        for item in data.get('data', {}).get('diff', []):
            code = str(item.get('f12', '')).zfill(6)
            prices[code] = item.get('f2', 0)
    except Exception:
        pass

    # 逐只分析
    stock_risks = []
    total_mv = 0
    sector_mv = {}

    for code, info in {**holdings.get("stocks", {}), **holdings.get("etfs", {})}.items():
        price = prices.get(code, 0)
        if not price:
            continue

        mv = price * info["shares"]
        total_mv += mv
        sector = info.get("sector", "其他")
        sector_mv[sector] = sector_mv.get(sector, 0) + mv

        # 历史数据
        closes = fetch_hist(code, 60, market="a")
        volatility = calc_volatility(closes)
        max_dd = calc_max_drawdown(closes)
        var_95 = calc_var_95(closes, mv)

        # 浮盈亏
        pnl_pct = (price - info["cost"]) / info["cost"] * 100

        # 均线判断
        ma_bearish = False
        if len(closes) >= 20:
            ma5 = sum(closes[-5:]) / 5
            ma20 = sum(closes[-20:]) / 20
            ma_bearish = ma5 < ma20

        # 止损预警
        alerts = []
        if pnl_pct <= -25:
            alerts.append("🔴 浮亏超-25%，建议止损")
        elif pnl_pct <= -15 and ma_bearish:
            alerts.append("🟡 浮亏>15%且均线空头，考虑止损")
        if volatility > 60:
            alerts.append("⚠️ 年化波动率>60%，高风险")

        stock_risks.append({
            "code": code,
            "name": info["name"],
            "sector": sector,
            "price": price,
            "cost": info["cost"],
            "shares": info["shares"],
            "mv": round(mv, 0),
            "pnl_pct": round(pnl_pct, 2),
            "volatility": volatility,
            "max_drawdown": max_dd,
            "var_95": var_95,
            "ma_bearish": ma_bearish,
            "alerts": alerts,
            "market": "A股",
        })

    # 港股
    for code, info in holdings.get("hk_stocks", {}).items():
        closes = fetch_hist(code, 60, market="hk")
        if not closes:
            continue
        price = closes[-1]
        mv = price * info["shares"]  # HKD
        total_mv += mv * 0.87  # 粗略折算人民币
        sector = "港股"
        sector_mv[sector] = sector_mv.get(sector, 0) + mv * 0.87

        volatility = calc_volatility(closes)
        max_dd = calc_max_drawdown(closes)
        var_95 = calc_var_95(closes, mv * 0.87)
        pnl_pct = (price - info["cost"]) / info["cost"] * 100

        alerts = []
        if pnl_pct <= -25:
            alerts.append("🔴 浮亏超-25%，建议止损")
        elif pnl_pct <= -15:
            alerts.append("🟡 浮亏>15%，关注")
        if volatility > 60:
            alerts.append("⚠️ 年化波动率>60%")

        stock_risks.append({
            "code": code, "name": info["name"], "sector": sector,
            "price": price, "cost": info["cost"], "shares": info["shares"],
            "mv": round(mv * 0.87, 0), "pnl_pct": round(pnl_pct, 2),
            "volatility": volatility, "max_drawdown": max_dd, "var_95": var_95,
            "ma_bearish": False, "alerts": alerts, "market": "港股",
        })

    # 美股
    for code, info in holdings.get("us_stocks", {}).items():
        closes = fetch_hist(code, 60, market="us")
        if not closes:
            continue
        price = closes[-1]
        mv = price * info["shares"]  # USD
        total_mv += mv * 6.78  # 粗略折算人民币
        sector = "美股"
        sector_mv[sector] = sector_mv.get(sector, 0) + mv * 6.78

        volatility = calc_volatility(closes)
        max_dd = calc_max_drawdown(closes)
        var_95 = calc_var_95(closes, mv * 6.78)
        pnl_pct = (price - info["cost"]) / info["cost"] * 100

        alerts = []
        if pnl_pct <= -25:
            alerts.append("🔴 浮亏超-25%，建议止损")
        if volatility > 60:
            alerts.append("⚠️ 年化波动率>60%")

        stock_risks.append({
            "code": code, "name": info["name"], "sector": sector,
            "price": price, "cost": info["cost"], "shares": info["shares"],
            "mv": round(mv * 6.78, 0), "pnl_pct": round(pnl_pct, 2),
            "volatility": volatility, "max_drawdown": max_dd, "var_95": var_95,
            "ma_bearish": False, "alerts": alerts, "market": "美股",
        })

    # 集中度分析
    concentration_alerts = []
    for sr in stock_risks:
        pct = sr["mv"] / total_mv * 100 if total_mv else 0
        sr["position_pct"] = round(pct, 1)
        if pct > 20:
            concentration_alerts.append(f"🔴 {sr['name']}占仓{pct:.1f}%（建议<20%）")

    sector_alerts = []
    for sector, mv in sector_mv.items():
        pct = mv / total_mv * 100 if total_mv else 0
        if pct > 30:
            sector_alerts.append(f"🟡 {sector}板块占{pct:.1f}%（建议<30%）")

    # 组合VaR
    total_var = sum(sr["var_95"] for sr in stock_risks)
    # 考虑分散化效应（简化：打7折）
    portfolio_var = round(total_var * 0.7, 0)

    # 组合波动率（简化：加权平均）
    portfolio_vol = sum(sr["volatility"] * sr["mv"] for sr in stock_risks) / total_mv if total_mv else 0

    # 风险等级
    if portfolio_vol > 50 or any("🔴" in a for sr in stock_risks for a in sr["alerts"]):
        risk_level = "L4"
        risk_desc = "高风险"
    elif portfolio_vol > 35 or concentration_alerts:
        risk_level = "L3"
        risk_desc = "中高风险"
    elif portfolio_vol > 20:
        risk_level = "L2"
        risk_desc = "中等风险"
    else:
        risk_level = "L1"
        risk_desc = "低风险"

    return {
        "_meta": {"generated_at": datetime.now().isoformat(), "source": "risk_monitor.py"},
        "portfolio": {
            "total_mv": round(total_mv, 0),
            "risk_level": risk_level,
            "risk_desc": risk_desc,
            "portfolio_volatility": round(portfolio_vol, 2),
            "portfolio_var_95": portfolio_var,
            "var_95_desc": f"95%概率单日最大亏损不超过¥{portfolio_var:,.0f}",
        },
        "stocks": sorted(stock_risks, key=lambda x: x["pnl_pct"]),
        "concentration_alerts": concentration_alerts,
        "sector_alerts": sector_alerts,
        "sector_breakdown": {k: round(v/total_mv*100, 1) for k, v in sector_mv.items()},
        "stop_loss_candidates": [sr for sr in stock_risks if sr["alerts"]],
    }


def main():
    parser = argparse.ArgumentParser(description='风控官 — 持仓风险扫描')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    parser.add_argument('--alerts', action='store_true', help='只输出预警')
    args = parser.parse_args()

    result = analyze_risk()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    p = result["portfolio"]
    print(f"\n{'═'*60}")
    print(f"  🛡️ 风控报告 | {result['_meta']['generated_at'][:16]}")
    print(f"{'═'*60}")
    print(f"  风险等级: {p['risk_level']} ({p['risk_desc']})")
    print(f"  组合波动率: {p['portfolio_volatility']:.1f}%（年化）")
    print(f"  VaR(95%): {p['var_95_desc']}")
    print(f"  总市值: ¥{p['total_mv']:,.0f}")

    # 板块集中度
    print(f"\n  【板块分布】")
    for sector, pct in sorted(result["sector_breakdown"].items(), key=lambda x: -x[1]):
        bar = "█" * int(pct / 3)
        print(f"  {sector:<8} {pct:>5.1f}% {bar}")

    # 预警
    all_alerts = result["concentration_alerts"] + result["sector_alerts"]
    stop_loss = result["stop_loss_candidates"]

    if all_alerts or stop_loss:
        print(f"\n  【⚠️ 预警】")
        for a in all_alerts:
            print(f"  {a}")
        for sr in stop_loss:
            for a in sr["alerts"]:
                print(f"  {a} — {sr['name']}({sr['code']}) 浮盈{sr['pnl_pct']:+.1f}%")

    if not args.alerts:
        print(f"\n  【逐只风险】")
        print(f"  {'名称':<8}{'占仓':>5}{'浮盈':>7}{'波动率':>7}{'回撤':>7}{'VaR':>8}")
        print(f"  {'─'*45}")
        for sr in result["stocks"]:
            print(f"  {sr['name']:<8}{sr['position_pct']:>4.1f}%"
                  f"{sr['pnl_pct']:>+6.1f}%{sr['volatility']:>6.1f}%"
                  f"{sr['max_drawdown']:>+6.1f}%{sr['var_95']:>7,.0f}")

    print(f"\n{'═'*60}\n")


if __name__ == "__main__":
    main()
