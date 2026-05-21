#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[09] src/bazi_chart_day.py - 标准盘 + 流年 + 流月 + 流日叠加
调用层级：被 bin/bazi 调用（daily 模式）
依赖：src/bazi_chart_month.py [08]

职责：
  接收 bazi_chart_month 的输出（流月盘），叠加指定流日干支，
  计算流日与原局/大运/流年/流月的刑冲合关系，输出完整的"流日盘"。

  日运分析直接调用本文件的输出，lib/daily_fortune 按日粒度分析时用这个。

输出结构：
  {
    "success": true,
    "base_chart":   原始标准盘
    "liuyear":      流年摘要
    "liuyue":       流月摘要
    "liuri":        流日干支详情 + 黄历信息 + 与各层的刑冲合
    "context":      运势层级摘要（大运 + 流年 + 流月 + 流日）
    "interactions": 流日与各层的刑冲合汇总
  }

调用方式（命令行）：
  python3 src/bazi_chart_day.py --year 1995 --month 9 --day 4 \
    --hour 21 --minute 44 --gender male --city 江阴 \
    --liuyear 2026 --liuyue-month 4 --liuri-date 2026-04-15

调用方式（Python）：
  from bazi_chart_day import build_day_chart
  day_chart = build_day_chart(month_chart, liuri_date='2026-04-15')
"""

import os
import sys
import json
import argparse
from datetime import datetime, date
from typing import Optional

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_SKILL_DIR, 'vendor'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from lunar_python import Solar
    HAS_LUNAR = True
except ImportError:
    HAS_LUNAR = False

from bazi_chart import build_bazi_chart
from bazi_chart_year import (
    build_year_chart,
    _ten_god, _calc_gan_interactions,
    _summarize_interactions,
    GAN_WUXING, ZHI_WUXING, ZHI_CANGYGAN,
)
from bazi_chart_month import build_month_chart

# 导入 lib/zhi_relations 作为统一的地支关系分析引擎
_LIB_DIR = os.path.join(_SKILL_DIR, 'lib')
sys.path.insert(0, _LIB_DIR)
try:
    from zhi_relations import analyze_zhi_relations
    HAS_ZHI_RELATIONS = True
except ImportError:
    HAS_ZHI_RELATIONS = False
    # 降级：使用 bazi_chart_year 的简化版
    from bazi_chart_year import _calc_zhi_interactions

DIRECTION_CN = {
    '艮':'东北','震':'正东','巽':'东南','离':'正南',
    '坤':'西南','兑':'正西','乾':'西北','坎':'正北','中':'中央',
}


# ─────────────────────────────────────────────────────────────────
# 流日干支 + 黄历
# ─────────────────────────────────────────────────────────────────

def _get_day_ganzhi_and_huangli(date_str: str, hour: int = 8) -> dict:
    """
    通过 lunar_python 获取指定日期的干支和黄历信息。
    date_str: 'YYYY-MM-DD'
    """
    if not HAS_LUNAR:
        return {'error': 'vendor/lunar_python 未找到'}
    try:
        y, m, d = [int(x) for x in date_str.split('-')]
        solar = Solar.fromYmdHms(y, m, d, hour, 0, 0)
        lunar = solar.getLunar()
        pos = {
            'xi':  f"{lunar.getDayPositionXi()}（{DIRECTION_CN.get(lunar.getDayPositionXi(),'')}）",
            'cai': f"{lunar.getDayPositionCai()}（{DIRECTION_CN.get(lunar.getDayPositionCai(),'')}）",
            'fu':  f"{lunar.getDayPositionFu()}（{DIRECTION_CN.get(lunar.getDayPositionFu(),'')}）",
        }
        return {
            'date':       date_str,
            'lunar_date': f"{lunar.getYearInChinese()}年{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
            'ganzhi': {
                'year':  lunar.getYearInGanZhi(),
                'month': lunar.getMonthInGanZhi(),
                'day':   lunar.getDayInGanZhi(),
            },
            'day_gz': lunar.getDayInGanZhi(),
            'huangli': {
                'yi':       lunar.getDayYi(),
                'ji':       lunar.getDayJi(),
                'zhi_xing': lunar.getZhiXing(),
                'chong':    lunar.getDayChong(),
                'sha':      lunar.getDaySha(),
                'nayin':    lunar.getDayNaYin(),
            },
            'positions': pos,
        }
    except Exception as e:
        return {'error': str(e)}


# ─────────────────────────────────────────────────────────────────
# 核心函数
# ─────────────────────────────────────────────────────────────────

def build_day_chart(month_chart: dict, liuri_date: str = None, hour: int = 8) -> dict:
    """
    在流月盘基础上叠加流日，生成流日盘。

    参数：
      month_chart: bazi_chart_month.build_month_chart() 的完整输出
      liuri_date:  流日日期 'YYYY-MM-DD'，默认今天
      hour:        时辰（0-23），用于黄历时辰干支，默认早8点

    返回：
      包含原盘 + 流年 + 流月 + 流日叠加信息的完整流日盘
    """
    if not month_chart.get('success'):
        return {'success': False, 'error': '流月盘无效'}

    target_date = liuri_date or date.today().strftime('%Y-%m-%d')

    base_chart   = month_chart.get('base_chart', {})
    liuyear_info = month_chart.get('liuyear', {})
    liuyue_info  = month_chart.get('liuyue', {})
    dayun_info   = month_chart.get('dayun', {})
    day_gan      = base_chart.get('day_gan', '')
    pillars      = base_chart.get('pillars', [])

    liuyear_gz = liuyear_info.get('ganzhi', '')
    liuyue_gz  = liuyue_info.get('ganzhi', '')
    dayun_gz   = dayun_info.get('ganzhi', '')

    # ── 1. 获取流日干支和黄历 ──────────────────────────────────────
    day_data = _get_day_ganzhi_and_huangli(target_date, hour)
    if 'error' in day_data:
        return {'success': False, 'error': day_data['error']}

    day_gz  = day_data['day_gz']
    day_gan_ri = day_gz[0] if len(day_gz) >= 2 else ''
    day_zhi_ri = day_gz[1] if len(day_gz) >= 2 else ''

    # ── 2. 收集所有地支（原局 + 大运 + 流年 + 流月）──────────────
    yuanju_zhis = {p['zhi'] for p in pillars if 'zhi' in p}
    yuanju_gans = {p['gan'] for p in pillars if 'gan' in p}

    dayun_zhi   = dayun_gz[1]   if len(dayun_gz)   >= 2 else ''
    dayun_gan   = dayun_gz[0]   if len(dayun_gz)   >= 2 else ''
    liuyear_zhi = liuyear_gz[1] if len(liuyear_gz) >= 2 else ''
    liuyear_gan = liuyear_gz[0] if len(liuyear_gz) >= 2 else ''
    liuyue_zhi  = liuyue_gz[1]  if len(liuyue_gz)  >= 2 else ''
    liuyue_gan  = liuyue_gz[0]  if len(liuyue_gz)  >= 2 else ''

    base_zhis = (yuanju_zhis
                 | ({dayun_zhi}   if dayun_zhi   else set())
                 | ({liuyear_zhi} if liuyear_zhi else set())
                 | ({liuyue_zhi}  if liuyue_zhi  else set()))
    base_gans = (yuanju_gans
                 | ({dayun_gan}   if dayun_gan   else set())
                 | ({liuyear_gan} if liuyear_gan else set())
                 | ({liuyue_gan}  if liuyue_gan  else set()))

    # ── 3. 计算流日与各层的刑冲合 ─────────────────────────────────
    # 收集所有层级天干（用于透出检查）
    all_tiangan = list(yuanju_gans)
    for gz in [dayun_gz, liuyear_gz, liuyue_gz, day_gz]:
        if gz and len(gz) >= 1:
            all_tiangan.append(gz[0])

    if HAS_ZHI_RELATIONS:
        # 使用 lib/zhi_relations.py 统一引擎（与 daily_fortune.py 同源）
        existing_zhis = frozenset(base_zhis - {day_zhi_ri})
        full_relations = analyze_zhi_relations(day_zhi_ri, existing_zhis, all_tiangan=all_tiangan)
        # 转换为 interactions 输出格式
        zhi_interactions = []
        for rel in full_relations.get('relations', []):
            zhi_b = rel.get('partner', '')
            if not zhi_b and rel.get('members'):
                # 三会/三合：取非自身的成员
                members = rel['members']
                zhi_b = ''.join(m for m in members if m != day_zhi_ri)
            zhi_interactions.append({
                'type': rel['type'],
                'zhi_a': day_zhi_ri,
                'zhi_b': zhi_b,
                'desc': rel.get('name', '') or rel.get('desc', ''),
                'effect': rel.get('desc', ''),
                'weight': rel.get('weight', 0),
                'element': rel.get('element', ''),
                'is_positive': rel.get('is_positive', True),
            })
    else:
        # 降级：使用简化版
        zhi_interactions = _calc_zhi_interactions(day_zhi_ri, base_zhis)

    gan_interactions = _calc_gan_interactions(day_gan_ri, base_gans)

    # 标注来源
    pillar_names = {p['zhi']: p['name'] for p in pillars}
    pillar_names[dayun_zhi]   = '大运'
    pillar_names[liuyear_zhi] = '流年'
    pillar_names[liuyue_zhi]  = '流月'
    interaction_detail = []
    for item in zhi_interactions:
        source = pillar_names.get(item.get('zhi_b', ''), '未知')
        interaction_detail.append({**item, 'source': source})

    # ── 4. 组装流日盘 ──────────────────────────────────────────────
    context = month_chart.get('context', {})
    layer_desc = f"{dayun_gz}大运 × {liuyear_gz}流年 × {liuyue_gz}流月 × {day_gz}流日（{target_date}）"

    day_chart = {
        'success': True,
        'chart_type': 'day',

        # 原始标准盘
        'base_chart': base_chart,

        # 流年摘要
        'liuyear': liuyear_info,

        # 流月摘要
        'liuyue': liuyue_info,

        # 当前大运摘要
        'dayun': dayun_info,

        # 流日信息
        'liuri': {
            'date':       target_date,
            'ganzhi':     day_gz,
            'gan':        day_gan_ri,
            'zhi':        day_zhi_ri,
            'gan_wuxing': GAN_WUXING.get(day_gan_ri, ''),
            'zhi_wuxing': ZHI_WUXING.get(day_zhi_ri, ''),
            'gan_shishen': _ten_god(day_gan, day_gan_ri),
            'zhi_shishen': _ten_god(day_gan, ZHI_CANGYGAN.get(day_zhi_ri, [''])[0]),
            'cangygan':   ZHI_CANGYGAN.get(day_zhi_ri, []),
            'cangygan_shishen': [
                {'gan': g, 'wuxing': GAN_WUXING.get(g,''), 'shishen': _ten_god(day_gan, g)}
                for g in ZHI_CANGYGAN.get(day_zhi_ri, [])
            ],
            'lunar_date': day_data.get('lunar_date', ''),
            'huangli':    day_data.get('huangli', {}),
            'positions':  day_data.get('positions', {}),
        },

        # 运势层级上下文
        'context': {
            'layer_desc':  layer_desc,
            'dayun_gz':    dayun_gz,
            'liuyear_gz':  liuyear_gz,
            'liuyue_gz':   liuyue_gz,
            'liuri_gz':    day_gz,
            'liuri_date':  target_date,
            'month_index': context.get('month_index', ''),
            'liuyear':     context.get('liuyear', ''),
        },

        # 刑冲合汇总
        'interactions': {
            'zhi': interaction_detail,
            'gan': gan_interactions,
            'summary': _summarize_interactions(zhi_interactions + gan_interactions),
        },

        # 供 lib/daily_fortune 直接使用的 prompt 数据
        'prompt_context': {
            'day_gan':    day_gan,
            'all_zhis':   list(base_zhis | ({day_zhi_ri} if day_zhi_ri else set())),
            'layer_desc': layer_desc,
        },

        'generated_at': datetime.now().isoformat(),
    }

    return day_chart


# ─────────────────────────────────────────────────────────────────
# 命令行入口
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='八字流日盘')
    parser.add_argument('--year',         type=int, required=True)
    parser.add_argument('--month',        type=int, required=True)
    parser.add_argument('--day',          type=int, required=True)
    parser.add_argument('--hour',         type=int, required=True)
    parser.add_argument('--minute',       type=int, default=0)
    parser.add_argument('--gender',       type=str, default='male')
    parser.add_argument('--city',         type=str, default='')
    parser.add_argument('--liuyear',      type=int, default=None)
    parser.add_argument('--liuyue-month', type=int, default=None)
    parser.add_argument('--liuyue-gz',    type=str, default=None)
    parser.add_argument('--liuri-date',   type=str, default=None, help='流日日期 YYYY-MM-DD，默认今天')
    parser.add_argument('--query-hour',   type=int, default=8,    help='查询时辰（0-23），用于黄历')
    args = parser.parse_args()

    liuyear = args.liuyear or datetime.now().year

    base_chart  = build_bazi_chart(
        year=args.year, month=args.month, day=args.day,
        hour=args.hour, minute=args.minute,
        gender=args.gender, city=args.city,
        current_year=liuyear,
    )
    year_chart  = build_year_chart(base_chart, liuyear=liuyear)
    month_chart = build_month_chart(
        year_chart,
        liuyue_month=args.liuyue_month,
        liuyue_gz=args.liuyue_gz,
    )
    result = build_day_chart(
        month_chart,
        liuri_date=args.liuri_date,
        hour=args.query_hour,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
