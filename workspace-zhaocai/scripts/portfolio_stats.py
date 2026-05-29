#!/usr/bin/env python3
"""
portfolio_stats.py — 统计员（量化指标计算）
计算组合的量化统计指标，用数据说话。

指标体系：
  1. 各标的年化收益率（持有期收益年化）
  2. 各标的年化波动率（日收益率标准差×√252）
  3. 夏普比率（超额收益/波动率，无风险利率=2%）
  4. 标的间相关性矩阵（判断分散化程度）
  5. 组合Beta（相对沪深300的系统性风险）
  6. 信息比率（超额收益/跟踪误差）
  7. 最大回撤及回撤天数

用法：
    python3 portfolio_stats.py          # 完整统计报告
    python3 portfolio_stats.py --json   # JSON输出
    python3 portfolio_stats.py --corr   # 只输出相关性矩阵
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
RISK_FREE_RATE = 0.02  # 无风险利率2%（年化）


def load_holdings():
    with open(HOLDINGS_PATH, encoding='utf-8') as f:
        return json.load(f)


def fetch_hist_closes(code: str, days: int = 120) -> list:
    """获取历史收盘价序列"""
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


def fetch_index_closes(days: int = 120) -> list:
    """获取沪深300历史收盘价（用于Beta计算）"""
    import akshare as ak
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
        df = ak.stock_zh_index_daily(symbol="sh000300")
        if df.empty:
            return []
        df = df[df['date'] >= start]
        return df['close'].tolist()[-days:]
    except Exception:
        return []


def calc_returns(closes: list) -> list:
    """计算日收益率序列"""
    return [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]


def calc_annual_return(closes: list) -> float:
    """年化收益率"""
    if len(closes) < 2:
        return 0
    total_return = (closes[-1] - closes[0]) / closes[0]
    days = len(closes)
    annual = (1 + total_return) ** (252 / days) - 1
    return round(annual * 100, 2)


def calc_volatility(returns: list) -> float:
    """年化波动率"""
    if len(returns) < 5:
        return 0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    daily_vol = math.sqrt(variance)
    return round(daily_vol * math.sqrt(252) * 100, 2)


def calc_sharpe(annual_return: float, volatility: float) -> float:
    """夏普比率"""
    if volatility == 0:
        return 0
    return round((annual_return / 100 - RISK_FREE_RATE) / (volatility / 100), 2)


def calc_max_drawdown(closes: list) -> dict:
    """最大回撤（含回撤天数）"""
    if len(closes) < 2:
        return {"pct": 0, "days": 0}
    peak = closes[0]
    max_dd = 0
    max_dd_days = 0
    current_dd_start = 0

    for i, p in enumerate(closes):
        if p > peak:
            peak = p
            current_dd_start = i
        dd = (p - peak) / peak
        if dd < max_dd:
            max_dd = dd
            max_dd_days = i - current_dd_start

    return {"pct": round(max_dd * 100, 2), "days": max_dd_days}


def calc_beta(stock_returns: list, index_returns: list) -> float:
    """Beta（相对沪深300）"""
    n = min(len(stock_returns), len(index_returns))
    if n < 20:
        return 1.0
    sr = stock_returns[-n:]
    ir = index_returns[-n:]

    mean_s = sum(sr) / n
    mean_i = sum(ir) / n

    cov = sum((sr[j] - mean_s) * (ir[j] - mean_i) for j in range(n)) / n
    var_i = sum((ir[j] - mean_i) ** 2 for j in range(n)) / n

    if var_i == 0:
        return 1.0
    return round(cov / var_i, 2)


def calc_correlation(returns_a: list, returns_b: list) -> float:
    """两个收益率序列的相关系数"""
    n = min(len(returns_a), len(returns_b))
    if n < 10:
        return 0
    a = returns_a[-n:]
    b = returns_b[-n:]

    mean_a = sum(a) / n
    mean_b = sum(b) / n

    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / n
    std_a = math.sqrt(sum((a[i] - mean_a) ** 2 for i in range(n)) / n)
    std_b = math.sqrt(sum((b[i] - mean_b) ** 2 for i in range(n)) / n)

    if std_a == 0 or std_b == 0:
        return 0
    return round(cov / (std_a * std_b), 3)


def run_stats() -> dict:
    """完整统计分析"""
    holdings = load_holdings()
    all_items = {**holdings.get("stocks", {}), **holdings.get("etfs", {})}
    # 注意：港股/美股使用不同数据源，暂不纳入A股统计分析
    # 后续可扩展 fetch_hist 支持港股代码

    # 获取沪深300
    index_closes = fetch_index_closes(120)
    index_returns = calc_returns(index_closes) if len(index_closes) > 1 else []

    stats = []
    all_returns = {}  # 用于相关性矩阵

    for code, info in all_items.items():
        closes = fetch_hist_closes(code, 120)
        if len(closes) < 20:
            stats.append({"code": code, "name": info["name"], "error": "数据不足"})
            continue

        returns = calc_returns(closes)
        all_returns[code] = returns

        annual_ret = calc_annual_return(closes)
        vol = calc_volatility(returns)
        sharpe = calc_sharpe(annual_ret, vol)
        max_dd = calc_max_drawdown(closes)
        beta = calc_beta(returns, index_returns)

        stats.append({
            "code": code,
            "name": info["name"],
            "sector": info.get("sector", ""),
            "annual_return": annual_ret,
            "volatility": vol,
            "sharpe": sharpe,
            "max_drawdown": max_dd["pct"],
            "max_dd_days": max_dd["days"],
            "beta": beta,
        })

    # 相关性矩阵（只取有数据的）
    codes_with_data = [s["code"] for s in stats if "error" not in s]
    corr_matrix = {}
    for i, c1 in enumerate(codes_with_data):
        for c2 in codes_with_data[i+1:]:
            if c1 in all_returns and c2 in all_returns:
                corr = calc_correlation(all_returns[c1], all_returns[c2])
                key = f"{c1}-{c2}"
                corr_matrix[key] = corr

    # 高相关性预警（>0.7）
    high_corr = {k: v for k, v in corr_matrix.items() if abs(v) > 0.7}

    # 组合整体指标
    portfolio_vol = sum(s.get("volatility", 0) for s in stats if "error" not in s) / max(1, len(codes_with_data))
    portfolio_sharpe = sum(s.get("sharpe", 0) for s in stats if "error" not in s) / max(1, len(codes_with_data))
    avg_beta = sum(s.get("beta", 1) for s in stats if "error" not in s) / max(1, len(codes_with_data))

    return {
        "_meta": {"generated_at": datetime.now().isoformat(), "source": "portfolio_stats.py"},
        "portfolio_summary": {
            "avg_volatility": round(portfolio_vol, 2),
            "avg_sharpe": round(portfolio_sharpe, 2),
            "avg_beta": round(avg_beta, 2),
            "diversification": "良好" if len(high_corr) < 3 else "不足（多只高相关）",
        },
        "stocks": sorted(stats, key=lambda x: -x.get("sharpe", 0)),
        "high_correlation": high_corr,
        "correlation_matrix": corr_matrix,
    }


def main():
    parser = argparse.ArgumentParser(description='统计员 — 量化指标')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    parser.add_argument('--corr', action='store_true', help='只输出相关性')
    args = parser.parse_args()

    result = run_stats()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    ps = result["portfolio_summary"]
    print(f"\n{'═'*65}")
    print(f"  📊 量化统计报告 | {result['_meta']['generated_at'][:16]}")
    print(f"{'═'*65}")
    print(f"  组合平均波动率: {ps['avg_volatility']:.1f}%")
    print(f"  组合平均夏普比: {ps['avg_sharpe']:.2f}")
    print(f"  组合平均Beta: {ps['avg_beta']:.2f}")
    print(f"  分散化程度: {ps['diversification']}")

    if not args.corr:
        print(f"\n  {'名称':<8}{'年化收益':>8}{'波动率':>7}{'夏普':>6}{'Beta':>6}{'最大回撤':>8}")
        print(f"  {'─'*48}")
        for s in result["stocks"]:
            if "error" in s:
                print(f"  {s['name']:<8} 数据不足")
                continue
            print(f"  {s['name']:<8}{s['annual_return']:>+7.1f}%{s['volatility']:>6.1f}%"
                  f"{s['sharpe']:>6.2f}{s['beta']:>5.2f}{s['max_drawdown']:>+7.1f}%")

    # 高相关性预警
    if result["high_correlation"]:
        print(f"\n  【⚠️ 高相关性（>0.7）— 分散化不足】")
        for pair, corr in sorted(result["high_correlation"].items(), key=lambda x: -abs(x[1])):
            c1, c2 = pair.split("-")
            n1 = next((s["name"] for s in result["stocks"] if s.get("code") == c1), c1)
            n2 = next((s["name"] for s in result["stocks"] if s.get("code") == c2), c2)
            print(f"  {n1} ↔ {n2}: {corr:.3f}")

    print(f"\n{'═'*65}\n")


if __name__ == "__main__":
    main()
