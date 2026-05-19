#!/usr/bin/env python3
"""
基金持仓穿透更新脚本 - update_fund_holdings.py
每周自动获取14只基金的十大重仓股
沛柔专属 · 招财喵出品

用法:
    python3 update_fund_holdings.py          # 正式运行
    python3 update_fund_holdings.py --dry-run # 测试
    python3 update_fund_holdings.py --json    # JSON输出
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from collections import Counter

# ─── 基金列表（从统一 holdings.json 读取）───
_HOLDINGS_PATH = Path(__file__).parent.parent.parent.parent / "holdings.json"

def _load_funds_from_holdings():
    if _HOLDINGS_PATH.exists():
        with open(_HOLDINGS_PATH, encoding='utf-8') as f:
            h = json.load(f)
        return {code: {"name": info["name"]} for code, info in h.get("funds", {}).items()}
    # 兜底硬编码（holdings.json 不存在时）
    return {
        "166002": {"name": "中欧新蓝筹A"},
        "006751": {"name": "富国互联科技A"},
        "163402": {"name": "兴全趋势投资"},
        "004477": {"name": "嘉实沪港深回报"},
        "001371": {"name": "富国沪港深价值精选A"},
        "166005": {"name": "中欧价值发现A"},
        "160706": {"name": "沪深300LOF"},
        "001668": {"name": "汇添富全球移动互联A"},
        "000979": {"name": "景顺长城沪港深精选A"},
        "118001": {"name": "易方达亚洲精选"},
        "004965": {"name": "泓德致远混合A"},
        "450009": {"name": "国富中小盘A"},
        "519069": {"name": "汇添富价值精选A"},
        "006113": {"name": "汇添富创新医药A"},
    }

FUNDS = _load_funds_from_holdings()

OUTPUT_DIR = Path(__file__).parent.parent / "references"
OUTPUT_MD = OUTPUT_DIR / "fund_holdings.md"
OUTPUT_JSON = OUTPUT_DIR / "fund_holdings.json"


def fetch_fund_holdings(fund_code: str, quarter: str = "20260331"):
    """
    获取基金十大重仓股（支持2026Q1等最新季度）
    返回 None 表示失败
    成功返回: {"quarter": str, "holdings": [...], "total_market_value": float}
    """
    try:
        import akshare as ak
        df = ak.stock_report_fund_hold_detail(symbol=fund_code, date=quarter)
        if df is None or df.empty:
            return None

        holdings = []
        for _, row in df.iterrows():
            code = str(row.get('股票代码', '')).strip()
            name = str(row.get('股票简称', '')).strip()
            percent = row.get('占总股本比例', 0) or 0
            mv = row.get('持股市值', 0) or 0

            if code and name and code.isdigit() and len(code) == 6:
                try:
                    holdings.append({
                        "code": code,
                        "name": name,
                        "percent": float(percent),
                        "market_value": float(mv),
                    })
                except (ValueError, TypeError):
                    pass

        total_mv = float(df['持股市值'].sum()) if '持股市值' in df.columns else 0.0
        # 接口持股市值单位是元，转换为万元保持一致
        total_mv = total_mv / 10000.0

        # 季度名称
        quarter_names = {
            "20260331": "2026年1季度股票投资明细",
            "20251231": "2025年4季度股票投资明细",
            "20250930": "2025年3季度股票投资明细",
        }
        quarter_label = quarter_names.get(quarter, f"{quarter[:4]}年{quarter[4:6]}季度")

        return {
            "quarter": quarter_label,
            "holdings": holdings,
            "total_market_value": total_mv,
        }

    except ImportError:
        print(f"  ⚠️ akshare未安装")
        return None
    except Exception as e:
        print(f"  ⚠️ 获取 {fund_code} 持仓失败: {e}")
        return None


def calc_overlap(filtered_holdings: dict) -> dict:
    """
    计算持仓重叠度（基于过滤后的持仓）
    filtered_holdings: {fund_code: {"holdings": [...]}}
    返回: {股票代码: {"name": str, "funds": [fund_codes], "count": int}}
    """
    code_to_name = {}
    code_to_funds = {}

    for fund_code, data in filtered_holdings.items():
        for stock in data.get("holdings", []):
            code = stock["code"]
            code_to_name[code] = stock["name"]
            if code not in code_to_funds:
                code_to_funds[code] = []
            code_to_funds[code].append(fund_code)

    overlap = {}
    for code, funds in code_to_funds.items():
        if len(funds) >= 2:
            overlap[code] = {
                "name": code_to_name[code],
                "count": len(funds),
                "funds": funds,
            }
    return overlap


def generate_markdown(filtered_holdings: dict, overlap: dict,
                       update_time: str) -> str:
    """生成 fund_holdings.md"""
    lines = [
        f"# 基金持仓穿透数据",
        f"",
        f"_自动生成，每周一更新 | 更新时间: {update_time}_",
        f"",
        f"## 持仓重叠度分析（被≥2只基金共同持有）",
        f"",
    ]

    if overlap:
        lines.append("| 股票 | 代码 | 持有基金数 | 涉及基金 |")
        lines.append("|------|------|-----------|---------|")
        for code, info in sorted(overlap.items(), key=lambda x: -x[1]["count"]):
            funds_str = ", ".join([f"{FUNDS[f]['name']}" for f in info["funds"]])
            lines.append(f"| {info['name']} | {code} | {info['count']}只 | {funds_str} |")
    else:
        lines.append("_暂无高度重叠持仓_")

    lines += ["", "---", "",
               "## 各基金五大重仓股（Top5基金 × 各前5大持仓）", ""]

    for fund_code, data in filtered_holdings.items():
        fund_name = FUNDS.get(fund_code, {}).get("name", fund_code)
        quarter = data.get("quarter", "")
        mv = data.get("total_market_value", 0)
        holdings = data.get("holdings", [])
        lines.append(f"### {fund_name}（{fund_code}）")
        lines.append(f"季度：{quarter} | 持仓总市值：{mv:,.0f}万")
        lines.append("")
        if holdings:
            lines.append("| 代码 | 名称 | 占净值比 |")
            lines.append("|------|------|---------|")
            for s in holdings:
                lines.append(f"| {s['code']} | {s['name']} | {s['percent']:.2f}% |")
        else:
            lines.append("_暂无数据_")
        lines.append("")

    return "\n".join(lines)


def run(dry_run=False, json_output=False):
    print(f"\n{'='*50}")
    print(f"🕐 基金持仓穿透更新 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    # ─── Step 0: 确定最新季度日期 ───
    # 优先使用2026Q1（季报每年4月/7月/10月/次年1月发布）
    QUARTERS_TO_TRY = ["20260331", "20251231", "20250930"]
    chosen_quarter = None
    for q in QUARTERS_TO_TRY:
        try:
            import akshare as ak
            test_df = ak.stock_report_fund_hold_detail(symbol="166002", date=q)
            if test_df is not None and len(test_df) > 0:
                chosen_quarter = q
                quarter_year = q[:4]
                quarter_num = int(q[4:6]) // 3
                print(f"📅 检测到最新季度: {quarter_year}年第{quarter_num}季度 ({q})")
                break
        except Exception:
            continue
    if not chosen_quarter:
        print("⚠️ 无法获取任何季度数据")
        return

    # ─── Step 1: 获取所有基金持仓 ───
    raw_data = {}
    for fund_code in FUNDS:
        fund_name = FUNDS[fund_code]["name"]
        print(f"\n📥 获取 {fund_name}（{fund_code}）持仓...")
        result = fetch_fund_holdings(fund_code, quarter=chosen_quarter)
        raw_data[fund_code] = result
        if result and result.get("holdings"):
            mv = result.get("total_market_value", 0)
            print(f"  ✅ {result['quarter']} | 总市值 {mv:,.0f}万 | {len(result['holdings'])}只")
        else:
            print(f"  ⚠️ 无数据")

    # ─── Step 2: 按持仓总市值排序，选Top5基金 ───
    valid = {f: d for f, d in raw_data.items() if d and d.get("holdings")}
    sorted_funds = sorted(valid.items(),
                          key=lambda x: x[1].get("total_market_value", 0),
                          reverse=True)
    TOP_N_FUNDS = 5
    top_funds = sorted_funds[:TOP_N_FUNDS]

    print(f"\n{'='*50}")
    print(f"📊 Top{TOP_N_FUNDS}基金（按持仓总市值）：")
    for fc, d in top_funds:
        print(f"  {FUNDS[fc]['name']}: {d.get('total_market_value', 0):,.0f}万")

    # ─── Step 3: 从Top5中各取占比前5的股票 ───
    TOP_N_PER_FUND = 5
    filtered = {}
    all_stocks_flat = {}  # code -> name

    print(f"\n📋 Top5基金 × 各5大重仓：")
    for fc, d in top_funds:
        sorted_stocks = sorted(d["holdings"],
                               key=lambda s: s.get("percent", 0),
                               reverse=True)[:TOP_N_PER_FUND]
        filtered[fc] = {
            "quarter": d.get("quarter", ""),
            "total_market_value": d.get("total_market_value", 0),
            "holdings": sorted_stocks,
        }
        print(f"\n  {FUNDS[fc]['name']} — {d.get('quarter','')}:")
        for s in sorted_stocks:
            print(f"    {s['code']} {s['name']} {s['percent']:.2f}%")
            all_stocks_flat[s["code"]] = s["name"]

    # ─── Step 4: 计算重叠度 ───
    overlap = calc_overlap(filtered)
    total = len(all_stocks_flat)

    print(f"\n{'='*50}")
    print(f"📊 最终汇总：")
    print(f"  - 覆盖基金：{len(filtered)}只（Top5）")
    print(f"  - 穿透重仓股：{total}只（去重）")
    print(f"  - 高度重叠股（≥2只基金）：{len(overlap)}只")
    if overlap:
        print(f"\n  🔴 重点重叠股：")
        for code, info in sorted(overlap.items(), key=lambda x: -x[1]["count"])[:5]:
            print(f"     {info['name']}({code}) 被{info['count']}只基金持有")

    # ─── Step 5: 写文件 ───
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = generate_markdown(filtered, overlap, update_time)
    all_codes = sorted(all_stocks_flat.keys())

    if json_output:
        print(json.dumps({
            "update_time": update_time,
            "top_funds": list(filtered.keys()),
            "total_stocks": total,
            "overlap_count": len(overlap),
            "overlap": overlap,
            "all_codes": all_codes,
            "fund_holdings": {f: {"name": FUNDS[f]["name"], **filtered[f]}
                              for f in filtered},
        }, ensure_ascii=False, indent=2))
        return filtered

    if not dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_MD.write_text(md, encoding="utf-8")
        print(f"\n✅ 已写入: {OUTPUT_MD}")
        json_data = {
            "update_time": update_time,
            "top_funds": list(filtered.keys()),
            "total_stocks": total,
            "overlap_count": len(overlap),
            "overlap": overlap,
            "all_codes": all_codes,
            "fund_holdings": {f: {"name": FUNDS[f]["name"], **filtered[f]}
                              for f in filtered},
        }
        OUTPUT_JSON.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 已写入: {OUTPUT_JSON}")
        print(f"📋 监控重仓股：{total}只")
        print(f"\n📋 持仓代码（{len(all_codes)}只）:")
        print(", ".join(all_codes))
    else:
        print(f"\n📋 [dry-run] 应写入: {OUTPUT_MD}")
        print(md[:500] + "...")

    return filtered


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="基金持仓穿透更新")
    parser.add_argument("--dry-run", action="store_true", help="测试模式")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    args = parser.parse_args()
    run(dry_run=args.dry_run, json_output=args.json)
