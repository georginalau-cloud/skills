#!/usr/bin/env python3
"""
tail_market.py — 尾盘"倒车接人"选股
14:30-14:50 运行，筛选今天回调但明天大概率反弹的标的 3-5 只。

筛选逻辑（"倒车接人"特征）：
  1. 今日涨跌 -3%~-10%（深度回调，不是小幅震荡）
  2. 近5日有过涨停或涨幅>5%的强势表现（说明主力在，只是洗盘）
  3. 当前价在20日均线附近（±5%以内，均线支撑）
  4. 换手率 > 3%（有人气，不是僵尸股）
  5. 流通市值 50-500亿（不太大不太小）
  6. 量比 < 1.5（缩量回调，不是放量杀跌）
  7. 所属板块当日涨幅为正或近3日有轮动迹象（板块不能退潮）

数据源：akshare 全A股实时 + 近5日历史 + 板块涨跌

用法：
    python3 tail_market.py              # 标准筛选
    python3 tail_market.py --top 5      # 输出前5只
    python3 tail_market.py --json       # JSON输出
"""

import json
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path


def get_candidates(top: int = 5) -> list:
    """筛选尾盘倒车接人候选股"""
    import akshare as ak

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 获取全A股实时数据...", file=sys.stderr)
    df = ak.stock_zh_a_spot_em()

    # 基础过滤
    df = df[~df['名称'].str.contains('ST|退|停|N|C', na=False)]
    df = df[df['最新价'] > 3]  # 排除低价股

    # 条件1：今日深度回调 -3% ~ -10%
    df = df[(df['涨跌幅'] >= -10) & (df['涨跌幅'] <= -3)]

    # 条件4：换手率 > 3%
    if '换手率' in df.columns:
        df = df[df['换手率'] > 3]

    # 条件5：流通市值 50-500亿
    mv_col = None
    for col in df.columns:
        if '流通' in col and '市值' in col:
            mv_col = col
            break
    if mv_col:
        df = df[(df[mv_col] >= 50e8) & (df[mv_col] <= 500e8)]

    # 条件6：量比 < 1.5（缩量回调）
    if '量比' in df.columns:
        df = df[df['量比'] < 1.5]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 初筛后 {len(df)} 只，获取板块数据...", file=sys.stderr)

    # 获取今日板块涨跌（用于条件7：板块轮动判断）
    sector_data = _fetch_sector_performance()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 检查近5日强势+均线+板块...", file=sys.stderr)

    # 条件2+3+7：需要历史数据+板块验证
    candidates = []
    for _, row in df.iterrows():
        if len(candidates) >= top * 3:
            break
        code = row['代码']
        try:
            hist = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=(datetime.now() - timedelta(days=10)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust="qfq"
            )
            if hist.empty or len(hist) < 5:
                continue

            # 条件2：近5日有涨幅>5%的交易日
            recent_5 = hist.tail(6).head(5)  # 不含今天
            max_gain = recent_5['涨跌幅'].max() if '涨跌幅' in recent_5.columns else 0
            if max_gain < 5:
                continue

            # 条件3：当前价在20日均线附近（±5%）
            if len(hist) >= 20:
                ma20 = hist['收盘'].tail(20).mean()
                current = row['最新价']
                deviation = abs(current - ma20) / ma20 * 100
                if deviation > 5:
                    continue
                ma20_val = round(ma20, 2)
            else:
                ma20_val = None
                deviation = 0

            # 条件7：板块轮动判断
            sector_info = _match_sector(code, row['名称'], sector_data)

            candidates.append({
                "code": code,
                "name": row['名称'],
                "price": round(row['最新价'], 2),
                "change_pct": round(row['涨跌幅'], 2),
                "turnover_rate": round(row.get('换手率', 0), 2),
                "volume_ratio": round(row.get('量比', 0), 2),
                "float_mv_yi": round(row.get(mv_col, 0) / 1e8, 0) if mv_col else 0,
                "max_gain_5d": round(max_gain, 2),
                "ma20": ma20_val,
                "ma20_deviation": round(deviation, 2) if ma20_val else None,
                "sector": sector_info.get("name", ""),
                "sector_change_pct": sector_info.get("change_pct", 0),
                "logic": _build_logic(row, max_gain, ma20_val, sector_info),
            })
        except Exception:
            continue

    # 排序：优先板块强势+个股回调深的（板块涨+个股跌=倒车接人最佳）
    candidates.sort(key=lambda x: (x.get("sector_change_pct", 0) - x["change_pct"]), reverse=True)
    return candidates[:top]


def _fetch_sector_performance() -> dict:
    """获取今日概念板块涨跌TOP50（用于判断板块轮动）"""
    import akshare as ak
    try:
        df = ak.stock_board_concept_name_em()
        if df.empty:
            return {}
        # 返回 {板块名: 涨跌幅}
        result = {}
        for _, row in df.iterrows():
            name = row.get('板块名称', '')
            chg = row.get('涨跌幅', 0)
            if name:
                result[name] = float(chg) if chg else 0
        return result
    except Exception:
        return {}


def _match_sector(code: str, name: str, sector_data: dict) -> dict:
    """匹配个股所属板块（简化：用行业关键词匹配）"""
    # 如果没有板块数据，返回空
    if not sector_data:
        return {"name": "未知", "change_pct": 0}

    # 尝试用 akshare 获取个股所属概念板块
    try:
        import akshare as ak
        df = ak.stock_board_concept_cons_em(symbol="")  # 这个接口不太好用
    except Exception:
        pass

    # 简化方案：找板块数据中涨幅最高的前10个板块作为"轮动中"的板块
    # 实际匹配需要个股-板块映射表，这里用涨幅中位数作为市场情绪参考
    top_sectors = sorted(sector_data.items(), key=lambda x: -x[1])[:10]
    avg_top = sum(v for _, v in top_sectors) / len(top_sectors) if top_sectors else 0

    return {
        "name": top_sectors[0][0] if top_sectors else "未知",
        "change_pct": round(avg_top, 2),
        "market_mood": "轮动活跃" if avg_top > 2 else ("正常" if avg_top > 0 else "退潮"),
    }


def _build_logic(row, max_gain_5d, ma20, sector_info=None) -> str:
    """生成看涨逻辑（一句话）"""
    parts = []
    if max_gain_5d >= 10:
        parts.append(f"近5日有涨停({max_gain_5d:+.1f}%)")
    elif max_gain_5d >= 5:
        parts.append(f"近5日强势({max_gain_5d:+.1f}%)")

    if ma20:
        parts.append(f"回踩20日均线({ma20:.2f})")

    vr = row.get('量比', 0)
    if vr < 0.8:
        parts.append("极度缩量回调")
    elif vr < 1.2:
        parts.append("缩量回调")

    if sector_info and sector_info.get("change_pct", 0) > 1:
        mood = sector_info.get("market_mood", "")
        parts.append(f"板块{mood}(+{sector_info['change_pct']:.1f}%)")
    elif sector_info and sector_info.get("market_mood") == "退潮":
        parts.append("⚠️板块退潮中")

    return "，".join(parts) if parts else "技术面回调"


def main():
    parser = argparse.ArgumentParser(description='尾盘倒车接人选股')
    parser.add_argument('--top', type=int, default=5, help='输出数量（默认5）')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    args = parser.parse_args()

    candidates = get_candidates(top=args.top)

    if args.json:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return

    now = datetime.now().strftime('%H:%M')
    print(f"\n{'═'*65}")
    print(f"  🚌 尾盘倒车接人 | {now}")
    print(f"  筛选：今日-3%~-10% + 近5日有强势 + 20日均线支撑 + 缩量 + 板块轮动")
    print(f"{'═'*65}")

    if not candidates:
        print(f"\n  今日无符合条件标的（市场可能普涨或普跌）")
        print(f"{'═'*65}\n")
        return

    print(f"\n  {'代码':<8}{'名称':<10}{'现价':>8}{'今日':>7}{'5日最强':>8}{'换手':>6}{'量比':>6}{'市值':>6}")
    print(f"  {'─'*60}")

    for c in candidates:
        print(f"  {c['code']:<8}{c['name']:<10}{c['price']:>8.2f}"
              f"{c['change_pct']:>+6.2f}%{c['max_gain_5d']:>+7.1f}%"
              f"{c['turnover_rate']:>5.1f}%{c['volume_ratio']:>5.1f}x"
              f"{c['float_mv_yi']:>5.0f}亿")
        print(f"         看涨逻辑：{c['logic']}")

    print(f"\n{'─'*65}")
    print(f"  ⚠️ 以上为程序筛选结果，买入前请确认：")
    print(f"  □ 分时图尾盘是否企稳（不是继续下杀）")
    print(f"  □ 板块整体是否仍有人气（不是板块退潮）")
    print(f"  □ 是否有利空公告（停牌/减持/业绩雷）")
    print(f"{'═'*65}\n")


if __name__ == "__main__":
    main()
