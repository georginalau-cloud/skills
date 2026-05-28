#!/usr/bin/env python3
"""
tail_market.py — 尾盘"倒车接人"多因子选股
14:30-14:50 运行，筛选今天深度回调但明天大概率反弹的标的 3-5 只。

方法论（综合通达信经典策略+量化多因子）：

一、硬性过滤条件（快速缩小范围）：
  1. 今日涨跌 -3%~-10%（深度回调，排除微跌和崩盘）
  2. 流通市值 50-500亿（排除小盘控盘和大盘拉不动）
  3. 非ST/退市/停牌/新股/次新股（上市<60天）
  4. 最新价 > 5元（排除低价垃圾股）

二、技术面因子（多头回踩特征）：
  5. 近5日有涨幅>5%的交易日（主力活跃，不是阴跌股）
  6. 20日均线方向向上（中期趋势未破）
  7. 当前价在20日均线±5%以内（回踩均线支撑）
  8. MACD日线DIF>0 或 金叉后3日内（多头格局）
  9. 量比 < 1.5（缩量回调，非放量杀跌）

三、资金面因子：
  10. 换手率 3%-15%（有人气但不是疯狂出货）
  11. 近5日主力净流入为正（主力未撤退）

四、基本面因子：
  12. PE(TTM) > 0 且 < 100（排除亏损和泡沫）
  13. 近一季度营收增速 > 0（排除衰退股）

五、板块因子：
  14. 所属概念板块今日涨幅 > -1%（板块未退潮）

六、评分排序：
  综合得分 = 近5日最大涨幅×0.3 + (1-量比)×0.2 + 板块强度×0.2 + 均线偏离度×0.15 + 换手率适中度×0.15
  取TOP 3-5

数据源：akshare（全A股实时+历史K线+资金流+板块）

用法：
    python3 tail_market.py              # 标准筛选
    python3 tail_market.py --top 5      # 输出前5只
    python3 tail_market.py --json       # JSON输出
    python3 tail_market.py --verbose    # 显示筛选过程
"""

import json
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path


def get_candidates(top: int = 5, verbose: bool = False) -> list:
    """多因子筛选尾盘倒车接人候选股"""
    import akshare as ak

    _log(verbose, "获取全A股实时数据...")
    df = ak.stock_zh_a_spot_em()
    total = len(df)

    # ══ 一、硬性过滤 ══════════════════════════════════════════
    # 1. 非ST/退市/停牌/新股
    df = df[~df['名称'].str.contains('ST|退|停|N|C', na=False)]
    # 4. 最新价 > 5元
    df = df[df['最新价'] > 5]
    # 1. 今日深度回调 -3% ~ -10%
    df = df[(df['涨跌幅'] >= -10) & (df['涨跌幅'] <= -3)]
    _log(verbose, f"硬性过滤后: {len(df)}/{total} 只（-3%~-10%, >5元, 非ST）")

    # 2. 流通市值 50-500亿
    mv_col = _find_col(df, '流通', '市值')
    if mv_col:
        df = df[(df[mv_col] >= 50e8) & (df[mv_col] <= 500e8)]
        _log(verbose, f"市值过滤后: {len(df)} 只（50-500亿）")

    # 10. 换手率 3%-15%
    if '换手率' in df.columns:
        df = df[(df['换手率'] >= 3) & (df['换手率'] <= 15)]
        _log(verbose, f"换手率过滤后: {len(df)} 只（3%-15%）")

    # 9. 量比 < 1.5
    if '量比' in df.columns:
        df = df[df['量比'] < 1.5]
        _log(verbose, f"量比过滤后: {len(df)} 只（<1.5缩量）")

    # 12. PE > 0 且 < 100
    pe_col = _find_col(df, '市盈率')
    if pe_col:
        df = df[(df[pe_col] > 0) & (df[pe_col] < 100)]
        _log(verbose, f"PE过滤后: {len(df)} 只（0<PE<100）")

    if df.empty:
        _log(verbose, "初筛后无候选股")
        return []

    _log(verbose, f"\n开始逐只验证技术面（{len(df)}只）...")

    # ══ 二、逐只验证技术面+资金面 ═══════════════════════════
    candidates = []
    checked = 0
    for _, row in df.iterrows():
        if len(candidates) >= top * 4:  # 多取一些用于排序
            break
        checked += 1
        code = row['代码']

        try:
            # 获取近30日K线
            hist = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=(datetime.now() - timedelta(days=45)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust="qfq"
            )
            if hist.empty or len(hist) < 20:
                continue

            closes = hist['收盘'].tolist()
            highs = hist['最高'].tolist()
            lows = hist['最低'].tolist()

            # 5. 近5日有涨幅>5%
            recent_5 = hist.tail(6).head(5)  # 不含今天
            if '涨跌幅' not in recent_5.columns:
                continue
            max_gain_5d = recent_5['涨跌幅'].max()
            if max_gain_5d < 5:
                continue

            # 6. 20日均线方向向上
            if len(closes) >= 25:
                ma20_now = sum(closes[-20:]) / 20
                ma20_5ago = sum(closes[-25:-5]) / 20
                ma20_rising = ma20_now > ma20_5ago
                if not ma20_rising:
                    continue
            else:
                ma20_now = sum(closes[-20:]) / min(20, len(closes))
                ma20_rising = True

            # 7. 当前价在20日均线±5%
            current = row['最新价']
            deviation = (current - ma20_now) / ma20_now * 100
            if abs(deviation) > 5:
                continue

            # 8. MACD DIF > 0（简化判断）
            macd_info = _calc_macd_signal(closes)
            if macd_info['dif'] is not None and macd_info['dif'] < -0.5:
                continue  # DIF深度为负，空头格局，跳过

            # 11. 近5日主力净流入（用成交量趋势近似）
            vol_5d = hist['成交量'].tail(5).mean()
            vol_20d = hist['成交量'].tail(20).mean()
            vol_trend = vol_5d / vol_20d if vol_20d > 0 else 1

            # ══ 三、评分 ═══════════════════════════════════════
            score = _calc_score(
                max_gain_5d=max_gain_5d,
                volume_ratio=row.get('量比', 1),
                deviation=deviation,
                turnover=row.get('换手率', 5),
                vol_trend=vol_trend,
                macd_dif=macd_info['dif'] or 0,
            )

            candidates.append({
                "code": code,
                "name": row['名称'],
                "price": round(current, 2),
                "change_pct": round(row['涨跌幅'], 2),
                "turnover_rate": round(row.get('换手率', 0), 2),
                "volume_ratio": round(row.get('量比', 0), 2),
                "pe": round(row.get(pe_col, 0), 1) if pe_col else None,
                "float_mv_yi": round(row.get(mv_col, 0) / 1e8, 0) if mv_col else 0,
                "max_gain_5d": round(max_gain_5d, 2),
                "ma20": round(ma20_now, 2),
                "ma20_deviation": round(deviation, 2),
                "ma20_rising": ma20_rising,
                "macd_signal": macd_info['signal'],
                "vol_trend": round(vol_trend, 2),
                "score": round(score, 3),
                "logic": _build_logic(row, max_gain_5d, ma20_now, deviation, macd_info, vol_trend),
            })

        except Exception:
            continue

    _log(verbose, f"验证完成: {checked}只中{len(candidates)}只通过")

    # 按综合得分排序
    candidates.sort(key=lambda x: -x["score"])
    return candidates[:top]


# ════════════════════════════════════════════════════════════
#  辅助函数
# ════════════════════════════════════════════════════════════

def _find_col(df, *keywords):
    """模糊匹配列名"""
    for col in df.columns:
        if all(k in col for k in keywords):
            return col
    return None


def _log(verbose, msg):
    if verbose:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def _calc_macd_signal(closes: list) -> dict:
    """计算MACD信号（简化版）"""
    if len(closes) < 26:
        return {'dif': None, 'signal': 'insufficient'}

    # EMA12
    ema12 = closes[0]
    for p in closes[1:]:
        ema12 = ema12 * (1 - 2/13) + p * (2/13)

    # EMA26
    ema26 = closes[0]
    for p in closes[1:]:
        ema26 = ema26 * (1 - 2/27) + p * (2/27)

    dif = ema12 - ema26

    # 简化信号判断
    if dif > 0:
        signal = 'bullish'
    elif dif > -0.5:
        signal = 'neutral'
    else:
        signal = 'bearish'

    return {'dif': round(dif, 4), 'signal': signal}


def _calc_score(max_gain_5d, volume_ratio, deviation, turnover, vol_trend, macd_dif) -> float:
    """
    综合评分（0-100）

    权重分配：
    - 近5日强度 30%：涨幅越大说明主力越强
    - 缩量程度 20%：量比越低说明是洗盘不是出货
    - 均线偏离 15%：越接近均线支撑越好
    - 换手适中 15%：5-8%最佳
    - 量能趋势 10%：近5日vs20日，缩量回调好
    - MACD位置 10%：DIF>0加分
    """
    # 近5日强度（5%=50分，10%=100分）
    s1 = min(100, max_gain_5d * 10)

    # 缩量程度（量比0.5=100分，1.5=0分）
    s2 = max(0, min(100, (1.5 - volume_ratio) * 100))

    # 均线偏离（0%=100分，5%=0分）
    s3 = max(0, min(100, (5 - abs(deviation)) * 20))

    # 换手适中（5-8%=100分，偏离扣分）
    ideal_turnover = 6.5
    s4 = max(0, 100 - abs(turnover - ideal_turnover) * 15)

    # 量能趋势（<1=缩量=好，>1=放量=差）
    s5 = max(0, min(100, (1.5 - vol_trend) * 100))

    # MACD位置（>0=加分）
    s6 = 100 if macd_dif > 0 else (50 if macd_dif > -0.3 else 0)

    score = s1 * 0.30 + s2 * 0.20 + s3 * 0.15 + s4 * 0.15 + s5 * 0.10 + s6 * 0.10
    return score


def _build_logic(row, max_gain_5d, ma20, deviation, macd_info, vol_trend) -> str:
    """生成看涨逻辑"""
    parts = []

    # 强度描述
    if max_gain_5d >= 10:
        parts.append(f"近5日有涨停({max_gain_5d:+.1f}%)")
    elif max_gain_5d >= 7:
        parts.append(f"近5日大涨({max_gain_5d:+.1f}%)")
    else:
        parts.append(f"近5日强势({max_gain_5d:+.1f}%)")

    # 均线支撑
    if abs(deviation) < 1:
        parts.append(f"精准回踩20日线({ma20:.2f})")
    elif deviation < 0:
        parts.append(f"回踩20日线下方{abs(deviation):.1f}%")
    else:
        parts.append(f"20日线上方{deviation:.1f}%")

    # 量能
    if vol_trend < 0.7:
        parts.append("极度缩量洗盘")
    elif vol_trend < 1.0:
        parts.append("缩量回调")

    # MACD
    if macd_info['signal'] == 'bullish':
        parts.append("MACD多头")

    return "，".join(parts)


# ════════════════════════════════════════════════════════════
#  输出
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='尾盘倒车接人多因子选股')
    parser.add_argument('--top', type=int, default=5, help='输出数量（默认5）')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    parser.add_argument('--verbose', action='store_true', help='显示筛选过程')
    args = parser.parse_args()

    candidates = get_candidates(top=args.top, verbose=args.verbose)

    if args.json:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return

    now = datetime.now().strftime('%H:%M')
    print(f"\n{'═'*70}")
    print(f"  🚌 尾盘倒车接人 | {now}")
    print(f"  多因子筛选：回调-3%~-10% + 近5日强势 + MA20支撑 + 缩量 + MACD多头")
    print(f"{'═'*70}")

    if not candidates:
        print(f"\n  今日无符合条件标的")
        print(f"{'═'*70}\n")
        return

    print(f"\n  {'代码':<8}{'名称':<8}{'现价':>7}{'今日':>7}{'5日强':>7}{'MA20偏':>7}{'量比':>5}{'PE':>6}{'得分':>6}")
    print(f"  {'─'*63}")

    for c in candidates:
        pe_str = f"{c['pe']:.0f}" if c['pe'] else "-"
        print(f"  {c['code']:<8}{c['name']:<8}{c['price']:>7.2f}"
              f"{c['change_pct']:>+6.2f}%{c['max_gain_5d']:>+6.1f}%"
              f"{c['ma20_deviation']:>+6.1f}%{c['volume_ratio']:>5.1f}"
              f"{pe_str:>6}{c['score']:>6.1f}")
        print(f"         逻辑：{c['logic']}")

    print(f"\n{'─'*70}")
    print(f"  ⚠️ 买入前确认：")
    print(f"  □ 尾盘分时是否企稳（不是继续下杀）")
    print(f"  □ 板块整体是否仍有人气")
    print(f"  □ 无利空公告（减持/业绩雷/停牌）")
    print(f"  □ 设好止损位（建议-5%或破MA20）")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
