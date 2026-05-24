#!/usr/bin/env python3
"""
链式外汇定存套利引擎 — fx_chain_deposit.py
汇丰香港「外币兑换及定期存款优惠」方案分析

机制：
  持有货币A → 换成货币B（享B的1周高利率）→ 到期后B → 换成货币C（享C的1周高利率）→ ...
  每周选"利率收益 + 汇率趋势 - 点差成本"综合最优的下一站货币。

决策公式：
  综合得分 = 1周利息净收益(%) + 汇率趋势得分(%) - 点差成本(%)
  其中：
    - 利息净收益 = 年利率 / 52（1周）
    - 汇率趋势 = 基于5日/20日均线动量的预估涨跌幅
    - 点差成本 = 单向换汇点差（约0.3%）

用法：
    python3 fx_chain_deposit.py                              # 默认NZD 15000
    python3 fx_chain_deposit.py --currency AUD --amount 8500 # 当前持有AUD
    python3 fx_chain_deposit.py --weeks 4                    # 模拟4周滚动
    python3 fx_chain_deposit.py --no-trend                   # 不考虑汇率趋势（纯利率比较）
    python3 fx_chain_deposit.py --json                       # JSON输出（供agent调用）

输出：
  各方案的利率收益、汇率趋势、点差损失、综合得分、推荐排名
"""

import json
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ════════════════════════════════════════════════════════════
#  汇丰定存利率表（固定，来源：汇丰香港官网 2026-03）
# ════════════════════════════════════════════════════════════

DEPOSIT_RATES = {
    # 货币: 1周年化利率（必须换入该货币才能享受）
    'AUD': 0.14,    # 14%
    'GBP': 0.14,    # 14%
    'CAD': 0.125,   # 12.5%
    'NZD': 0.125,   # 12.5%
    'CNY': 0.105,   # 10.5%
    'USD': 0.103,   # 10.3%
    'EUR': 0.068,   # 6.8%
    'HKD': 0.058,   # 5.8%
}

# 预估换汇点差（单向，汇丰牌价 vs 中间价）
SPREAD_ESTIMATE = 0.003  # 0.3%

# 汇率趋势权重（趋势得分乘以此系数后加入综合得分）
TREND_WEIGHT = 0.5  # 趋势预测不确定性高，打5折


# ════════════════════════════════════════════════════════════
#  汇率获取（实时 + 历史）
# ════════════════════════════════════════════════════════════

def _http_get(url: str, headers: dict = None, timeout: int = 10) -> str:
    """直连HTTP GET（不走代理）"""
    import urllib.request
    hdrs = headers or {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0"
    }
    req = urllib.request.Request(url, headers=hdrs)
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode('gbk', errors='replace')


def fetch_rate(from_cur: str, to_cur: str) -> float:
    """
    获取实时汇率：1 from_cur = ? to_cur
    数据源：新浪外汇
    """
    if from_cur == to_cur:
        return 1.0

    # 正向查询
    rate = _fetch_sina_rate(from_cur, to_cur)
    if rate:
        return rate

    # 反向查询
    reverse = _fetch_sina_rate(to_cur, from_cur)
    if reverse and reverse > 0:
        return 1.0 / reverse

    # USD中转
    if from_cur != 'USD' and to_cur != 'USD':
        r1 = fetch_rate(from_cur, 'USD')
        r2 = fetch_rate('USD', to_cur)
        if r1 and r2:
            return r1 * r2

    return None


def _fetch_sina_rate(from_cur: str, to_cur: str) -> float:
    """从新浪获取单个货币对汇率"""
    pair = f"{from_cur}{to_cur}"
    url = f"https://hq.sinajs.cn/list=fx_s{pair}"
    try:
        text = _http_get(url)
        if '=""' in text or not text.strip():
            return None
        data = text.split('"')[1] if '"' in text else ''
        fields = data.split(',')
        if len(fields) >= 2 and fields[1]:
            return float(fields[1])
    except Exception:
        pass
    return None


def fetch_historical_rates(from_cur: str, to_cur: str, days: int = 20) -> list:
    """
    获取历史汇率（近N天）用于趋势分析。
    数据源：新浪外汇日K线

    返回：[(date_str, close_rate), ...] 按日期升序
    """
    pair = f"{from_cur}{to_cur}"
    # 新浪外汇日K接口
    url = f"https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/data/NewForexService.getDayKLine?symbol=fx_s{pair}&_={int(datetime.now().timestamp()*1000)}"

    try:
        text = _http_get(url, timeout=15)
        # 解析 JSONP: data([{...}, ...])
        start = text.find('[')
        end = text.rfind(']') + 1
        if start < 0 or end <= 0:
            return []
        json_str = text[start:end]
        data = json.loads(json_str)

        # 取最近N天
        recent = data[-days:] if len(data) >= days else data
        result = []
        for item in recent:
            # 格式：{"d":"2026-05-20","o":"0.9123","h":"0.9150","l":"0.9100","c":"0.9135"}
            date_str = item.get('d', '')
            close = float(item.get('c', 0))
            if date_str and close > 0:
                result.append((date_str, close))
        return result
    except Exception:
        return []


# ════════════════════════════════════════════════════════════
#  汇率趋势分析
# ════════════════════════════════════════════════════════════

def analyze_trend(from_cur: str, to_cur: str) -> dict:
    """
    分析汇率趋势（from_cur → to_cur 方向）

    返回：
        {
            'direction': 'up' | 'down' | 'flat',
            'momentum_5d': float,   # 5日动量（%变化）
            'momentum_20d': float,  # 20日动量（%变化）
            'trend_score': float,   # 趋势得分（正=有利于换入to_cur，负=不利）
            'confidence': float,    # 置信度 0-1
            'note': str,            # 说明
        }
    """
    if from_cur == to_cur:
        return {'direction': 'flat', 'momentum_5d': 0, 'momentum_20d': 0,
                'trend_score': 0, 'confidence': 0, 'note': '同币种'}

    history = fetch_historical_rates(from_cur, to_cur, days=20)

    if len(history) < 5:
        # 数据不足，无法判断趋势
        return {
            'direction': 'unknown',
            'momentum_5d': 0,
            'momentum_20d': 0,
            'trend_score': 0,
            'confidence': 0,
            'note': '历史数据不足，无法判断趋势',
        }

    closes = [c for _, c in history]
    current = closes[-1]

    # 5日动量：(当前 - 5天前) / 5天前
    ref_5d = closes[-5] if len(closes) >= 5 else closes[0]
    momentum_5d = (current - ref_5d) / ref_5d * 100

    # 20日动量
    ref_20d = closes[0]
    momentum_20d = (current - ref_20d) / ref_20d * 100

    # 5日均线 vs 20日均线
    ma5 = sum(closes[-5:]) / min(5, len(closes[-5:]))
    ma20 = sum(closes) / len(closes)

    # 趋势得分计算：
    # 正分 = from_cur 对 to_cur 在升值（换入to_cur更便宜）→ 有利
    # 但我们要的是"换入to_cur后，to_cur会升值" → 需要反向看
    # 即：from→to 汇率上升 = from升值/to贬值 = 换入to后to会跌 = 不利
    # 所以趋势得分 = -momentum（汇率涨=不利）
    #
    # 等等，重新想：
    # 汇率定义：1 from = X to
    # 如果X在涨（from升值），意味着同样的from能换更多to → 现在换入to划算
    # 但换入to之后，如果to继续贬值（X继续涨），到期后to换成下一个货币时亏
    # 关键问题：定存只有1周，1周后to的价值变化才是风险
    #
    # 简化处理：
    # - 如果 to_cur 近期在走强（即 from→to 汇率在下降），说明to在升值
    #   → 换入to后，to可能继续升值 → 有利 → 正分
    # - 如果 to_cur 近期在走弱（即 from→to 汇率在上升），说明to在贬值
    #   → 换入to后，to可能继续贬值 → 不利 → 负分

    # 所以趋势得分 = -momentum_5d（汇率涨=to贬值=不利）
    # 用5日动量为主，20日为辅
    trend_score = -(momentum_5d * 0.7 + momentum_20d * 0.3)

    # 置信度：基于数据量和波动一致性
    if len(history) >= 15:
        confidence = 0.7
    elif len(history) >= 10:
        confidence = 0.5
    else:
        confidence = 0.3

    # MA交叉加强/减弱信号
    if ma5 > ma20:
        # 短期均线在长期上方 → from→to汇率短期偏高 → to偏弱 → 不利
        trend_score -= 0.1
        direction = 'down'  # to在走弱
    elif ma5 < ma20:
        # 短期均线在长期下方 → to偏强 → 有利
        trend_score += 0.1
        direction = 'up'  # to在走强
    else:
        direction = 'flat'

    # 生成说明
    if abs(trend_score) < 0.1:
        note = f'{to_cur}近期走势平稳'
        direction = 'flat'
    elif trend_score > 0:
        note = f'{to_cur}近期走强（5日+{abs(momentum_5d):.2f}%），换入有利'
    else:
        note = f'{to_cur}近期走弱（5日-{abs(momentum_5d):.2f}%），换入需谨慎'

    return {
        'direction': direction,
        'momentum_5d': round(momentum_5d, 3),
        'momentum_20d': round(momentum_20d, 3),
        'trend_score': round(trend_score, 3),
        'confidence': confidence,
        'note': note,
    }


# ════════════════════════════════════════════════════════════
#  综合决策引擎
# ════════════════════════════════════════════════════════════

def evaluate_options(amount: float, from_currency: str,
                     use_trend: bool = True) -> list:
    """
    评估所有可选目标货币，返回综合排名。

    综合得分 = 利率收益(%) - 点差成本(%) + 趋势得分(%) * TREND_WEIGHT

    返回：方案列表（按综合得分从高到低）
    """
    targets = [c for c in DEPOSIT_RATES.keys() if c != from_currency]
    options = []

    for target in targets:
        rate = fetch_rate(from_currency, target)
        if not rate:
            continue

        # 1周利率收益（%）
        annual_rate = DEPOSIT_RATES[target]
        weekly_rate_pct = annual_rate / 52 * 100  # 转为百分比

        # 点差成本（%）
        spread_pct = SPREAD_ESTIMATE * 100

        # 利率净收益（%）
        rate_net_pct = weekly_rate_pct - spread_pct

        # 汇率趋势
        if use_trend:
            trend = analyze_trend(from_currency, target)
        else:
            trend = {'direction': 'unknown', 'momentum_5d': 0,
                     'momentum_20d': 0, 'trend_score': 0,
                     'confidence': 0, 'note': '未启用趋势分析'}

        # 综合得分
        trend_contribution = trend['trend_score'] * TREND_WEIGHT * trend['confidence']
        composite_score = rate_net_pct + trend_contribution

        # 金额计算
        amount_converted = amount * rate
        spread_cost = amount_converted * SPREAD_ESTIMATE
        net_principal = amount_converted - spread_cost
        interest = net_principal * annual_rate / 52

        options.append({
            'target': target,
            'rate': round(rate, 6),
            'annual_rate': annual_rate,
            'annual_rate_pct': f"{annual_rate*100:.1f}%",
            'weekly_rate_pct': round(weekly_rate_pct, 4),
            'spread_pct': round(spread_pct, 2),
            'rate_net_pct': round(rate_net_pct, 4),
            'trend': trend,
            'trend_contribution': round(trend_contribution, 4),
            'composite_score': round(composite_score, 4),
            # 金额明细
            'amount_converted': round(amount_converted, 2),
            'spread_cost': round(spread_cost, 2),
            'net_principal': round(net_principal, 2),
            'interest': round(interest, 2),
            'net_gain': round(interest - spread_cost, 2),
        })

    options.sort(key=lambda x: x['composite_score'], reverse=True)
    return options


def simulate_chain(initial_amount: float, initial_currency: str,
                   weeks: int = 4, use_trend: bool = True) -> dict:
    """
    模拟多周链式定存。

    每周选综合得分最高的目标货币，到期后继续换下一个最优。

    返回：
        {
            'records': [...],          # 每周操作记录
            'final_currency': str,
            'final_amount': float,
            'total_interest': float,
            'total_spread_cost': float,
            'total_net_gain': float,
        }
    """
    records = []
    current_amount = initial_amount
    current_currency = initial_currency

    for week in range(1, weeks + 1):
        options = evaluate_options(current_amount, current_currency, use_trend)
        if not options:
            records.append({'week': week, 'error': f'无法获取{current_currency}汇率'})
            break

        chosen = options[0]

        records.append({
            'week': week,
            'from': current_currency,
            'from_amount': round(current_amount, 2),
            'to': chosen['target'],
            'rate': chosen['rate'],
            'annual_rate_pct': chosen['annual_rate_pct'],
            'to_amount': chosen['amount_converted'],
            'interest': chosen['interest'],
            'spread_cost': chosen['spread_cost'],
            'net_gain': chosen['net_gain'],
            'composite_score': chosen['composite_score'],
            'trend_note': chosen['trend']['note'],
        })

        # 下周本金 = 净本金 + 利息
        current_amount = chosen['net_principal'] + chosen['interest']
        current_currency = chosen['target']

    if records and 'error' not in records[-1]:
        total_interest = sum(r.get('interest', 0) for r in records)
        total_spread = sum(r.get('spread_cost', 0) for r in records)
        return {
            'records': records,
            'initial': f"{initial_currency} {initial_amount:,.2f}",
            'final_currency': current_currency,
            'final_amount': round(current_amount, 2),
            'total_interest': round(total_interest, 2),
            'total_spread_cost': round(total_spread, 2),
            'total_net_gain': round(total_interest - total_spread, 2),
            'weeks': weeks,
        }

    return {'records': records, 'error': '模拟中断'}


# ════════════════════════════════════════════════════════════
#  命令行入口
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='链式外汇定存套利引擎（汇丰香港）')
    parser.add_argument('--currency', default='NZD',
                        help='当前持有货币（默认NZD）')
    parser.add_argument('--amount', type=float, default=15000,
                        help='当前持有金额（默认15000）')
    parser.add_argument('--weeks', type=int, default=0,
                        help='模拟滚动周数（0=只看本周推荐）')
    parser.add_argument('--no-trend', action='store_true',
                        help='不使用汇率趋势分析（纯利率比较）')
    parser.add_argument('--json', action='store_true',
                        help='JSON格式输出（供agent调用）')
    args = parser.parse_args()

    use_trend = not args.no_trend

    if args.weeks > 0:
        # ── 多周链式模拟 ──
        result = simulate_chain(args.amount, args.currency, args.weeks, use_trend)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        print(f"\n{'═'*65}")
        print(f"  💱 链式外汇定存 — {args.weeks}周滚动模拟")
        print(f"{'═'*65}")
        print(f"  起始：{args.currency} {args.amount:,.2f}")
        print(f"  策略：每周选综合得分最高的货币{'（含趋势）' if use_trend else '（纯利率）'}")
        print(f"{'─'*65}")

        if 'error' in result:
            print(f"  ⚠️ {result['error']}")
        else:
            for r in result['records']:
                if 'error' in r:
                    print(f"  第{r['week']}周：{r['error']}")
                else:
                    print(f"  第{r['week']}周：{r['from']} {r['from_amount']:>10,.2f} → {r['to']}"
                          f"（{r['annual_rate_pct']}）"
                          f" | 利息+{r['interest']:.2f}"
                          f" | 点差-{r['spread_cost']:.2f}"
                          f" | 得分{r['composite_score']:+.3f}")
                    if use_trend:
                        print(f"         趋势：{r['trend_note']}")
            print(f"{'─'*65}")
            print(f"  最终持有：{result['final_currency']} {result['final_amount']:,.2f}")
            print(f"  累计利息：+{result['total_interest']:.2f}")
            print(f"  累计点差：-{result['total_spread_cost']:.2f}")
            print(f"  净收益：  +{result['total_net_gain']:.2f}")
        print(f"{'═'*65}\n")

    else:
        # ── 本周推荐 ──
        options = evaluate_options(args.amount, args.currency, use_trend)

        if args.json:
            print(json.dumps(options, ensure_ascii=False, indent=2))
            return

        if not options:
            print("⚠️ 无法获取汇率数据")
            return

        print(f"\n{'═'*75}")
        print(f"  💱 链式外汇定存 — 本周推荐")
        print(f"{'═'*75}")
        print(f"  当前持有：{args.currency} {args.amount:,.2f}")
        print(f"  点差预估：{SPREAD_ESTIMATE*100:.1f}%（单向）")
        print(f"  趋势分析：{'启用' if use_trend else '关闭'}")
        print(f"{'─'*75}")
        print(f"  {'排名':<4} {'目标':<5} {'年利率':<7} {'周利率%':<8} {'趋势':<8} {'综合得分':<9} {'净收益':<10} {'趋势说明'}")
        print(f"{'─'*75}")

        medals = ['🥇', '🥈', '🥉']
        for i, opt in enumerate(options):
            medal = medals[i] if i < 3 else f"  {i+1}."
            trend_dir = {'up': '↑', 'down': '↓', 'flat': '→', 'unknown': '?'}
            trend_arrow = trend_dir.get(opt['trend']['direction'], '?')
            print(f"  {medal} {opt['target']:<5} {opt['annual_rate_pct']:<7}"
                  f" {opt['weekly_rate_pct']:<8.4f}"
                  f" {trend_arrow:<8}"
                  f" {opt['composite_score']:>+8.4f}"
                  f" {opt['net_gain']:>+9.2f}"
                  f"  {opt['trend']['note']}")

        print(f"{'─'*75}")
        best = options[0]
        print(f"\n  🎯 推荐：换入 {best['target']}")
        print(f"     理由：年利率{best['annual_rate_pct']}，"
              f"综合得分{best['composite_score']:+.4f}，"
              f"预估净收益 +{best['net_gain']:.2f} {best['target']}")
        if use_trend:
            print(f"     趋势：{best['trend']['note']}")

        if len(options) >= 2:
            runner = options[1]
            diff = best['composite_score'] - runner['composite_score']
            if diff < 0.02:
                print(f"\n  ⚠️ 次选 {runner['target']} 得分接近（差{diff:.4f}），"
                      f"可根据个人判断选择")

        print(f"\n{'═'*75}\n")


if __name__ == '__main__':
    main()
