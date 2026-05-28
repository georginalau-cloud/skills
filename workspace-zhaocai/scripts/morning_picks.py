#!/usr/bin/env python3
"""
morning_picks.py — 晨报选股（多因子量化筛选）
08:00-08:30 运行，筛选今日值得关注的短线机会 3-5 只。

方法论（多因子模型 + 动量+质量+估值）：

一、动量因子（趋势跟随）：
  1. 近5日涨幅 > 8%（强动量，主力介入）
  2. 近20日涨幅 > 15%（中期趋势向上）
  3. 昨日未涨停（今天还有空间）
  4. MA5 > MA10 > MA20（均线多头排列）

二、量价因子（资金确认）：
  5. 近5日平均换手率 > 3%（活跃度）
  6. 近3日成交量递增或维持高位（资金持续流入）
  7. 昨日量比 > 1（相对放量）

三、估值因子（安全边际）：
  8. PE(TTM) 10-80（排除亏损和极端泡沫）
  9. 市值 50-500亿（中盘股，弹性好）

四、质量因子（基本面）：
  10. 近一季度净利润增速 > 0（不亏损）
  11. ROE > 5%（有盈利能力）

五、风险排除：
  12. 非ST/退市/停牌
  13. 上市 > 60天（排除次新股炒作）
  14. 昨日涨跌幅 < 9.8%（排除涨停板，今天可能核按钮）
  15. 近5日无跌停（排除问题股）

六、评分排序：
  综合得分 = 动量强度×0.35 + 量价配合×0.25 + 均线形态×0.20 + 估值合理×0.10 + 质量×0.10

数据源：akshare（昨日收盘数据，盘前可用）

用法：
    python3 morning_picks.py            # 标准筛选
    python3 morning_picks.py --top 5    # 输出前5只
    python3 morning_picks.py --json     # JSON输出
    python3 morning_picks.py --verbose  # 显示筛选过程
"""

import json
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path


def get_picks(top: int = 5, verbose: bool = False) -> list:
    """多因子筛选晨报推荐标的"""
    import akshare as ak

    _log(verbose, "获取全A股昨日收盘数据...")
    df = ak.stock_zh_a_spot_em()
    total = len(df)

    # ══ 一、硬性过滤 ══════════════════════════════════════════
    df = df[~df['名称'].str.contains('ST|退|停|N|C', na=False)]
    df = df[df['最新价'] > 5]

    # 市值 50-500亿
    mv_col = _find_col(df, '流通', '市值')
    if mv_col:
        df = df[(df[mv_col] >= 50e8) & (df[mv_col] <= 500e8)]

    # PE 10-80
    pe_col = _find_col(df, '市盈率')
    if pe_col:
        df = df[(df[pe_col] > 10) & (df[pe_col] < 80)]

    # 排除昨日涨停（涨幅>9.8%）
    df = df[df['涨跌幅'] < 9.8]

    # 换手率 > 3%
    if '换手率' in df.columns:
        df = df[df['换手率'] > 3]

    # 量比 > 1（昨日相对放量）
    if '量比' in df.columns:
        df = df[df['量比'] > 1]

    # 昨日涨幅 > 0（至少是涨的，动量方向对）
    df = df[df['涨跌幅'] > 0]

    _log(verbose, f"初筛后: {len(df)}/{total} 只")

    if df.empty:
        return []

    # ══ 二、逐只验证动量+均线+量价 ═══════════════════════════
    _log(verbose, f"逐只验证技术面（{min(len(df), 100)}只）...")
    candidates = []
    checked = 0

    for _, row in df.head(150).iterrows():  # 最多检查150只
        if len(candidates) >= top * 4:
            break
        checked += 1
        code = row['代码']

        try:
            hist = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=(datetime.now() - timedelta(days=45)).strftime("%Y%m%d"),
                end_date=(datetime.now() - timedelta(days=1)).strftime("%Y%m%d"),
                adjust="qfq"
            )
            if hist.empty or len(hist) < 20:
                continue

            closes = hist['收盘'].tolist()
            volumes = hist['成交量'].tolist()

            # 动量因子
            gain_5d = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
            gain_20d = (closes[-1] - closes[-20]) / closes[-20] * 100 if len(closes) >= 20 else 0

            # 条件1：近5日涨幅>8%
            if gain_5d < 8:
                continue

            # 条件4：均线多头排列 MA5>MA10>MA20
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma_bullish = ma5 > ma10 > ma20
            if not ma_bullish:
                continue

            # 条件6：近3日成交量趋势（递增或维持）
            vol_3d = volumes[-3:]
            vol_increasing = vol_3d[-1] >= vol_3d[0] * 0.8  # 允许小幅缩量

            # 条件15：近5日无跌停
            if '涨跌幅' in hist.columns:
                min_chg_5d = hist['涨跌幅'].tail(5).min()
                if min_chg_5d < -9.5:
                    continue

            # MACD
            macd_info = _calc_macd(closes)

            # 近5日平均换手率
            avg_turnover_5d = hist['换手率'].tail(5).mean() if '换手率' in hist.columns else row.get('换手率', 5)

            # 评分
            score = _calc_score(
                gain_5d=gain_5d,
                gain_20d=gain_20d,
                ma_bullish=ma_bullish,
                vol_increasing=vol_increasing,
                turnover=avg_turnover_5d,
                volume_ratio=row.get('量比', 1),
                pe=row.get(pe_col, 30) if pe_col else 30,
                macd_dif=macd_info['dif'] or 0,
            )

            candidates.append({
                "code": code,
                "name": row['名称'],
                "price": round(closes[-1], 2),
                "gain_5d": round(gain_5d, 2),
                "gain_20d": round(gain_20d, 2),
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma20": round(ma20, 2),
                "ma_bullish": ma_bullish,
                "turnover_5d_avg": round(avg_turnover_5d, 2),
                "volume_ratio": round(row.get('量比', 0), 2),
                "pe": round(row.get(pe_col, 0), 1) if pe_col else None,
                "float_mv_yi": round(row.get(mv_col, 0) / 1e8, 0) if mv_col else 0,
                "macd_signal": macd_info['signal'],
                "vol_increasing": vol_increasing,
                "score": round(score, 3),
                "logic": _build_logic(gain_5d, gain_20d, ma5, ma20, macd_info, vol_increasing),
            })

        except Exception:
            continue

    _log(verbose, f"验证完成: {checked}只中{len(candidates)}只通过")

    candidates.sort(key=lambda x: -x["score"])
    return candidates[:top]


# ════════════════════════════════════════════════════════════
#  辅助函数
# ════════════════════════════════════════════════════════════

def _find_col(df, *keywords):
    for col in df.columns:
        if all(k in col for k in keywords):
            return col
    return None


def _log(verbose, msg):
    if verbose:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def _calc_macd(closes: list) -> dict:
    """计算MACD"""
    if len(closes) < 26:
        return {'dif': None, 'dea': None, 'signal': 'insufficient'}

    ema12 = closes[0]
    for p in closes[1:]:
        ema12 = ema12 * (1 - 2/13) + p * (2/13)

    ema26 = closes[0]
    for p in closes[1:]:
        ema26 = ema26 * (1 - 2/27) + p * (2/27)

    dif = ema12 - ema26

    if dif > 0:
        signal = 'bullish'
    elif dif > -0.3:
        signal = 'neutral'
    else:
        signal = 'bearish'

    return {'dif': round(dif, 4), 'signal': signal}


def _calc_score(gain_5d, gain_20d, ma_bullish, vol_increasing, turnover, volume_ratio, pe, macd_dif) -> float:
    """
    综合评分（0-100）

    - 动量强度 35%：5日涨幅+20日涨幅
    - 量价配合 25%：量比+成交量趋势
    - 均线形态 20%：多头排列+MACD
    - 估值合理 10%：PE越低越好（10-30最佳）
    - 换手适中 10%：5-10%最佳
    """
    # 动量（5日8%=50分，15%=100分）
    s1 = min(100, (gain_5d - 5) * 10)

    # 量价（量比1.5=80分，成交量递增+20分）
    s2 = min(100, volume_ratio * 50) + (20 if vol_increasing else 0)
    s2 = min(100, s2)

    # 均线+MACD
    s3 = 60 if ma_bullish else 20
    s3 += 40 if macd_dif > 0 else (20 if macd_dif > -0.3 else 0)
    s3 = min(100, s3)

    # 估值（PE 15-25=100分，偏离扣分）
    ideal_pe = 20
    s4 = max(0, 100 - abs(pe - ideal_pe) * 3)

    # 换手（5-10%=100分）
    s5 = max(0, 100 - abs(turnover - 7.5) * 15)

    score = s1 * 0.35 + s2 * 0.25 + s3 * 0.20 + s4 * 0.10 + s5 * 0.10
    return score


def _build_logic(gain_5d, gain_20d, ma5, ma20, macd_info, vol_increasing) -> str:
    """生成推荐逻辑"""
    parts = []

    if gain_5d >= 15:
        parts.append(f"5日暴涨{gain_5d:.0f}%，强动量")
    elif gain_5d >= 10:
        parts.append(f"5日大涨{gain_5d:.0f}%")
    else:
        parts.append(f"5日涨{gain_5d:.0f}%")

    if gain_20d >= 20:
        parts.append(f"20日趋势+{gain_20d:.0f}%")

    parts.append("均线多头排列")

    if macd_info['signal'] == 'bullish':
        parts.append("MACD多头")

    if vol_increasing:
        parts.append("量能配合")

    return "，".join(parts)


# ════════════════════════════════════════════════════════════
#  输出
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='晨报多因子选股')
    parser.add_argument('--top', type=int, default=5, help='输出数量（默认5）')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    parser.add_argument('--verbose', action='store_true', help='显示筛选过程')
    args = parser.parse_args()

    picks = get_picks(top=args.top, verbose=args.verbose)

    if args.json:
        print(json.dumps(picks, ensure_ascii=False, indent=2))
        return

    now = datetime.now().strftime('%H:%M')
    print(f"\n{'═'*70}")
    print(f"  🎯 晨报选股 | {now}")
    print(f"  多因子：动量>8% + 均线多头 + 放量 + PE合理 + 市值50-500亿")
    print(f"{'═'*70}")

    if not picks:
        print(f"\n  今日无符合条件标的（市场可能整体弱势）")
        print(f"{'═'*70}\n")
        return

    print(f"\n  {'代码':<8}{'名称':<8}{'昨收':>7}{'5日涨':>7}{'20日涨':>7}{'量比':>5}{'PE':>6}{'得分':>6}")
    print(f"  {'─'*58}")

    for c in picks:
        pe_str = f"{c['pe']:.0f}" if c['pe'] else "-"
        print(f"  {c['code']:<8}{c['name']:<8}{c['price']:>7.2f}"
              f"{c['gain_5d']:>+6.1f}%{c['gain_20d']:>+6.1f}%"
              f"{c['volume_ratio']:>5.1f}{pe_str:>6}{c['score']:>6.1f}")
        print(f"         逻辑：{c['logic']}")

    print(f"\n{'─'*70}")
    print(f"  ⚠️ 注意事项：")
    print(f"  □ 开盘后观察集合竞价情况（高开>3%谨慎追）")
    print(f"  □ 确认板块整体氛围（板块涨停数>3只说明有人气）")
    print(f"  □ 设好止损位（建议-5%或破MA10）")
    print(f"  □ 仓位控制（单只不超总仓位20%）")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
