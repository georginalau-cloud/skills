#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[07] src/bazi_chart_year.py - 标准盘 + 流年叠加
调用层级：被 bin/bazi 调用（monthly/daily 模式）
依赖：src/bazi_chart.py [06]

职责：
  接收 bazi_chart 的输出（标准盘），叠加指定流年干支，
  计算流年与原局/大运的刑冲合关系，输出完整的"流年盘"。

  这是月运/日运分析的基础层，bazi_chart_month 和 bazi_chart_day
  都以本文件的输出作为输入。

输出结构：
  {
    "success": true,
    "base_chart":   原始标准盘（bazi_chart 完整输出）
    "liuyear":      流年干支详情 + 与原局/大运的刑冲合
    "context":      当前运势层级摘要（大运 + 流年）
    "interactions": 流年与各柱的刑冲合汇总
  }

调用方式（命令行）：
  python3 src/bazi_chart_year.py --year 1995 --month 9 --day 4 \
    --hour 21 --minute 44 --gender male --city 江阴 --liuyear 2026

调用方式（Python）：
  from bazi_chart_year import build_year_chart
  year_chart = build_year_chart(base_chart, liuyear=2026)
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, Optional

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_SKILL_DIR, 'vendor'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bazi_chart import build_bazi_chart

# ─────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────

GAN_WUXING = {
    '甲': '木', '乙': '木', '丙': '火', '丁': '火', '戊': '土',
    '己': '土', '庚': '金', '辛': '金', '壬': '水', '癸': '水',
}
ZHI_WUXING = {
    '子': '水', '丑': '土', '寅': '木', '卯': '木', '辰': '土', '巳': '火',
    '午': '火', '未': '土', '申': '金', '酉': '金', '戌': '土', '亥': '水',
}
ZHI_CANGYGAN = {
    '子': ['癸'], '丑': ['己', '癸', '辛'], '寅': ['甲', '丙', '戊'],
    '卯': ['乙'], '辰': ['戊', '乙', '癸'], '巳': ['丙', '戊', '庚'],
    '午': ['丁', '己'], '未': ['己', '丁', '乙'], '申': ['庚', '壬', '戊'],
    '酉': ['辛'], '戌': ['戊', '辛', '丁'], '亥': ['壬', '甲'],
}
TEN_GODS = {
    '甲': {'甲':'比','乙':'劫','丙':'食','丁':'伤','戊':'才','己':'财','庚':'杀','辛':'官','壬':'枭','癸':'印'},
    '乙': {'甲':'劫','乙':'比','丙':'伤','丁':'食','戊':'财','己':'才','庚':'官','辛':'杀','壬':'印','癸':'枭'},
    '丙': {'甲':'枭','乙':'印','丙':'比','丁':'劫','戊':'食','己':'伤','庚':'才','辛':'财','壬':'杀','癸':'官'},
    '丁': {'甲':'印','乙':'枭','丙':'劫','丁':'比','戊':'伤','己':'食','庚':'财','辛':'才','壬':'官','癸':'杀'},
    '戊': {'甲':'杀','乙':'官','丙':'枭','丁':'印','戊':'比','己':'劫','庚':'食','辛':'伤','壬':'才','癸':'财'},
    '己': {'甲':'官','乙':'杀','丙':'印','丁':'枭','戊':'劫','己':'比','庚':'伤','辛':'食','壬':'财','癸':'才'},
    '庚': {'甲':'才','乙':'财','丙':'杀','丁':'官','戊':'枭','己':'印','庚':'比','辛':'劫','壬':'食','癸':'伤'},
    '辛': {'甲':'财','乙':'才','丙':'官','丁':'杀','戊':'印','己':'枭','庚':'劫','辛':'比','壬':'伤','癸':'食'},
    '壬': {'甲':'食','乙':'伤','丙':'才','丁':'财','戊':'杀','己':'官','庚':'枭','辛':'印','壬':'比','癸':'劫'},
    '癸': {'甲':'伤','乙':'食','丙':'财','丁':'才','戊':'官','己':'杀','庚':'印','辛':'枭','壬':'劫','癸':'比'},
}
CHONG = {'子':'午','午':'子','丑':'未','未':'丑','寅':'申','申':'寅','卯':'酉','酉':'卯','辰':'戌','戌':'辰','巳':'亥','亥':'巳'}
HE6   = {'子':'丑','丑':'子','寅':'亥','亥':'寅','卯':'戌','戌':'卯','辰':'酉','酉':'辰','巳':'申','申':'巳','午':'未','未':'午'}
XING  = {'子':'卯','卯':'子','寅':'巳','巳':'申','申':'寅','丑':'戌','戌':'未','未':'丑','辰':'辰','午':'午','酉':'酉','亥':'亥'}
SANHE = [({'申','子','辰'},'水局'),({'寅','午','戌'},'火局'),({'巳','酉','丑'},'金局'),({'亥','卯','未'},'木局')]
SANHUI = [({'寅','卯','辰'},'木','东方三会木局'),({'巳','午','未'},'火','南方三会火局'),({'申','酉','戌'},'金','西方三会金局'),({'亥','子','丑'},'水','北方三会水局')]
HAI = {'子':'未','未':'子','丑':'午','午':'丑','寅':'巳','巳':'寅','卯':'辰','辰':'卯','申':'亥','亥':'申','酉':'戌','戌':'酉'}
GAN_HE = {'甲':'己','己':'甲','乙':'庚','庚':'乙','丙':'辛','辛':'丙','丁':'壬','壬':'丁','戊':'癸','癸':'戊'}
GAN_CHONG = {'甲':'庚','庚':'甲','乙':'辛','辛':'乙','丙':'壬','壬':'丙','丁':'癸','癸':'丁'}

# 流年干支表（1900-2100）
_GAN = ['甲','乙','丙','丁','戊','己','庚','辛','壬','癸']
_ZHI = ['子','丑','寅','卯','辰','巳','午','未','申','酉','戌','亥']

def _year_to_ganzhi(year: int) -> str:
    gan = _GAN[(year - 4) % 10]
    zhi = _ZHI[(year - 4) % 12]
    return gan + zhi


# ─────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────

def _ten_god(day_gan: str, gan: str) -> str:
    return TEN_GODS.get(day_gan, {}).get(gan, '')


def _ganzhi_detail(gz: str, day_gan: str) -> dict:
    if not gz or len(gz) < 2:
        return {}
    gan, zhi = gz[0], gz[1]
    cangygan = ZHI_CANGYGAN.get(zhi, [])
    return {
        'ganzhi':      gz,
        'gan':         gan,
        'zhi':         zhi,
        'gan_wuxing':  GAN_WUXING.get(gan, ''),
        'zhi_wuxing':  ZHI_WUXING.get(zhi, ''),
        'gan_shishen': _ten_god(day_gan, gan),
        'zhi_shishen': _ten_god(day_gan, cangygan[0]) if cangygan else '',
        'cangygan':    cangygan,
        'cangygan_shishen': [
            {'gan': g, 'wuxing': GAN_WUXING.get(g, ''), 'shishen': _ten_god(day_gan, g)}
            for g in cangygan
        ],
    }


def _calc_zhi_interactions(zhi_new: str, zhi_set: set) -> list:
    """计算一个新地支与已有地支集合的刑冲合关系（含三会局、六害）。"""
    results = []
    all_zhis = zhi_set | {zhi_new}

    # 三会局（力量最强，优先检测）
    for members, element, name in SANHUI:
        if zhi_new in members and members.issubset(all_zhis):
            # 找出另外两个参与的地支
            others = [z for z in members if z != zhi_new]
            for other in others:
                results.append({'type':'三会','zhi_a':zhi_new,'zhi_b':other,'desc':f'{name}（{zhi_new}+{other}+{[z for z in members if z != zhi_new and z != other][0] if len(others)>1 else ""}）','effect':f'{element}五行力量极强，可改变格局'})
            # 只输出一条三会记录，不重复
            results = [r for r in results if r['type'] != '三会']
            others_str = ''.join(sorted(members))
            results.append({'type':'三会','zhi_a':zhi_new,'zhi_b':''.join(sorted(members - {zhi_new})),'desc':f'{name}（{"".join(sorted(members))}）','effect':f'{element}五行力量极强，可改变格局','members':list(members)})
            break  # 一个地支只能参与一个三会

    for zhi_b in zhi_set:
        if zhi_b == zhi_new:
            continue
        if CHONG.get(zhi_new) == zhi_b:
            results.append({'type':'冲','zhi_a':zhi_new,'zhi_b':zhi_b,'desc':f'{zhi_new}冲{zhi_b}','effect':'动荡变化，需防意外'})
        if HE6.get(zhi_new) == zhi_b:
            results.append({'type':'合','zhi_a':zhi_new,'zhi_b':zhi_b,'desc':f'{zhi_new}合{zhi_b}','effect':'有助力（合而不化，各自五行属性保留）'})
        if XING.get(zhi_new) == zhi_b and zhi_new != zhi_b:
            results.append({'type':'刑','zhi_a':zhi_new,'zhi_b':zhi_b,'desc':f'{zhi_new}刑{zhi_b}','effect':'摩擦压力，需谨慎'})
        if HAI.get(zhi_new) == zhi_b:
            results.append({'type':'害','zhi_a':zhi_new,'zhi_b':zhi_b,'desc':f'{zhi_new}害{zhi_b}','effect':'暗中损耗，需防小人或暗伤'})
    # 自刑
    if XING.get(zhi_new) == zhi_new and zhi_new in zhi_set:
        results.append({'type':'自刑','zhi_a':zhi_new,'zhi_b':zhi_new,'desc':f'{zhi_new}{zhi_new}自刑','effect':'内耗，需注意自我管理'})
    # 三合（检查新地支加入后是否凑成三合）
    for members, ju_name in SANHE:
        if zhi_new in members:
            all_present = members.issubset(zhi_set | {zhi_new})  # 三支必须全部存在
            if all_present:
                results.append({'type':'三合','members':list(members),'zhi_a':zhi_new,'zhi_b':''.join(sorted(members - {zhi_new})),'desc':f'三合{ju_name}（{"".join(sorted(members))}）','effect':'力量聚合，大有助益'})
    return results


def _calc_gan_interactions(gan_new: str, gan_set: set) -> list:
    """计算一个新天干与已有天干集合的合冲关系。"""
    results = []
    for gan_b in gan_set:
        if GAN_HE.get(gan_new) == gan_b:
            results.append({'type':'天干合','gan_a':gan_new,'gan_b':gan_b,'desc':f'{gan_new}合{gan_b}','effect':'化合，力量转化'})
        if GAN_CHONG.get(gan_new) == gan_b:
            results.append({'type':'天干冲','gan_a':gan_new,'gan_b':gan_b,'desc':f'{gan_new}冲{gan_b}','effect':'相克，需防冲突'})
    return results


def _get_liuyue_from_chart(base_chart: dict, liuyear: int) -> list:
    """
    从 base_chart 的 dayun_list 中找到指定流年的流月列表。
    如果找不到（流年不在当前大运展开范围内），返回空列表。
    """
    for dayun in base_chart.get('dayun_list', []):
        for ln in dayun.get('liu_nian', []):
            if ln.get('year') == liuyear:
                return ln.get('liu_yue', [])
    return []


# ─────────────────────────────────────────────────────────────────
# 核心函数
# ─────────────────────────────────────────────────────────────────

def build_year_chart(base_chart: dict, liuyear: int) -> dict:
    """
    在标准盘基础上叠加流年，生成流年盘。

    参数：
      base_chart: bazi_chart.build_bazi_chart() 的完整输出
      liuyear:    要分析的流年（公历年份，如 2026）

    返回：
      包含原盘 + 流年叠加信息的完整流年盘
    """
    if not base_chart.get('success'):
        return {'success': False, 'error': '基础标准盘无效'}

    day_gan = base_chart.get('day_gan', '')
    pillars = base_chart.get('pillars', [])

    # ── 1. 流年干支 ────────────────────────────────────────────────
    liuyear_gz = _year_to_ganzhi(liuyear)

    # 尝试从 base_chart 的 dayun_list 中找到更精确的流年信息（含空亡）
    liuyear_from_chart = None
    for dayun in base_chart.get('dayun_list', []):
        for ln in dayun.get('liu_nian', []):
            if ln.get('year') == liuyear:
                liuyear_from_chart = ln
                break
        if liuyear_from_chart:
            break

    if liuyear_from_chart:
        liuyear_detail = liuyear_from_chart
    else:
        liuyear_detail = _ganzhi_detail(liuyear_gz, day_gan)
        liuyear_detail['year'] = liuyear
        liuyear_detail['xun_kong'] = ''

    # ── 2. 找当前大运 ──────────────────────────────────────────────
    current_dayun = None
    for dayun in base_chart.get('dayun_list', []):
        if dayun.get('start_year', 9999) <= liuyear <= dayun.get('end_year', 0):
            current_dayun = dayun
            break
    # fallback：用 base_chart 自带的 current
    if not current_dayun and base_chart.get('current'):
        current_dayun = base_chart['current'].get('dayun')

    dayun_gz = current_dayun.get('ganzhi', '') if current_dayun else ''

    # ── 3. 收集所有地支（原局 + 大运）用于刑冲合计算 ──────────────
    yuanju_zhis = {p['zhi'] for p in pillars if 'zhi' in p}
    yuanju_gans = {p['gan'] for p in pillars if 'gan' in p}

    dayun_zhi = dayun_gz[1] if len(dayun_gz) >= 2 else ''
    dayun_gan = dayun_gz[0] if len(dayun_gz) >= 2 else ''

    base_zhis = yuanju_zhis | ({dayun_zhi} if dayun_zhi else set())
    base_gans = yuanju_gans | ({dayun_gan} if dayun_gan else set())

    liuyear_zhi = liuyear_gz[1] if len(liuyear_gz) >= 2 else ''
    liuyear_gan = liuyear_gz[0] if len(liuyear_gz) >= 2 else ''

    # ── 4. 计算流年与原局+大运的刑冲合 ───────────────────────────
    zhi_interactions = _calc_zhi_interactions(liuyear_zhi, base_zhis)
    gan_interactions = _calc_gan_interactions(liuyear_gan, base_gans)

    # 按柱标注刑冲合来源
    interaction_detail = []
    pillar_names = {p['zhi']: p['name'] for p in pillars}
    pillar_names[dayun_zhi] = '大运' if dayun_zhi else ''

    for item in zhi_interactions:
        source = pillar_names.get(item.get('zhi_b', ''), '未知')
        interaction_detail.append({**item, 'source': source})

    # ── 5. 流月列表（从 base_chart 中提取，或标注需单独计算）──────
    liu_yue = _get_liuyue_from_chart(base_chart, liuyear)

    # ── 6. 组装流年盘 ──────────────────────────────────────────────
    year_chart = {
        'success': True,
        'chart_type': 'year',

        # 原始标准盘（完整保留）
        'base_chart': base_chart,

        # 流年信息
        'liuyear': {
            'year':        liuyear,
            'ganzhi':      liuyear_gz,
            'gan':         liuyear_gan,
            'zhi':         liuyear_zhi,
            'gan_wuxing':  GAN_WUXING.get(liuyear_gan, ''),
            'zhi_wuxing':  ZHI_WUXING.get(liuyear_zhi, ''),
            'gan_shishen': _ten_god(day_gan, liuyear_gan),
            'zhi_shishen': _ten_god(day_gan, ZHI_CANGYGAN.get(liuyear_zhi, [''])[0]),
            'cangygan':    ZHI_CANGYGAN.get(liuyear_zhi, []),
            'xun_kong':    liuyear_detail.get('xun_kong', ''),
            'age':         liuyear_detail.get('age', ''),
            'liu_yue':     liu_yue,
        },

        # 当前大运摘要
        'dayun': {
            'ganzhi':     dayun_gz,
            'start_year': current_dayun.get('start_year', '') if current_dayun else '',
            'end_year':   current_dayun.get('end_year', '') if current_dayun else '',
            'gan_shishen': current_dayun.get('gan_shishen', '') if current_dayun else '',
            'zhi_shishen': current_dayun.get('zhi_shishen', '') if current_dayun else '',
        },

        # 运势层级上下文
        'context': {
            'layer_desc': f'{dayun_gz}大运 × {liuyear_gz}流年（{liuyear}年）',
            'dayun_gz':   dayun_gz,
            'liuyear_gz': liuyear_gz,
            'liuyear':    liuyear,
        },

        # 刑冲合汇总
        'interactions': {
            'zhi': interaction_detail,
            'gan': gan_interactions,
            'summary': _summarize_interactions(zhi_interactions + gan_interactions),
        },

        'generated_at': datetime.now().isoformat(),
    }

    # 修正 age 字段（简化计算）
    birth_year_str = base_chart.get('meta', {}).get('solar_date', '')[:4]
    if birth_year_str.isdigit():
        year_chart['liuyear']['age'] = liuyear - int(birth_year_str) + 1

    return year_chart


def _summarize_interactions(interactions: list) -> str:
    """将刑冲合列表转为简短文字摘要。"""
    if not interactions:
        return '流年与命局无明显刑冲合'
    parts = [item['desc'] for item in interactions]
    return '；'.join(parts)


# ─────────────────────────────────────────────────────────────────
# 命令行入口
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='八字流年盘')
    parser.add_argument('--year',         type=int, required=True, help='出生年')
    parser.add_argument('--month',        type=int, required=True, help='出生月')
    parser.add_argument('--day',          type=int, required=True, help='出生日')
    parser.add_argument('--hour',         type=int, required=True, help='出生时')
    parser.add_argument('--minute',       type=int, default=0)
    parser.add_argument('--gender',       type=str, default='male')
    parser.add_argument('--city',         type=str, default='')
    parser.add_argument('--liuyear',      type=int, default=None, help='流年（公历年份），默认今年')
    parser.add_argument('--chart-file',   type=str, default=None, help='已有标准盘 JSON 文件路径')
    args = parser.parse_args()

    liuyear = args.liuyear or datetime.now().year

    # 加载或生成标准盘
    if args.chart_file:
        with open(args.chart_file, 'r', encoding='utf-8') as f:
            base_chart = json.load(f)
    else:
        base_chart = build_bazi_chart(
            year=args.year, month=args.month, day=args.day,
            hour=args.hour, minute=args.minute,
            gender=args.gender, city=args.city,
            current_year=liuyear,
        )

    result = build_year_chart(base_chart, liuyear=liuyear)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
