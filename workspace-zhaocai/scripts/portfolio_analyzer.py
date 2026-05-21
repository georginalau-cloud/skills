#!/usr/bin/env python3
"""
持仓分析引擎 — portfolio_analyzer.py
计算：均线/MACD/RSI/PE/支撑压力位/盈亏/仓位占比

用法：
    python3 portfolio_analyzer.py                    # 全持仓分析
    python3 portfolio_analyzer.py --code 600352      # 单只分析
    python3 portfolio_analyzer.py --summary          # 只输出汇总
    python3 portfolio_analyzer.py --json             # JSON格式输出

输出：每只持仓标的的技术面+基本面+盈亏状况，以及组合整体汇总。
"""

import json
import sys
import os
import math
from datetime import datetime, timedelta
from pathlib import Path

# 路径配置
WORKSPACE = Path(__file__).resolve().parent.parent
HOLDINGS_FILE = WORKSPACE / "holdings.json"
sys.path.insert(0, str(WORKSPACE / "skills" / "shared"))

try:
    from price_fetcher import get_a_stock_prices, _urlopen_with_fallback
    HAS_FETCHER = True
except ImportError:
    HAS_FETCHER = False


# ════════════════════════════════════════════════════════════
#  数据加载
# ════════════════════════════════════════════════════════════

def load_holdings() -> dict:
    with open(HOLDINGS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def fetch_hist_data(code: str, days: int = 120) -> list:
    """
    获取历史K线数据（akshare）
    返回：[{date, open, close, high, low, volume, turnover_rate}, ...]
    按日期升序排列
    """
    try:
        import akshare as ak
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty:
            return []
        records = []
        for _, row in df.iterrows():
            records.append({
                'date': str(row['日期']),
                'open': float(row['开盘']),
                'close': float(row['收盘']),
                'high': float(row['最高']),
                'low': float(row['最低']),
                'volume': float(row['成交量']),
                'turnover_rate': float(row.get('换手率', 0)),
            })
        return records[-days:]  # 只取最近N天
    except Exception as e:
        print(f"  ⚠️ {code} 历史数据获取失败: {e}", file=sys.stderr)
        return []


def fetch_fundamental(code: str) -> dict:
    """
    获取基本面数据（PE/PB/ROE/营收增速等）
    """
    try:
        import akshare as ak
        # 个股指标
        df = ak.stock_a_indicator_lg(symbol=code)
        if df.empty:
            return {}
        latest = df.iloc[-1]
        return {
            'pe_ttm': float(latest.get('pe_ttm', 0)) if latest.get('pe_ttm') else None,
            'pb': float(latest.get('pb', 0)) if latest.get('pb') else None,
            'ps_ttm': float(latest.get('ps_ttm', 0)) if latest.get('ps_ttm') else None,
            'total_mv': float(latest.get('total_mv', 0)) if latest.get('total_mv') else None,  # 总市值(万)
        }
    except Exception as e:
        print(f"  ⚠️ {code} 基本面数据获取失败: {e}", file=sys.stderr)
        return {}


# ════════════════════════════════════════════════════════════
#  技术指标计算
# ════════════════════════════════════════════════════════════

def calc_ma(closes: list, period: int) -> float:
    """计算简单移动平均线"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_ema(closes: list, period: int) -> list:
    """计算指数移动平均线（返回完整序列）"""
    if len(closes) < period:
        return []
    emas = []
    multiplier = 2 / (period + 1)
    # 初始值用SMA
    ema = sum(closes[:period]) / period
    emas = [None] * (period - 1) + [ema]
    for i in range(period, len(closes)):
        ema = (closes[i] - ema) * multiplier + ema
        emas.append(ema)
    return emas


def calc_macd(closes: list) -> dict:
    """
    计算MACD（12,26,9）
    返回：{dif, dea, macd_bar, signal}
    signal: 'golden_cross' / 'death_cross' / 'bullish' / 'bearish' / 'neutral'
    """
    if len(closes) < 35:
        return {'dif': None, 'dea': None, 'macd_bar': None, 'signal': 'insufficient_data'}

    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)

    # DIF = EMA12 - EMA26
    dif_list = []
    for i in range(len(closes)):
        if ema12[i] is not None and ema26[i] is not None:
            dif_list.append(ema12[i] - ema26[i])
        else:
            dif_list.append(None)

    # DEA = DIF的9日EMA
    valid_difs = [d for d in dif_list if d is not None]
    if len(valid_difs) < 9:
        return {'dif': None, 'dea': None, 'macd_bar': None, 'signal': 'insufficient_data'}

    dea_list = calc_ema(valid_difs, 9)

    dif = valid_difs[-1] if valid_difs else None
    dea = dea_list[-1] if dea_list else None
    macd_bar = (dif - dea) * 2 if dif is not None and dea is not None else None

    # 判断信号
    signal = 'neutral'
    if len(valid_difs) >= 2 and len(dea_list) >= 2:
        prev_dif = valid_difs[-2]
        prev_dea = dea_list[-2]
        if prev_dif <= prev_dea and dif > dea:
            signal = 'golden_cross'
        elif prev_dif >= prev_dea and dif < dea:
            signal = 'death_cross'
        elif dif > dea:
            signal = 'bullish'
        elif dif < dea:
            signal = 'bearish'

    return {'dif': round(dif, 4) if dif else None,
            'dea': round(dea, 4) if dea else None,
            'macd_bar': round(macd_bar, 4) if macd_bar else None,
            'signal': signal}


def calc_rsi(closes: list, period: int = 14) -> float:
    """计算RSI"""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    # 使用最近period天
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_support_resistance(highs: list, lows: list, closes: list) -> dict:
    """
    计算支撑位和压力位
    方法：近60日高低点 + 均线位置
    """
    if len(closes) < 20:
        return {'support': [], 'resistance': []}

    current = closes[-1]
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else None

    # 近60日最高/最低
    recent_high = max(highs[-60:]) if len(highs) >= 60 else max(highs)
    recent_low = min(lows[-60:]) if len(lows) >= 60 else min(lows)

    # 近20日最高/最低
    high_20 = max(highs[-20:])
    low_20 = min(lows[-20:])

    supports = []
    resistances = []

    # 均线作为支撑/压力
    if ma20 and ma20 < current:
        supports.append(('20日均线', round(ma20, 2)))
    elif ma20 and ma20 > current:
        resistances.append(('20日均线', round(ma20, 2)))

    if ma60 and ma60 < current:
        supports.append(('60日均线', round(ma60, 2)))
    elif ma60 and ma60 > current:
        resistances.append(('60日均线', round(ma60, 2)))

    # 近期高低点
    if low_20 < current * 0.97:
        supports.append(('近20日低点', round(low_20, 2)))
    if high_20 > current * 1.03:
        resistances.append(('近20日高点', round(high_20, 2)))
    if recent_low < current * 0.95:
        supports.append(('近60日低点', round(recent_low, 2)))
    if recent_high > current * 1.05:
        resistances.append(('近60日高点', round(recent_high, 2)))

    # 按距离排序（最近的排前面）
    supports.sort(key=lambda x: current - x[1])
    resistances.sort(key=lambda x: x[1] - current)

    return {
        'support': supports[:3],
        'resistance': resistances[:3],
    }


def judge_ma_arrangement(closes: list) -> str:
    """判断均线排列"""
    ma5 = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else None

    if ma5 is None or ma20 is None:
        return 'insufficient_data'

    if ma60:
        if ma5 > ma20 > ma60:
            return 'bullish'  # 多头排列
        elif ma5 < ma20 < ma60:
            return 'bearish'  # 空头排列
    else:
        if ma5 > ma20:
            return 'bullish_short'
        elif ma5 < ma20:
            return 'bearish_short'

    return 'mixed'  # 交织


# ════════════════════════════════════════════════════════════
#  单只标的完整分析
# ════════════════════════════════════════════════════════════

def analyze_stock(code: str, name: str, shares: int, cost: float,
                  current_price: float = None, prev_close: float = None) -> dict:
    """
    对单只标的进行完整分析
    返回：技术面+基本面+盈亏+信号
    """
    result = {
        'code': code,
        'name': name,
        'shares': shares,
        'cost': cost,
    }

    # 获取历史数据
    hist = fetch_hist_data(code, days=120)
    if not hist:
        result['error'] = '历史数据获取失败'
        return result

    closes = [d['close'] for d in hist]
    highs = [d['high'] for d in hist]
    lows = [d['low'] for d in hist]

    # 当前价（优先用传入的实时价，否则用最后一根K线收盘价）
    price = current_price or closes[-1]
    prev = prev_close or (closes[-2] if len(closes) >= 2 else closes[-1])
    result['price'] = price
    result['prev_close'] = prev

    # ── 盈亏计算 ──
    result['pnl'] = {
        'today': round((price - prev) * shares, 2),
        'today_pct': round((price - prev) / prev * 100, 2) if prev else 0,
        'total': round((price - cost) * shares, 2),
        'total_pct': round((price - cost) / cost * 100, 2) if cost else 0,
        'market_value': round(price * shares, 2),
    }

    # ── 技术面 ──
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else None
    ma120 = calc_ma(closes, 120) if len(closes) >= 120 else None

    macd = calc_macd(closes)
    rsi = calc_rsi(closes, 14)
    ma_arrangement = judge_ma_arrangement(closes)
    sr = calc_support_resistance(highs, lows, closes)

    # 最近换手率
    recent_turnover = hist[-1].get('turnover_rate', 0) if hist else 0
    avg_turnover_5 = sum(d.get('turnover_rate', 0) for d in hist[-5:]) / 5 if len(hist) >= 5 else 0

    result['technical'] = {
        'ma5': round(ma5, 3) if ma5 else None,
        'ma10': round(ma10, 3) if ma10 else None,
        'ma20': round(ma20, 3) if ma20 else None,
        'ma60': round(ma60, 3) if ma60 else None,
        'ma120': round(ma120, 3) if ma120 else None,
        'macd': macd,
        'rsi_14': rsi,
        'ma_arrangement': ma_arrangement,
        'turnover_rate': round(recent_turnover, 2),
        'avg_turnover_5d': round(avg_turnover_5, 2),
        'support': sr['support'],
        'resistance': sr['resistance'],
    }

    # ── 基本面 ──
    fundamental = fetch_fundamental(code)
    result['fundamental'] = fundamental

    # ── 综合信号 ──
    signals = []
    # 止盈信号
    if result['pnl']['total_pct'] >= 50 and rsi and rsi >= 70:
        signals.append('🟡 止盈：浮盈>50%且RSI超买')
    elif result['pnl']['total_pct'] >= 30 and macd['signal'] == 'death_cross':
        signals.append('🟡 止盈：浮盈>30%且MACD死叉')
    # 止损信号
    if result['pnl']['total_pct'] <= -25:
        signals.append('🔴 止损：浮亏超-25%')
    elif result['pnl']['total_pct'] <= -15 and ma_arrangement == 'bearish':
        signals.append('🔴 止损：浮亏>15%且均线空头')
    # 加仓信号
    if ma_arrangement == 'bullish' and macd['signal'] in ('golden_cross', 'bullish') and rsi and rsi < 70:
        signals.append('🟢 加仓：多头排列+MACD看多+RSI未超买')
    # 观望信号
    if ma_arrangement == 'mixed' and abs(result['pnl']['today_pct']) < 1:
        signals.append('⏸️ 观望：方向不明，等待突破')

    result['signals'] = signals

    return result


# ════════════════════════════════════════════════════════════
#  组合汇总
# ════════════════════════════════════════════════════════════

def analyze_portfolio(target_code: str = None, summary_only: bool = False) -> dict:
    """
    分析完整持仓组合
    """
    holdings = load_holdings()

    # 获取实时价格
    all_codes = list(holdings.get('stocks', {}).keys()) + list(holdings.get('etfs', {}).keys())
    prices = {}
    if HAS_FETCHER:
        try:
            prices = get_a_stock_prices(all_codes)
        except Exception:
            pass

    results = []
    total_market_value = 0
    total_cost_value = 0
    total_today_pnl = 0
    total_pnl = 0

    # 分析个股
    for code, info in holdings.get('stocks', {}).items():
        if target_code and code != target_code:
            continue
        price_data = prices.get(code, {})
        r = analyze_stock(
            code=code,
            name=info['name'],
            shares=info['shares'],
            cost=info['cost'],
            current_price=price_data.get('price'),
            prev_close=price_data.get('prev_close') if 'prev_close' in price_data else None,
        )
        results.append(r)
        if 'pnl' in r:
            total_market_value += r['pnl']['market_value']
            total_cost_value += info['cost'] * info['shares']
            total_today_pnl += r['pnl']['today']
            total_pnl += r['pnl']['total']

    # 分析ETF
    for code, info in holdings.get('etfs', {}).items():
        if target_code and code != target_code:
            continue
        price_data = prices.get(code, {})
        r = analyze_stock(
            code=code,
            name=info['name'],
            shares=info['shares'],
            cost=info['cost'],
            current_price=price_data.get('price'),
            prev_close=price_data.get('prev_close') if 'prev_close' in price_data else None,
        )
        r['type'] = 'etf'
        results.append(r)
        if 'pnl' in r:
            total_market_value += r['pnl']['market_value']
            total_cost_value += info['cost'] * info['shares']
            total_today_pnl += r['pnl']['today']
            total_pnl += r['pnl']['total']

    # 组合汇总
    summary = {
        'total_market_value': round(total_market_value, 2),
        'total_cost_value': round(total_cost_value, 2),
        'total_today_pnl': round(total_today_pnl, 2),
        'total_today_pct': round(total_today_pnl / total_market_value * 100, 2) if total_market_value else 0,
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl / total_cost_value * 100, 2) if total_cost_value else 0,
        'holdings_count': len(results),
        'timestamp': datetime.now().isoformat(),
    }

    # 仓位占比
    for r in results:
        if 'pnl' in r and total_market_value > 0:
            r['position_pct'] = round(r['pnl']['market_value'] / total_market_value * 100, 1)

    # 贡献排名
    sorted_by_today = sorted([r for r in results if 'pnl' in r],
                             key=lambda x: x['pnl']['today'], reverse=True)
    summary['top_contributors'] = [
        {'name': r['name'], 'today_pnl': r['pnl']['today']}
        for r in sorted_by_today[:3]
    ]
    summary['top_drags'] = [
        {'name': r['name'], 'today_pnl': r['pnl']['today']}
        for r in sorted_by_today[-3:]
    ]

    # 风险提示
    risks = []
    for r in results:
        pos = r.get('position_pct', 0)
        if pos > 20:
            risks.append(f"{r['name']}占仓{pos}%（建议<20%）")
        pnl_pct = r.get('pnl', {}).get('total_pct', 0)
        if pnl_pct <= -25:
            risks.append(f"{r['name']}浮亏{pnl_pct:.1f}%（超止损线）")
    summary['risks'] = risks

    return {
        'summary': summary,
        'holdings': results if not summary_only else [],
    }


# ════════════════════════════════════════════════════════════
#  命令行入口
# ════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='持仓分析引擎')
    parser.add_argument('--code', help='分析单只标的（代码）')
    parser.add_argument('--summary', action='store_true', help='只输出汇总')
    parser.add_argument('--json', action='store_true', help='JSON格式输出')
    args = parser.parse_args()

    result = analyze_portfolio(target_code=args.code, summary_only=args.summary)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        s = result['summary']
        print(f"\n{'='*55}")
        print(f"📊 持仓分析 {s['timestamp'][:16]}")
        print(f"{'='*55}")
        print(f"💰 总市值：¥{s['total_market_value']:,.0f}")
        print(f"💰 今日盈亏：¥{s['total_today_pnl']:+,.0f}（{s['total_today_pct']:+.2f}%）")
        print(f"💰 累计浮盈：¥{s['total_pnl']:+,.0f}（{s['total_pnl_pct']:+.2f}%）")
        top_str = '  '.join(f"{c['name']}({c['today_pnl']:+,.0f})" for c in s['top_contributors'])
        drag_str = '  '.join(f"{c['name']}({c['today_pnl']:+,.0f})" for c in s['top_drags'])
        print(f"\n🔥 贡献TOP3：{top_str}")
        print(f"💧 拖累TOP3：{drag_str}")

        if s['risks']:
            print(f"\n⚠️ 风险提示：")
            for risk in s['risks']:
                print(f"  - {risk}")

        if not args.summary:
            print(f"\n{'─'*55}")
            for r in result['holdings']:
                if 'error' in r:
                    print(f"  ❌ {r['name']}({r['code']}): {r['error']}")
                    continue
                pnl = r.get('pnl', {})
                tech = r.get('technical', {})
                pos = r.get('position_pct', 0)
                emoji = "📈" if pnl.get('today', 0) >= 0 else "📉"
                print(f"\n  {emoji} {r['name']}({r['code']}) | 占仓{pos:.1f}%")
                print(f"     现价¥{r.get('price',0):.3f} | 今日{pnl.get('today_pct',0):+.2f}% ¥{pnl.get('today',0):+,.0f} | 总{pnl.get('total_pct',0):+.1f}% ¥{pnl.get('total',0):+,.0f}")
                if tech.get('macd'):
                    macd_signal = {'golden_cross':'金叉','death_cross':'死叉','bullish':'多头','bearish':'空头','neutral':'中性'}.get(tech['macd']['signal'], tech['macd']['signal'])
                    print(f"     MA排列:{tech.get('ma_arrangement','')} | MACD:{macd_signal} | RSI:{tech.get('rsi_14','-')}")
                if r.get('signals'):
                    for sig in r['signals']:
                        print(f"     {sig}")

        print(f"\n{'='*55}")


if __name__ == '__main__':
    main()
