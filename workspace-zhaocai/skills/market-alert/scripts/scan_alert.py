#!/usr/bin/env python3
"""
市场异动扫描脚本 - scan_alert.py
沛柔专属持仓监控 · 招财喵出品
Version 2: 支持条件触发配置

用法:
    python3 scan_alert.py --config defaults     # 默认全量扫描
    python3 scan_alert.py --triggers stock,index  # 仅扫描个股+大盘
    python3 scan_alert.py --index-threshold 0.8   # 大盘阈值改为±0.8%
    python3 scan_alert.py --stock-threshold 5     # 个股阈值改为±5%
    python3 scan_alert.py --dry-run                # 测试模式（不推送）
    python3 scan_alert.py --json                   # JSON格式输出
    python3 scan_alert.py --list                   # 列出所有触发条件
"""

import sys
import json
import argparse
from datetime import datetime, time
from pathlib import Path

# ─── 个人持仓配置（从统一 holdings.json 读取）───
import pathlib as _pathlib
_HOLDINGS_PATH = _pathlib.Path(__file__).parent.parent.parent.parent / "holdings.json"

def _load_holdings_config():
    if _HOLDINGS_PATH.exists():
        with open(_HOLDINGS_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {"stocks": {}, "etfs": {}, "funds": {}}

_H = _load_holdings_config()
STOCKS = {code: {"name": info["name"], "sector": info.get("sector", ""), "cost": info.get("cost", 0)}
          for code, info in _H.get("stocks", {}).items()}
ETFS = {code: {"name": info["name"], "sector": info.get("sector", ""), "cost": info.get("cost", 0)}
        for code, info in _H.get("etfs", {}).items()}

# ─── 默认触发条件配置 ───
DEFAULT_TRIGGERS = {
    "stock": {
        "enabled": True,
        "label": "持仓个股异动",
        "threshold_pct": 3.0,
        "description": "持仓A股单日涨跌超阈值",
    },
    "etf": {
        "enabled": True,
        "label": "ETF异动",
        "threshold_pct": 3.0,
        "description": "持仓场内ETF涨跌超阈值",
    },
    "index": {
        "enabled": True,
        "label": "大盘指数波动",
        "threshold_pct": 1.0,
        "indices": ["000300", "399001", "399006"],  # 沪深300/深证/创业板
        "index_names": {"000300": "沪深300", "399001": "深证成指", "399006": "创业板指"},
        "description": "大盘指数波动超阈值（默认±1%）",
    },
    "volume": {
        "enabled": True,
        "label": "成交量突变",
        "threshold_pct": 50.0,
        "description": "持仓标的成交量较昨日增加超阈值",
    },
    "sector": {
        "enabled": False,
        "label": "板块集体异动",
        "min_stocks": 3,
        "threshold_pct": 3.0,
        "description": "持仓关联板块内≥N只股票异动（需板块数据支持）",
    },
    "usmarket": {
        "enabled": False,
        "label": "美股隔夜异动",
        "threshold_pct": 1.0,
        "description": "道琼斯/纳斯达克/标普500隔夜涨跌超阈值",
    },
    "oil": {
        "enabled": False,
        "label": "原油波动",
        "threshold_pct": 2.0,
        "description": "WTI原油价格波动超阈值",
    },
}

# ─── 静默时段 ───
QUIET_START = time(23, 0)
QUIET_END   = time(8, 0)

# ─── 持仓关联板块 ───
SECTOR_STOCKS = {
    "医美":   ["300896", "688363", "002614"],
    "化工":   ["600309", "600352"],
    "新能源": ["002176", "159566"],
    "地产":   ["000652"],
    "航空":   ["600221"],
    "医疗":   ["002551"],
}


# ════════════════════════════════════════════════════════════
#  基金持仓加载（从 update_fund_holdings.py 生成的JSON读取）
# ════════════════════════════════════════════════════════════

FUND_HOLDINGS_JSON = Path(__file__).parent.parent / "references" / "fund_holdings.json"


def load_fund_holdings() -> dict:
    """读取基金穿透持仓JSON数据"""
    if not FUND_HOLDINGS_JSON.exists():
        return {}
    try:
        import json
        with open(FUND_HOLDINGS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_all_monitored_codes(include_fund: bool = True) -> dict:
    """
    返回所有需要监控的股票代码
    返回格式: {代码: {"name": "名称", "source": "personal|fund", "sector": "板块"}}
    """
    codes = {}
    # 个人持仓
    for code, info in STOCKS.items():
        codes[code] = {"name": info["name"], "source": "personal", "sector": info["sector"]}
    # 基金持仓
    if include_fund:
        fund_data = load_fund_holdings()
        if fund_data and "fund_holdings" in fund_data:
            update_info = f"（上周一更新）"
            for fund_code, fund_info in fund_data["fund_holdings"].items():
                for stock in fund_info.get("holdings", []):
                    code = stock["code"]
                    if code not in codes:  # 不覆盖个人持仓
                        codes[code] = {
                            "name": stock["name"],
                            "source": "fund",
                            "sector": "基金穿透",
                            "fund": fund_info["name"],
                        }
    return codes


def get_fund_overlap_stocks() -> list:
    """获取高度重叠的基金持仓股（被≥2只基金持有）"""
    fund_data = load_fund_holdings()
    if not fund_data or "overlap" not in fund_data:
        return []
    return list(fund_data["overlap"].keys())


# ════════════════════════════════════════════════════════════
#  工具函数
# ════════════════════════════════════════════════════════════

def is_quiet_hours():
    now = datetime.now().time()
    if QUIET_START <= now or now <= QUIET_END:
        return True
    return False


def is_trading_day():
    """用akshare判断今天是否为A股交易日（包含节假日调休判断）"""
    cache_file = Path(__file__).parent.parent / ".trading_day_cache"
    today = datetime.now().strftime("%Y-%m-%d")

    # 读缓存（当日有效）
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("date") == today:
                return cached.get("is_trading", False)
        except Exception:
            pass

    # akshare 交易日历接口
    try:
        import akshare as ak
        # 取当前日期前后各5天的日历
        start = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
        end   = (datetime.now() + timedelta(days=5)).strftime("%Y%m%d")
        df = ak.tool_trade_date_hist_sina()
        # df 的 trade_date 列格式为 YYYY-MM-DD 或 YYYYMMDD
        dates = set(df["trade_date"].astype(str).str.replace("-",""))
        today_str = today.replace("-", "")
        is_trading = today_str in dates
    except Exception:
        # 接口失败时保守：认为非交易日
        is_trading = False

    # 缓存
    try:
        cache_file.write_text(json.dumps({"date": today, "is_trading": is_trading}), encoding="utf-8")
    except Exception:
        pass

    return is_trading


def is_market_open():
    """判断当前是否为A股交易时间（时间窗口内 + 必须是交易日）"""
    now = datetime.now()
    # 先判断是否交易日（含节假日）
    if not is_trading_day():
        return False
    # 再判断时间窗口（工作日9:30-15:00）
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return time(9, 30) <= current_time <= time(15, 0)


def is_overseas_market_active():
    """判断海外市场是否活跃（美股盘前/交易中）"""
    now = datetime.now()
    # 转为纽约时间简单估算（UTC-5 / UTC-4 夏令时）
    # 用上海时间粗算：美股 22:30-次日05:00 为交易时段
    # 对应上海时区 14:30-21:00（夏令则 13:30-20:00）
    hour = now.hour
    minute = now.minute
    t = hour * 60 + minute
    # 粗判断：北京时间 14:30-21:00 为美股交易时段
    trading_start = 14 * 60 + 30
    trading_end   = 21 * 60
    return trading_start <= t <= trading_end


def fetch_us_futures():
    """获取美股期指数据（S&P500、Nasdaq、Dow）
    新浪hf_格式：字段[0]=当前价 [2]=昨收 [3]=今开 [4]=最高 [5]=最低
    """
    try:
        import requests
        url = "https://hq.sinajs.cn/list=hf_ES,hf_NQ,hf_YM"
        headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "gbk"
        result = {}
        names = {"ES": ("S&P500期指", "ES"),
                 "NQ": ("Nasdaq100期指", "NQ"),
                 "YM": ("Dow30期指", "YM")}
        for line in r.text.strip().split(chr(10)):
            if "hq_str_" not in line or "=" not in line:
                continue
            key = line.split("=")[0].split("_")[-1].strip()
            if key not in names:
                continue
            name, symbol = names[key]
            vals = line.split("=")[1].strip().strip('"').rstrip('",').split(",")
            if len(vals) < 9:
                continue
            try:
                price = float(vals[0])
                prev  = float(vals[2])
                change_pct = (price - prev) / prev * 100 if prev else 0.0
                result[key] = {"name": name, "symbol": symbol,
                               "price": price, "change_pct": change_pct}
            except (ValueError, IndexError):
                continue
        return result
    except Exception as e:
        print(f"⚠️ 美股期指获取失败: {e}")
        return {}


def fetch_forex():
    """获取主要汇率数据（新浪优先，东方财富兜底）"""
    result = _fetch_forex_sina()
    # 检查是否有缺失的货币对，用东方财富兜底
    expected_keys = ["USDCNY", "USDCNH", "EURUSD", "GBPUSD",
                     "NZDCNY", "AUDCNY", "CADCNY", "HKDCNY", "KRWCNY"]
    missing = [k for k in expected_keys if k not in result]
    if missing:
        print(f"  ⚠️ 新浪缺失 {len(missing)} 个货币对，尝试东方财富兜底...")
        fallback = _fetch_forex_eastmoney()
        for k in missing:
            if k in fallback:
                result[k] = fallback[k]
    # 最终兜底：如果东方财富也没有，尝试 akshare
    still_missing = [k for k in expected_keys if k not in result]
    if still_missing:
        print(f"  ⚠️ 东方财富仍缺失 {len(still_missing)} 个，尝试 akshare 兜底...")
        fallback2 = _fetch_forex_akshare()
        for k in still_missing:
            if k in fallback2:
                result[k] = fallback2[k]
    return result


def _fetch_forex_sina():
    """P1: 新浪外汇接口
    格式：USDCNY [1]=当前价 [8]=昨收；EURUSD [1]=当前价 [7]=昨收
    """
    try:
        import requests
        # 新浪外汇有两种格式，都试一下
        # 格式1: 直接货币对
        url = "https://hq.sinajs.cn/list=USDCNY,USDCNH,EURUSD,GBPUSD,NZDCNY,AUDCNY,CADCNY,HKDCNY,KRWCNY"
        headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "gbk"
        result = {}
        field_map = {
            "USDCNY": (1, 8, "美元/离岸人民币"),
            "USDCNH": (1, 8, "美元/在岸人民币"),
            "EURUSD": (1, 7, "欧元/美元"),
            "GBPUSD": (1, 7, "英镑/美元"),
            "NZDCNY": (1, 8, "新西兰元/人民币"),
            "AUDCNY": (1, 8, "澳元/人民币"),
            "CADCNY": (1, 8, "加拿大元/人民币"),
            "HKDCNY": (1, 8, "港币/人民币"),
            "KRWCNY": (1, 8, "韩元/人民币"),
        }
        for line in r.text.strip().split(chr(10)):
            if "hq_str_" not in line or "=" not in line:
                continue
            key = line.split("=")[0].split("_")[-1].strip()
            if key not in field_map:
                continue
            idx_price, idx_prev, name = field_map[key]
            vals = line.split("=")[1].strip().strip('"').rstrip('",').split(",")
            if len(vals) <= max(idx_price, idx_prev):
                continue
            try:
                price = float(vals[idx_price])
                prev  = float(vals[idx_prev])
                if price == 0 or prev == 0:
                    continue
                change_pct = (price - prev) / prev * 100
                result[key] = {"name": name, "symbol": key,
                               "price": price, "change_pct": change_pct}
            except (ValueError, IndexError):
                continue
        # 如果部分货币对没拿到，尝试 fx_s 前缀格式
        missing_keys = [k for k in field_map if k not in result]
        if missing_keys:
            fx_codes = ",".join([f"fx_s{k}" for k in missing_keys])
            url2 = f"https://hq.sinajs.cn/list={fx_codes}"
            try:
                r2 = requests.get(url2, headers=headers, timeout=10)
                r2.encoding = "gbk"
                for line in r2.text.strip().split(chr(10)):
                    if "hq_str_" not in line or "=" not in line:
                        continue
                    raw_key = line.split("=")[0].split("fx_s")[-1].strip()
                    if raw_key not in field_map:
                        continue
                    idx_price, idx_prev, name = field_map[raw_key]
                    vals = line.split("=")[1].strip().strip('"').rstrip('",').split(",")
                    if len(vals) <= max(idx_price, idx_prev):
                        continue
                    try:
                        price = float(vals[idx_price])
                        prev  = float(vals[idx_prev])
                        if price == 0 or prev == 0:
                            continue
                        change_pct = (price - prev) / prev * 100
                        result[raw_key] = {"name": name, "symbol": raw_key,
                                           "price": price, "change_pct": change_pct}
                    except (ValueError, IndexError):
                        continue
            except:
                pass
        return result
    except Exception as e:
        print(f"⚠️ 新浪汇率获取失败: {e}")
        return {}


def _fetch_forex_eastmoney():
    """P2: 东方财富外汇接口（兜底）
    接口: https://push2.eastmoney.com/api/qt/clist/get 外汇板块
    """
    try:
        import requests
        # 东方财富外汇实时数据
        # 119.USDCNY=美元兑人民币, 119.EURCNY=欧元兑人民币, etc.
        em_map = {
            "119.USDCNY": ("USDCNY", "美元/离岸人民币"),
            "119.EURCNY": ("EURUSD", "欧元/美元"),  # 需要反算
            "119.GBPCNY": ("GBPUSD", "英镑/美元"),  # 需要反算
            "119.NZDCNY": ("NZDCNY", "新西兰元/人民币"),
            "119.AUDCNY": ("AUDCNY", "澳元/人民币"),
            "119.CADCNY": ("CADCNY", "加拿大元/人民币"),
            "119.HKDCNY": ("HKDCNY", "港币/人民币"),
            "119.KRWCNY": ("KRWCNY", "韩元/人民币"),
        }
        secids = ",".join(em_map.keys())
        url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
               f"?fltt=2&invt=2&fields=f2,f3,f12,f14&secids={secids}")
        headers = {"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        result = {}
        for item in data.get('data', {}).get('diff', []):
            code = item.get('f12', '')
            price = item.get('f2')
            change_pct = item.get('f3')
            if price is None or change_pct is None:
                continue
            # 匹配到我们的 key
            for em_secid, (our_key, name) in em_map.items():
                if code in em_secid:
                    result[our_key] = {"name": name, "symbol": our_key,
                                       "price": float(price), "change_pct": float(change_pct)}
                    break
        return result
    except Exception as e:
        print(f"⚠️ 东方财富汇率获取失败: {e}")
        return {}


def _fetch_forex_akshare():
    """P3: akshare 外汇接口（最终兜底）"""
    try:
        import akshare as ak
        # akshare 外汇实时行情
        df = ak.currency_boc_safe()  # 中国银行外汇牌价
        result = {}
        name_map = {
            "美元": ("USDCNY", "美元/离岸人民币"),
            "新西兰元": ("NZDCNY", "新西兰元/人民币"),
            "澳大利亚元": ("AUDCNY", "澳元/人民币"),
            "加拿大元": ("CADCNY", "加拿大元/人民币"),
            "英镑": ("GBPUSD", "英镑/美元"),
            "欧元": ("EURUSD", "欧元/美元"),
            "港币": ("HKDCNY", "港币/人民币"),
            "韩国元": ("KRWCNY", "韩元/人民币"),
        }
        for _, row in df.iterrows():
            currency_name = row.get('货币名称', '')
            for cn_name, (key, display_name) in name_map.items():
                if cn_name in currency_name:
                    try:
                        # 中行牌价：中间价
                        price = float(row.get('中行折算价', 0)) / 100  # 中行报价单位是100外币
                        if price > 0:
                            result[key] = {"name": display_name, "symbol": key,
                                           "price": price, "change_pct": 0.0,
                                           "note": "中行牌价(无日内涨跌)"}
                    except:
                        pass
                    break
        return result
    except Exception as e:
        print(f"⚠️ akshare汇率获取失败: {e}")
        return {}


def fetch_commodities():
    """获取大宗商品数据（原油、黄金、白银）
    新浪hf_格式：[0]=当前价 [2]=昨收 [3]=今开 [4]=最高 [5]=最低
    """
    try:
        import requests
        url = "https://hq.sinajs.cn/list=hf_CL,hf_GC,hf_SI"
        headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "gbk"
        result = {}
        names = {"CL": ("WTI原油", "CL"),
                 "GC": ("黄金", "GC"),
                 "SI": ("白银", "SI")}
        for line in r.text.strip().split(chr(10)):
            if "hq_str_" not in line or "=" not in line:
                continue
            key = line.split("=")[0].split("_")[-1].strip()
            if key not in names:
                continue
            name, symbol = names[key]
            vals = line.split("=")[1].strip().strip('"').rstrip('",').split(",")
            if len(vals) < 9:
                continue
            try:
                price = float(vals[0])
                prev  = float(vals[2])
                change_pct = (price - prev) / prev * 100 if prev else 0.0
                result[key] = {"name": name, "symbol": symbol,
                               "price": price, "change_pct": change_pct}
            except (ValueError, IndexError):
                continue
        return result
    except Exception as e:
        print(f"⚠️ 大宗商品获取失败: {e}")
        return {}


def fetch_yesterday_vol(codes):
    """获取昨日成交量"""
    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    result = {}
    try:
        import akshare as ak
        for code in codes:
            df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                     start_date=yesterday, end_date=yesterday, adjust="qfq")
            if not df.empty:
                result[code] = float(df.iloc[0]['成交量'])
            else:
                result[code] = None
    except:
        for code in codes:
            result[code] = None
    return result


# ════════════════════════════════════════════════════════════
#  海外市场监控（非A股交易日模式）
# ════════════════════════════════════════════════════════════

def calc_score_overseas(change_pct, volatility_bonus=0):
    """海外异动评分"""
    return abs(change_pct) * 20 + volatility_bonus


def get_overseas_alert_level(score):
    if score >= 60:
        return "🔴 紧急"
    elif score >= 40:
        return "🟠 预警"
    elif score >= 25:
        return "🟡 关注"
    return "🟢 记录"


def build_overseas_message(item):
    """构建海外异动消息"""
    level = item["level"]
    name = item["name"]
    change = item["change_pct"]
    price = item.get("price", 0)
    score = item["score"]
    category = item.get("category", "海外")

    emoji_map = {"🔴": "📈", "🟠": "📊", "🟡": "📉", "🟢": "➖"}
    emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"

    # 涨跌说明
    if category == "汇率":
        direction = "升值" if change < 0 else "贬值"
    else:
        direction = "上涨" if change > 0 else "下跌" if change < 0 else "持平"

    msg = f"""🌏 【海外{level}】{datetime.now().strftime('%H:%M')}

🏷️ {category} | {name}
{emoji} {change:+.3f}% | 现价 {price:.4f}
🎯 异动得分：{score:.0f}/100

💡 市场解读：
- {name} {direction} {abs(change):.3f}%
- {'值得关注' if level in ['🔴 紧急','🟠 预警'] else '正常波动'}"""
    return msg


def scan_overseas_mode(dry_run=False):
    """非A股交易日：监控海外市场异动"""
    all_items = []

    # ── 美股期指 ──
    futures = fetch_us_futures()
    for key, data in futures.items():
        change_pct = data.get("change_pct", 0)
        if abs(change_pct) >= 0.3:
            score = calc_score_overseas(change_pct, 10)
            level = get_overseas_alert_level(score)
            item = {"type": "futures", "category": "美股期指",
                    "level": level, "score": score, **data}
            all_items.append(item)

    # ── 汇率 ──
    forex = fetch_forex()
    for key, data in forex.items():
        change_pct = data.get("change_pct", 0)
        if abs(change_pct) >= 0.3:
            score = calc_score_overseas(change_pct, 15)
            level = get_overseas_alert_level(score)
            item = {"type": "forex", "category": "汇率",
                    "level": level, "score": score, **data}
            all_items.append(item)

    # ── 大宗商品 ──
    commodities = fetch_commodities()
    for key, data in commodities.items():
        change_pct = data.get("change_pct", 0)
        if abs(change_pct) >= 0.5:
            score = calc_score_overseas(change_pct, 10)
            level = get_overseas_alert_level(score)
            item = {"type": "commodity", "category": "大宗商品",
                    "level": level, "score": score, **data}
            all_items.append(item)

    if dry_run:
        return all_items

    # ── 海外无异动：静默不输出 ──
    if not all_items:
        return []

    # 有异动时输出消息
    for item in sorted(all_items, key=lambda x: -x["score"]):
        print(build_overseas_message(item))

    return all_items


# ════════════════════════════════════════════════════════════
#  异动检测
# ════════════════════════════════════════════════════════════

def check_stock_alerts(stock_data, yesterday_vol, triggers):
    """检测个股异动"""
    alerts = []
    threshold = triggers["stock"]["threshold_pct"]
    vol_threshold = triggers["volume"]["threshold_pct"]

    for code, data in stock_data.items():
        change = data.get("change", 0)
        vol_today = data.get("volume", 0)
        vol_yest = yesterday_vol.get(code)

        vol_change_pct = None
        if vol_yest and vol_yest > 0:
            vol_change_pct = (vol_today - vol_yest) / vol_yest * 100

        triggered = False
        reasons = []

        if abs(change) >= threshold:
            triggered = True
            reasons.append(f"涨跌{change:+.2f}%")

        if vol_change_pct and vol_change_pct >= vol_threshold:
            triggered = True
            reasons.append(f"放量{vol_change_pct:+.1f}%")

        if triggered:
            score = calc_score(change, vol_change_pct or 0)
            alerts.append({
                "type": "stock",
                "code": code,
                "name": data["name"],
                "price": data["price"],
                "change": change,
                "vol_change": vol_change_pct,
                "score": score,
                "level": get_alert_level(score),
                "reasons": reasons,
                "cost": STOCKS.get(code, {}).get("cost"),
                "sector": STOCKS.get(code, {}).get("sector"),
            })

    return alerts


def check_etf_alerts(etf_data, triggers):
    """检测ETF异动"""
    alerts = []
    threshold = triggers["etf"]["threshold_pct"]

    for code, data in etf_data.items():
        change = data.get("change", 0)
        if abs(change) >= threshold:
            score = calc_score(change)
            alerts.append({
                "type": "etf",
                "code": code,
                "name": data["name"],
                "price": data["price"],
                "change": change,
                "score": score,
                "level": get_alert_level(score),
                "reasons": [f"ETF涨跌{change:+.2f}%"],
                "cost": ETFS.get(code, {}).get("cost"),
                "sector": ETFS.get(code, {}).get("sector"),
            })

    return alerts


def check_index_alerts(index_data, triggers):
    """检测大盘指数异动"""
    alerts = []
    threshold = triggers["index"]["threshold_pct"]

    for idx_code, data in index_data.items():
        change = abs(data.get("change", 0))
        if change >= threshold:
            score = change * 30  # 指数权重更高
            idx_name = triggers["index"]["index_names"].get(idx_code, idx_code)
            alerts.append({
                "type": "index",
                "code": idx_code,
                "name": idx_name,
                "price": data.get("change", 0),
                "change": data.get("change", 0),
                "score": score,
                "level": get_alert_level(score),
                "reasons": [f"大盘{data['change']:+.2f}%"],
            })

    return alerts


# ════════════════════════════════════════════════════════════
#  消息构建
# ════════════════════════════════════════════════════════════

def build_message(alert):
    """构建飞书推送消息"""
    level = alert["level"]
    name = alert["name"]
    code = alert["code"]
    change = alert["change"]
    price = alert.get("price", 0)
    reasons = " / ".join(alert["reasons"])
    score = alert["score"]
    sector = alert.get("sector", "")

    # 浮盈文字
    pnl_text = ""
    cost = alert.get("cost")
    if cost and cost > 0:
        pnl_pct = (price - cost) / cost * 100
        pnl_emoji = "✅" if pnl_pct >= 0 else "🔴"
        pnl_text = f"\n💰 持仓：{pnl_emoji} {pnl_pct:+.2f}%"

    # 成交量文字
    vol_text = ""
    vol_change = alert.get("vol_change")
    if vol_change is not None:
        vol_icon = "📈" if vol_change > 0 else "📉"
        vol_text = f"\n💧 量：{vol_icon} 较昨日 {vol_change:+.1f}%"

    # 来源标注
    source_tag = "🏠 个人持仓" if alert.get("source") == "personal" else "📁 基金穿透"
    overlap_tag = "\n⚠️ 【高重叠】该股被≥2只基金共同重仓" if alert.get("high_overlap") else ""

    type_label = {
        "stock": "个股异动",
        "etf": "ETF异动",
        "index": "大盘异动",
    }.get(alert["type"], "异动")

    msg = f"""📊 【{type_label}{level}】{datetime.now().strftime('%H:%M')}

{source_tag} | {name}（{code}）{overlap_tag}
📈 最新：{change:+.2f}%  |  现价：{price:.3f}
📌 触发：{reasons}{vol_text}{pnl_text}
🎯 异动得分：{score:.0f}/100

⏰ 操作建议：
- 现价 {price:.3f} 区域关注
- 结合大盘氛围判断

⚠️ 关联板块：{sector}"""

    return msg


# ════════════════════════════════════════════════════════════
#  主扫描流程
# ════════════════════════════════════════════════════════════

def scan(triggers_config=None, dry_run=False, json_output=False,
         stock_threshold=None, index_threshold=None, etf_threshold=None,
         volume_threshold=None, triggers_filter=None,
         include_funds=True):
    """
    执行市场异动扫描

    triggers_config: 触发条件配置字典（None则用默认）
    dry_run: 测试模式，不输出消息
    json_output: JSON格式输出
    stock_threshold / index_threshold / etf_threshold / volume_threshold: 覆盖阈值
    triggers_filter: list，只扫描指定类型，如 ["stock", "index"]
    """

    # 加载触发配置
    if triggers_config is None:
        triggers_config = DEFAULT_TRIGGERS.copy()

    # 命令行阈值覆盖
    if stock_threshold is not None:
        triggers_config["stock"]["threshold_pct"] = stock_threshold
    if index_threshold is not None:
        triggers_config["index"]["threshold_pct"] = index_threshold
    if etf_threshold is not None:
        triggers_config["etf"]["threshold_pct"] = etf_threshold
    if volume_threshold is not None:
        triggers_config["volume"]["threshold_pct"] = volume_threshold

    # triggers_filter：只启用指定类型
    if triggers_filter:
        for k in triggers_config:
            triggers_config[k]["enabled"] = (k in triggers_filter)

    print(f"\n{'='*50}")
    print(f"🕐 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── 非交易日：切换到海外监控模式 ──
    if not is_trading_day():
        print("📅 今日非A股交易日，切换至海外市场监控模式...")
        return scan_overseas_mode(dry_run=dry_run)

    if is_quiet_hours():
        print("🌙 静默时段（23:00-8:00），紧急异动仍会推送")
    print(f"{'='*50}")

    # 打印启用的触发条件
    enabled = [f"{k}(±{v['threshold_pct']}%)" for k, v in triggers_config.items() if v.get("enabled")]
    print(f"📡 启用的触发条件: {', '.join(enabled) if enabled else '无'}")

    all_alerts = []

    # ─── 持仓个股扫描（个人持仓 + 基金穿透持仓） ───
    if triggers_config.get("stock", {}).get("enabled"):
        # 合并个人持仓 + 基金持仓代码
        all_codes = get_all_monitored_codes(include_fund=include_funds)
        fund_overlap = get_fund_overlap_stocks()

        personal_codes = list(STOCKS.keys())
        fund_codes = [c for c in all_codes if c not in personal_codes]

        print(f"\n📡 扫描持仓个股（个人{personal_codes.__len__()}只 + 基金穿透{fund_codes.__len__()}只）...")

        # 合并批量拉取
        all_stock_codes = list(all_codes.keys())
        stock_data = fetch_realtime_stock(all_stock_codes)

        if stock_data:
            yesterday_vol = fetch_yesterday_vol(all_stock_codes)
            alerts = check_stock_alerts(stock_data, yesterday_vol, triggers_config)

            # 标注来源
            for a in alerts:
                code = a["code"]
                if code in personal_codes:
                    a["source"] = "personal"
                else:
                    a["source"] = "fund"
                    # 标注重叠股
                    if code in fund_overlap:
                        a["high_overlap"] = True

            all_alerts.extend(alerts)
            for a in alerts:
                src_tag = "🏠" if a["source"] == "personal" else "📁"
                overlap_tag = "⚠️" if a.get("high_overlap") else ""
                print(f"  {a['level']} {src_tag}{overlap_tag} {a['code']} {a['name']}: {a['change']:+.2f}% | 得分{a['score']:.0f}")

        # 打印基金持仓概况
        fund_data = load_fund_holdings()
        if fund_data:
            print(f"  📋 基金穿透覆盖: {len(fund_codes)}只 | 重叠监控: {len(fund_overlap)}只")

    # ─── ETF扫描 ───
    if triggers_config.get("etf", {}).get("enabled"):
        print(f"\n📡 扫描ETF持仓...")
        etf_data = fetch_realtime_etf(list(ETFS.keys()))
        alerts = check_etf_alerts(etf_data, triggers_config)
        all_alerts.extend(alerts)
        for a in alerts:
            print(f"  {a['level']} {a['code']} {a['name']}: {a['change']:+.2f}% | 得分{a['score']:.0f}")

    # ─── 大盘指数扫描 ───
    if triggers_config.get("index", {}).get("enabled"):
        print(f"\n📡 扫描大盘指数...")
        index_data = fetch_index_data()
        alerts = check_index_alerts(index_data, triggers_config)
        all_alerts.extend(alerts)
        for a in alerts:
            idx_val = a.get("price", a.get("change", 0))
            print(f"  {a['level']} {a['name']}: {idx_val:+.2f}% | 得分{a['score']:.0f}")

    # ─── 汇总 ───
    print(f"\n{'='*50}")
    print(f"📊 扫描完成: {len(all_alerts)} 条异动")
    if all_alerts:
        print(f"\n{'─'*40}")
        for a in sorted(all_alerts, key=lambda x: -x["score"]):
            print(f"  {a['level']} {a['name']}({a['code']}) | {' / '.join(a['reasons'])} | 得分{a['score']:.0f}")

    if json_output:
        print(json.dumps(all_alerts, ensure_ascii=False, indent=2))
        return all_alerts

    # 输出消息
    if all_alerts and not dry_run:
        print(f"\n{'─'*40}")
        print("📨 飞书推送预览:")
        for a in sorted(all_alerts, key=lambda x: -x["score"]):
            print(build_message(a))
            print()

    return all_alerts


# ════════════════════════════════════════════════════════════
#  命令行入口
# ════════════════════════════════════════════════════════════

def list_triggers():
    """列出所有触发条件"""
    print("\n📋 可配置的触发条件：\n")
    print(f"{'条件':<12} {'启用':<6} {'默认阈值':<12} {'说明'}")
    print("─"*65)
    for key, cfg in DEFAULT_TRIGGERS.items():
        enabled = "✅" if cfg.get("enabled") else "❌"
        thresh = f"±{cfg.get('threshold_pct', 'N/A')}% "
        if key == "index":
            thresh += f"(多指数)"
        elif key == "volume":
            thresh = f"+{cfg.get('threshold_pct', 'N/A')}% "
        print(f"{key:<12} {enabled:<6} {thresh:<12} {cfg.get('description', '')}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="沛柔专属市场异动扫描 · 支持条件触发配置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --list                          # 查看所有触发条件
  %(prog)s --triggers stock,index           # 只扫描个股+大盘
  %(prog)s --stock-threshold 5             # 个股阈值改为±5%%
  %(prog)s --index-threshold 0.8           # 大盘阈值改为±0.8%%
  %(prog)s --dry-run                        # 测试模式
  %(prog)s --json                           # JSON格式输出
        """
    )
    parser.add_argument("--triggers", metavar="KIND",
                        help="启用的触发条件，逗号分隔，如: stock,index,volume")
    parser.add_argument("--stock-threshold", type=float, metavar="PCT",
                        help=f"个股涨跌阈值（默认: {DEFAULT_TRIGGERS['stock']['threshold_pct']}%%）")
    parser.add_argument("--index-threshold", type=float, metavar="PCT",
                        help=f"大盘指数阈值（默认: {DEFAULT_TRIGGERS['index']['threshold_pct']}%%）")
    parser.add_argument("--etf-threshold", type=float, metavar="PCT",
                        help=f"ETF涨跌阈值（默认: {DEFAULT_TRIGGERS['etf']['threshold_pct']}%%）")
    parser.add_argument("--volume-threshold", type=float, metavar="PCT",
                        help=f"成交量突增阈值（默认: {DEFAULT_TRIGGERS['volume']['threshold_pct']}%%）")
    parser.add_argument("--dry-run", action="store_true", help="测试模式，不输出消息")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    parser.add_argument("--list", action="store_true", help="列出所有触发条件")
    parser.add_argument("--include-funds", action="store_true", default=True,
                        help="包含基金穿透持仓（默认开启）")
    parser.add_argument("--no-funds", dest="include_funds", action="store_false",
                        help="关闭基金穿透持仓，仅扫描个人持仓")

    args = parser.parse_args()

    if args.list:
        list_triggers()
        sys.exit(0)

    # 解析 triggers_filter
    triggers_filter = None
    if args.triggers:
        triggers_filter = [t.strip() for t in args.triggers.split(",")]

    scan(
        dry_run=args.dry_run,
        json_output=args.json,
        stock_threshold=args.stock_threshold,
        index_threshold=args.index_threshold,
        etf_threshold=args.etf_threshold,
        volume_threshold=args.volume_threshold,
        triggers_filter=triggers_filter,
        include_funds=args.include_funds,
    )
