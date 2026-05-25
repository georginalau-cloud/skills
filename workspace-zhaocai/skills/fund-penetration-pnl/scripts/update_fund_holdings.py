#!/usr/bin/env python3
"""
update_fund_holdings.py
每天自动从天天基金网抓取用户持仓基金的Q1最新持仓明细，
写入 fund_holdings.json，供 fund_penetration_pnl.py 使用。

用法:
    python3 update_fund_holdings.py              # 更新所有基金
    python3 update_fund_holdings.py --fund 166002  # 只更新指定基金
    python3 update_fund_holdings.py --dry          # 试运行不写入
"""
import json
import re
import time
import argparse
from pathlib import Path

# ── 用户持仓基金（从统一 holdings.json 读取）───────────────────
import pathlib as _pathlib
_HOLDINGS_PATH = _pathlib.Path(__file__).parent.parent.parent.parent / "holdings.json"

def _load_fund_list():
    """从 holdings.json 读取基金列表"""
    if _HOLDINGS_PATH.exists():
        with open(_HOLDINGS_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return {code: info["name"] for code, info in data.get("funds", {}).items()}
    # 兜底：如果 holdings.json 不存在，用硬编码
    return {
        "163402": "兴全趋势投资",
        "006113": "汇添富创新医药A",
        "519069": "汇添富价值精选A",
        "166002": "中欧新蓝筹A",
        "000979": "景顺长城沪港深精选A",
        "006751": "富国互联科技A",
        "004477": "嘉实沪港深回报",
        "001371": "富国沪港深价值精选A",
        "166005": "中欧价值发现A",
        "160706": "沪深300LOF",
        "001668": "汇添富全球移动互联A",
        "118001": "易方达亚洲精选",
        "004965": "泓德致远混合A",
        "450009": "国富中小盘A",
    }

MY_FUNDS = _load_fund_list()

OUTPUT_PATH = Path(__file__).parent.parent.parent / "market-alert" / "references" / "fund_holdings.json"
FUND_LIST_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={fund}&topline=10&year=2026&month=03&r=0.{rand}"
HEADERS = {
    "Referer": "https://fundf10.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch_holdings(fund_code):
    """从天天基金网抓取单只基金的Q1持仓明细"""
    import requests
    url = FUND_LIST_URL.format(fund=fund_code, rand=int(time.time() % 100))
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = "utf-8"
        raw = r.text
    except Exception as e:
        return {"error": str(e)}

    # 解析 content:'...' 之间的 HTML
    m = re.search(r"content:['\"](.*?)['\"],\s*arryear", raw, re.DOTALL)
    if not m:
        # 空季报或接口异常
        return {"error": "no content", "raw": raw[:200]}

    html = m.group(1).replace("\\'", "'")
    # 提取基金名称
    name_m = re.search(r"title='([^']+)'", html)
    fund_name = name_m.group(1) if name_m else MY_FUNDS.get(fund_code, fund_code)
    # 提取总市值（净资产规模）
    scale_m = re.search(r"净资产规模.*?([\d.]+)", html)
    total_mv = float(scale_m.group(1)) * 1e8 if scale_m else 0

    holdings = []
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 8:
            continue
        # Clean HTML
        clean = []
        for c in cells:
            c = re.sub(r"<[^>]+>", "", c).strip()
            c = c.replace("&nbsp;", "").replace(",", "")
            clean.append(c)
        try:
            seq = clean[0].strip()
            if not seq.isdigit():
                continue
            code_raw = clean[1].strip()
            # Normalize code: 300308 -> 300308, 06869 -> 06869
            code = code_raw.zfill(6)
            name = clean[2].strip()
            pct_str = clean[6].strip().replace("%", "")
            mv_str = clean[7].strip()
            holdings.append({
                "code": code,
                "name": name,
                "percent": float(pct_str),
                "market_value": float(mv_str) * 1e4,  # 万元 → 元
            })
        except Exception:
            continue

    return {
        "name": fund_name,
        "total_market_value": total_mv,
        "holdings": holdings,
    }


def load_existing():
    """加载已有 holdings 文件（保留没有Q1数据的基金空壳）"""
    if not OUTPUT_PATH.exists():
        return {}
    with open(OUTPUT_PATH) as f:
        return json.load(f)


def save(data):
    """写入 fund_holdings.json"""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fund", type=str, help="只更新指定基金代码")
    parser.add_argument("--dry", action="store_true", help="试运行，不写入文件")
    args = parser.parse_args()

    funds_to_update = {args.fund: MY_FUNDS[args.fund]} if args.fund else MY_FUNDS
    results = {}

    print(f"{'='*60}")
    print(f"  基金持仓更新 | {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    existing = load_existing()
    fund_holdings = existing.get("fund_holdings", {})

    for i, (fid, fname) in enumerate(funds_to_update.items(), 1):
        print(f"\n[{i}/{len(funds_to_update)}] 抓取 {fid} {fname}...")
        result = fetch_holdings(fid)

        if "error" in result and result["error"] != "no content":
            print(f"  ⚠️ 失败: {result['error']}")
            # 保留旧数据
            if fid in fund_holdings:
                results[fid] = fund_holdings[fid]
                print(f"  ↩ 保留旧数据")
        else:
            results[fid] = result
            holdings_count = len(result.get("holdings", []))
            total_mv = result.get("total_market_value", 0)
            print(f"  ✅ 抓取成功: {holdings_count} 只重仓股, 规模 {total_mv/1e8:.2f}亿")
            if holdings_count > 0:
                for h in result["holdings"][:3]:
                    print(f"     {h['code']} {h['name']} {h['percent']:.2f}%")
                if holdings_count > 3:
                    print(f"     ... 等 {holdings_count} 只")

        # Rate limit
        if i < len(funds_to_update):
            time.sleep(0.8)

    # 构建输出
    output = {
        "update_time": time.strftime("%Y-%m-%d %H:%M"),
        "top_funds": list(funds_to_update.keys()),
        "fund_holdings": results,
    }

    # 汇总所有股票
    all_codes = set()
    for fid, finfo in results.items():
        for h in finfo.get("holdings", []):
            all_codes.add(h["code"])
    output["all_codes"] = sorted(list(all_codes), key=lambda x: (x[0] in "56", x))
    output["total_stocks"] = len(all_codes)

    # 统计重叠股
    overlap = {}
    for fid, finfo in results.items():
        for h in finfo.get("holdings", []):
            c = h["code"]
            if c not in overlap:
                overlap[c] = []
            overlap[c].append(fid)
    output["overlap"] = {k: v for k, v in overlap.items() if len(v) > 1}
    output["overlap_count"] = len(output["overlap"])

    if args.dry:
        print(f"\n{'='*60}")
        print(f"  Dry run — 不写入文件")
        print(f"  结果预览:")
        print(json.dumps(output, ensure_ascii=False, indent=2)[:2000])
    else:
        save(output)
        print(f"\n{'='*60}")
        print(f"  ✅ 已写入 {OUTPUT_PATH}")
        print(f"  📊 更新基金: {len(results)}/{len(funds_to_update)}")
        print(f"  📈 穿透股数: {output['total_stocks']} 只")
        print(f"  🔗 重叠股数: {output['overlap_count']} 只")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()