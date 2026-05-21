#!/usr/bin/env python3
"""
外汇互换定存套利计算器 — nzd_deposit_calculator.py
汇丰香港「外币兑换及定期存款优惠」方案分析

机制：
  持有货币A → 换成货币B → B定存1周（享高年利率）→ 到期后B → 换成货币C → C定存1周 → ...
  每周一换，利息滚入本金，持续套利。

用法：
    python3 nzd_deposit_calculator.py                          # 默认NZD 15000
    python3 nzd_deposit_calculator.py --currency AUD --amount 8500  # 当前持有AUD 8500
    python3 nzd_deposit_calculator.py --weeks 4                # 模拟4周滚动收益
    python3 nzd_deposit_calculator.py --json                   # JSON输出

输出：
  各方案的1周利息收益、预估点差损失、净收益、汇率趋势、推荐排名
"""

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "shared"))

# ════════════════════════════════════════════════════════════
#  汇丰定存利率表（固定，来源：汇丰香港 2026-03-30）
# ════════════════════════════════════════════════════════════

DEPOSIT_RATES = {
    # 货币: {1周年利率, 1月年利率}
    'AUD': {'1w': 0.14,   '1m': 0.033},
    'CAD': {'1w': 0.125,  '1m': 0.033},
    'GBP': {'1w': 0.14,   '1m': 0.033},
    'EUR': {'1w': 0.068,  '1m': 0.028},
    'NZD': {'1w': 0.125,  '1m': 0.033},
    'CNY': {'1w': 0.105,  '1m': 0.033},
    'USD': {'1w': 0.103,  '1m': 0.043},
    'HKD': {'1w': 0.058,  '1m': 0.028},
}

# 注意：NZD行的利率是给"其他货币换成NZD"的人用的
# 如果你当前持有NZD，不能直接享受NZD 12.5%，必须换出去

# 预估换汇点差（单向，汇丰牌价 vs 中间价的差距）
SPREAD_ESTIMATE = 0.003  # 0.3% 单向点差（保守估计）


# ════════════════════════════════════════════════════════════
#  汇率获取
# ════════════════════════════════════════════════════════════

def fetch_exchange_rates(base_currency: str) -> dict:
    """
    获取 base_currency 对所有目标货币的汇率
    返回: {目标货币: 汇率}（1单位base = X单位目标）
    """
    # 使用新浪外汇接口获取实时汇率
    import urllib.request

    # 构建货币对列表
    targets = [c for c in DEPOSIT_RATES.keys() if c != base_currency]
    rates = {}

    for target in targets:
        rate = _get_rate_pair(base_currency, target)
        if rate:
            rates[target] = rate

    return rates


def _get_rate_pair(from_cur: str, to_cur: str) -> float:
    """获取单个货币对的汇率（1 from = ? to）"""
    import urllib.request

    # 新浪外汇接口格式
    pair = f"{from_cur}{to_cur}"
    url = f"https://hq.sinajs.cn/list=fx_s{pair}"
    headers = {"Referer": "https://finance.sina.com.cn",
               "User-Agent": "Mozilla/5.0"}

    try:
        req = urllib.request.Request(url, headers=headers)
        # 直连模式（不走代理）
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(req, timeout=10) as resp:
            text = resp.read().decode('gbk')

        if '=""' in text or not text.strip():
            # 新浪没有这个货币对，尝试反向
            return _get_rate_reverse(from_cur, to_cur)

        # 解析：字段[1]=当前价
        data = text.split('"')[1] if '"' in text else ''
        fields = data.split(',')
        if len(fields) >= 2 and fields[1]:
            return float(fields[1])
    except Exception:
        pass

    # 尝试反向计算
    return _get_rate_reverse(from_cur, to_cur)


def _get_rate_reverse(from_cur: str, to_cur: str) -> float:
    """通过反向货币对计算汇率"""
    import urllib.request

    pair = f"{to_cur}{from_cur}"
    url = f"https://hq.sinajs.cn/list=fx_s{pair}"
    headers = {"Referer": "https://finance.sina.com.cn",
               "User-Agent": "Mozilla/5.0"}

    try:
        req = urllib.request.Request(url, headers=headers)
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(req, timeout=10) as resp:
            text = resp.read().decode('gbk')

        if '=""' in text or not text.strip():
            return None

        data = text.split('"')[1] if '"' in text else ''
        fields = data.split(',')
        if len(fields) >= 2 and fields[1]:
            reverse_rate = float(fields[1])
            if reverse_rate > 0:
                return 1.0 / reverse_rate
    except Exception:
        pass

    # 最终兜底：通过USD中转
    return _get_rate_via_usd(from_cur, to_cur)


def _get_rate_via_usd(from_cur: str, to_cur: str) -> float:
    """通过USD中转计算交叉汇率"""
    if from_cur == 'USD' or to_cur == 'USD':
        return None

    from_to_usd = _get_rate_pair(from_cur, 'USD')
    usd_to_target = _get_rate_pair('USD', to_cur)

    if from_to_usd and usd_to_target:
        return from_to_usd * usd_to_target
    return None


# ════════════════════════════════════════════════════════════
#  收益计算
# ════════════════════════════════════════════════════════════

def calculate_weekly_return(amount: float, from_currency: str,
                           to_currency: str, rate: float,
                           period: str = '1w') -> dict:
    """
    计算换汇+定存1周的收益

    参数：
        amount: 当前持有金额（from_currency 计价）
        from_currency: 当前持有货币
        to_currency: 目标货币
        rate: 汇率（1 from = rate to）
        period: '1w' 或 '1m'

    返回：
        {
            'to_currency': 目标货币,
            'rate': 使用的汇率,
            'amount_converted': 换汇后金额（目标货币）,
            'spread_cost': 点差损失（目标货币）,
            'net_principal': 实际入存金额,
            'annual_rate': 年利率,
            'interest': 利息收入（目标货币）,
            'net_gain': 净收益（利息-点差，目标货币）,
            'net_gain_pct': 净收益率,
            'equivalent_annual_rate': 等效年化收益率（扣除点差后）,
        }
    """
    annual_rate = DEPOSIT_RATES[to_currency][period]
    weeks = 1 if period == '1w' else 4.33

    # 换汇（扣除点差）
    amount_converted = amount * rate
    spread_cost = amount_converted * SPREAD_ESTIMATE
    net_principal = amount_converted - spread_cost

    # 利息
    interest = net_principal * annual_rate / 52 * (1 if period == '1w' else 4.33)

    # 净收益
    net_gain = interest - spread_cost  # 利息 - 点差
    net_gain_pct = net_gain / amount_converted * 100 if amount_converted else 0

    # 等效年化（扣除点差后的真实年化收益）
    equivalent_annual = net_gain_pct * 52 if period == '1w' else net_gain_pct * 12

    return {
        'to_currency': to_currency,
        'rate': round(rate, 6),
        'amount_converted': round(amount_converted, 2),
        'spread_cost': round(spread_cost, 2),
        'net_principal': round(net_principal, 2),
        'annual_rate': annual_rate,
        'annual_rate_pct': f"{annual_rate*100:.1f}%",
        'interest': round(interest, 2),
        'net_gain': round(net_gain, 2),
        'net_gain_pct': round(net_gain_pct, 4),
        'equivalent_annual_rate': round(equivalent_annual, 2),
    }


def analyze_all_options(amount: float, from_currency: str,
                        period: str = '1w') -> list:
    """
    分析所有可换汇方案，按净收益排序

    返回：方案列表（按净收益从高到低）
    """
    rates = fetch_exchange_rates(from_currency)
    if not rates:
        return []

    options = []
    for target, rate in rates.items():
        if target == from_currency:
            continue
        result = calculate_weekly_return(amount, from_currency, target, rate, period)
        options.append(result)

    # 按净收益排序
    options.sort(key=lambda x: x['net_gain'], reverse=True)
    return options


def simulate_rolling(initial_amount: float, initial_currency: str,
                     weeks: int = 4, strategy: str = 'best') -> list:
    """
    模拟多周滚动定存

    strategy:
        'best' — 每周选净收益最高的货币
        'stable' — 每周选同一个高利率货币（AUD/GBP）

    返回：每周的操作记录
    """
    records = []
    current_amount = initial_amount
    current_currency = initial_currency

    for week in range(1, weeks + 1):
        options = analyze_all_options(current_amount, current_currency, '1w')
        if not options:
            records.append({
                'week': week,
                'error': f'无法获取{current_currency}的汇率数据'
            })
            break

        if strategy == 'best':
            chosen = options[0]  # 净收益最高
        elif strategy == 'stable':
            # 优先选 AUD/GBP（14%），其次 CAD/NZD（12.5%）
            preferred = ['AUD', 'GBP', 'CAD', 'NZD']
            chosen = options[0]
            for pref in preferred:
                match = [o for o in options if o['to_currency'] == pref]
                if match:
                    chosen = match[0]
                    break

        records.append({
            'week': week,
            'from': current_currency,
            'from_amount': round(current_amount, 2),
            'to': chosen['to_currency'],
            'rate': chosen['rate'],
            'to_amount': chosen['amount_converted'],
            'interest': chosen['interest'],
            'spread_cost': chosen['spread_cost'],
            'net_gain': chosen['net_gain'],
        })

        # 下周的本金 = 换汇后金额 + 利息（利息滚入）
        current_amount = chosen['net_principal'] + chosen['interest']
        current_currency = chosen['to_currency']

    # 计算总收益
    if records and 'error' not in records[-1]:
        # 最终金额换回初始货币估算
        final_amount = current_amount
        total_interest = sum(r.get('interest', 0) for r in records)
        total_spread = sum(r.get('spread_cost', 0) for r in records)

        return {
            'records': records,
            'final_currency': current_currency,
            'final_amount': round(final_amount, 2),
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
    parser = argparse.ArgumentParser(description='外汇互换定存套利计算器')
    parser.add_argument('--currency', default='NZD', help='当前持有货币（默认NZD）')
    parser.add_argument('--amount', type=float, default=15000, help='当前持有金额（默认15000）')
    parser.add_argument('--period', default='1w', choices=['1w', '1m'], help='定存期限')
    parser.add_argument('--weeks', type=int, default=0, help='模拟滚动周数（0=只看本周）')
    parser.add_argument('--json', action='store_true', help='JSON格式输出')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"💱 外汇互换定存套利分析")
    print(f"{'='*60}")
    print(f"当前持有：{args.currency} {args.amount:,.2f}")
    print(f"定存期限：{'1周' if args.period == '1w' else '1个月'}")
    print(f"预估单向点差：{SPREAD_ESTIMATE*100:.1f}%")
    print(f"{'='*60}\n")

    if args.weeks > 0:
        # 滚动模拟
        result = simulate_rolling(args.amount, args.currency, args.weeks)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if 'error' in result:
                print(f"⚠️ {result['error']}")
            else:
                print(f"📊 {args.weeks}周滚动模拟（每周选最优）：\n")
                for r in result['records']:
                    if 'error' in r:
                        print(f"  第{r['week']}周：{r['error']}")
                    else:
                        print(f"  第{r['week']}周：{r['from']} {r['from_amount']:,.2f} → {r['to']}（利率{DEPOSIT_RATES[r['to']]['1w']*100:.1f}%）| 利息+{r['interest']:.2f} | 点差-{r['spread_cost']:.2f}")
                print(f"\n{'─'*60}")
                print(f"  最终持有：{result['final_currency']} {result['final_amount']:,.2f}")
                print(f"  累计利息：+{result['total_interest']:.2f}")
                print(f"  累计点差：-{result['total_spread_cost']:.2f}")
                print(f"  净收益：+{result['total_net_gain']:.2f}")
    else:
        # 本周方案对比
        options = analyze_all_options(args.amount, args.currency, args.period)

        if not options:
            print("⚠️ 无法获取汇率数据")
            return

        if args.json:
            print(json.dumps(options, ensure_ascii=False, indent=2))
        else:
            print(f"{'─'*60}")
            print(f"{'目标货币':<8} {'年利率':<8} {'换汇后金额':<14} {'利息':<10} {'点差':<10} {'净收益':<10} {'等效年化':<8}")
            print(f"{'─'*60}")
            for i, opt in enumerate(options):
                marker = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "  "
                print(f"{marker} {opt['to_currency']:<6} {opt['annual_rate_pct']:<8} "
                      f"{opt['amount_converted']:>10,.2f}  "
                      f"+{opt['interest']:>6,.2f}  "
                      f"-{opt['spread_cost']:>6,.2f}  "
                      f"{opt['net_gain']:>+8,.2f}  "
                      f"{opt['equivalent_annual_rate']:>+.1f}%")
            print(f"{'─'*60}")
            print(f"\n🎯 推荐：换成 {options[0]['to_currency']}（净收益最高 +{options[0]['net_gain']:.2f}，等效年化 {options[0]['equivalent_annual_rate']:.1f}%）")

            if len(options) >= 2 and options[0]['net_gain'] - options[1]['net_gain'] < 1:
                print(f"   备选：{options[1]['to_currency']}（差距仅 {options[0]['net_gain'] - options[1]['net_gain']:.2f}，可考虑汇率趋势选择）")

    print(f"\n{'='*60}")


if __name__ == '__main__':
    main()
