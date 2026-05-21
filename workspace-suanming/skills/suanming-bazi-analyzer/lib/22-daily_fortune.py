#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[22] lib/daily_fortune.py - 日运分析模块
调用层级：被 bin/bazi（daily 模式）调用
依赖：vendor/lunar_python

功能：
  1. 计算当日干支（年/月/日/时）
  2. 获取黄历宜忌、建除十二值星、吉神方位
  3. 分析当日干支与命局（原局 + 大运 + 流年 + 流月）的关系
  4. 生成日运 prompt 供 MiniMax 润色

层级：原局 → 大运 → 流年 → 流月 → 流日（完整五层）
"""

import os
import sys
from datetime import date
from typing import Dict

_LIB_DIR   = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_LIB_DIR)
sys.path.insert(0, os.path.join(_SKILL_DIR, 'vendor'))
sys.path.insert(0, os.path.join(_SKILL_DIR, 'src'))

try:
    from lunar_python import Solar
    HAS_LUNAR = True
except ImportError:
    HAS_LUNAR = False

# ─────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────

ZHI_CANGYGAN = {
    '子':['癸'],'丑':['己','癸','辛'],'寅':['甲','丙','戊'],
    '卯':['乙'],'辰':['戊','乙','癸'],'巳':['丙','戊','庚'],
    '午':['丁','己'],'未':['己','丁','乙'],'申':['庚','壬','戊'],
    '酉':['辛'],'戌':['戊','辛','丁'],'亥':['壬','甲'],
}
CHONG = {
    '子':'午','午':'子','丑':'未','未':'丑',
    '寅':'申','申':'寅','卯':'酉','酉':'卯',
    '辰':'戌','戌':'辰','巳':'亥','亥':'巳',
}
HE6 = {
    '子':'丑','丑':'子','寅':'亥','亥':'寅',
    '卯':'戌','戌':'卯','辰':'酉','酉':'辰',
    '巳':'申','申':'巳','午':'未','未':'午',
}
XING = {
    '子':'卯','卯':'子',
    '寅':'巳','巳':'申','申':'寅',
    '丑':'戌','戌':'未','未':'丑',
}
SANHE = [
    ({'申','子','辰'}, '水局'),
    ({'寅','午','戌'}, '火局'),
    ({'巳','酉','丑'}, '金局'),
    ({'亥','卯','未'}, '木局'),
]
DIRECTION_CN = {
    '艮':'东北','震':'正东','巽':'东南','离':'正南',
    '坤':'西南','兑':'正西','乾':'西北','坎':'正北','中':'中央',
}
LUCKY_COLORS = {
    '木':['绿色','青色'],'火':['红色','橙色','紫色'],
    '土':['黄色','棕色','米色'],'金':['白色','金色','银色'],
    '水':['黑色','深蓝色','灰色'],
}
# 按十神大类的幸运色优先级（用于流日动态调整）
SHISHEN_COLOR_HINTS = {
    '官': '金（白色、金色、银色），提升贵气与决策力',
    '杀': '金+水组合，白色金色纳气，紫黑色化煞',
    '财': '火（红橙紫）旺财，赤红色系开运',
    '才': '火（红橙紫）旺偏财，忌绿色青色的散财色',
    '食': '土（黄色、棕色）生金，忌辛辣冲胃',
    '伤': '金（白色、金色）制伤，忌红色橙色过旺',
    '印': '金水（白、黑）养印，忌土色过重沉闷',
    '枭': '水（黑、深蓝）化枭，忌土色克水',
    '比': '金水（白、黑）润比，忌火色过旺冲动',
    '劫': '水（黑、深蓝）化劫，忌红色冲动色',
}
# 食物按十神推荐
SHISHEN_FOOD_HINTS = {
    '官': '清淡养胃（小米粥、莲子、山药），忌辛辣',
    '杀': '白色食物（银耳、百合、梨）化煞，忌红油重口',
    '财': '红色系食物（红枣、枸杞、红豆）旺财',
    '才': '红色系+高蛋白（羊肉、牛肉、红椒）旺偏财',
    '食': '黄色系（玉米、南瓜、黄豆）养脾，忌生冷',
    '伤': '白色润肺（梨、银耳、百合），忌辛辣刺激',
    '印': '黑色系（黑豆、黑木耳、海带）养印，忌过咸',
    '枭': '水润食品（莲子心茶、薏米水）化枭，忌油炸',
    '比': '黑色食品（黑芝麻糊、黑豆）润比，忌熬夜',
    '劫': '水+收敛（蜂蜜水、百合、梨）化躁，忌刺激性',
}
# 流日干支五行权重（用于判断当日能量侧重）
STEM_WUXING = {'甲':'木','乙':'木','丙':'火','丁':'火','戊':'土','己':'土','庚':'金','辛':'金','壬':'水','癸':'水'}
BRANCH_WUXING = {'子':'水','丑':'土','寅':'木','卯':'木','辰':'土','巳':'火','午':'火','未':'土','申':'金','酉':'金','戌':'土','亥':'水'}
SHISHEN_FULL = {
    '比':'比肩','劫':'劫财','食':'食神','伤':'伤官',
    '才':'偏财','财':'正财','杀':'七杀','官':'正官',
    '枭':'偏印','印':'正印','日主':'日主',
}
# 五行对应食物（用于动态食物推荐，与幸运色同逻辑）
WUXING_FOODS = {
    '木': {'good': '绿叶蔬菜、菠菜、芹菜、青椒、猕猴桃、绿茶', 'avoid': '酸味过重食物'},
    '火': {'good': '辣椒、红色食物、烤制食品、羊肉、红枣、枸杞', 'avoid': '冰饮、生冷食物'},
    '土': {'good': '黄色食物（玉米、南瓜、黄豆）、山药、小米粥、红薯', 'avoid': '过甜食物'},
    '金': {'good': '白色食物（银耳、百合、梨、莲子、山药）、鸡肉', 'avoid': '辛辣刺激'},
    '水': {'good': '黑色食物（黑豆、黑芝麻、海带、紫菜）、鱼类、汤品', 'avoid': '过咸食物'},
}


# ─────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────

def _get_interactions(zhi_a, zhi_set):
    notes = []
    for zhi_b in zhi_set:
        if zhi_b == zhi_a:
            continue
        if CHONG.get(zhi_a) == zhi_b:
            notes.append({'type':'冲','desc':f'{zhi_a}冲{zhi_b}','effect':'动荡变化，需防意外'})
        if HE6.get(zhi_a) == zhi_b:
            notes.append({'type':'合','desc':f'{zhi_a}合{zhi_b}','effect':'有助力，贵人相助'})
        if XING.get(zhi_a) == zhi_b:
            notes.append({'type':'刑','desc':f'{zhi_a}刑{zhi_b}','effect':'摩擦压力，需谨慎'})
    for members, ju_name in SANHE:
        if zhi_a in members and members.issubset(zhi_set | {zhi_a}):
            notes.append({'type':'三合','desc':f'三合{ju_name}','effect':'力量聚合，大有助益'})
            break
    return notes


def _score_day(day_gz, day_gan, all_zhis):
    from .ten_gods_analyzer import get_ten_god
    if not day_gz or len(day_gz) < 2:
        return {}
    gan, zhi = day_gz[0], day_gz[1]
    shishen_gan  = get_ten_god(day_gan, gan)
    cangygan     = ZHI_CANGYGAN.get(zhi, [])
    shishen_zhi  = get_ten_god(day_gan, cangygan[0]) if cangygan else ''
    interactions = _get_interactions(zhi, all_zhis)

    score = 0
    notes = []
    GOOD = {'印','枭','官','财','才','食'}
    BAD  = {'杀','劫','伤'}
    if shishen_gan in GOOD:
        score += 1
        notes.append(f'日干{gan}（{SHISHEN_FULL.get(shishen_gan,shishen_gan)}）对命局有利')
    elif shishen_gan in BAD:
        score -= 1
        notes.append(f'日干{gan}（{SHISHEN_FULL.get(shishen_gan,shishen_gan)}）需注意压力')

    for inter in interactions:
        if inter['type'] == '冲':
            score -= 2
            notes.append(f"{inter['desc']}，{inter['effect']}")
        elif inter['type'] == '合':
            score += 1
            notes.append(f"{inter['desc']}，{inter['effect']}")
        elif inter['type'] == '刑':
            score -= 1
            notes.append(f"{inter['desc']}，{inter['effect']}")
        elif inter['type'] == '三合':
            score += 2
            notes.append(f"{inter['desc']}，{inter['effect']}")

    rating = '吉' if score >= 2 else ('需防' if score < 0 else '平')
    return {
        'score': score, 'rating': rating,
        'shishen_gan': shishen_gan, 'shishen_zhi': shishen_zhi,
        'interactions': interactions, 'notes': notes,
    }


# ─────────────────────────────────────────────────────────────────
# 动态幸运色/食物计算
# ─────────────────────────────────────────────────────────────────

def _compute_lucky(day_gan, day_gan_shishen, day_zhi_shishen, day_zhi, day_cangygan,
                   yong_shen, yong_wuxing,
                   has_chong, has_xing, has_he, has_sanhe,
                   day_analysis, relations=None, ji_shen=None, xi_shen=None):
    """
    根据流日十神与命局的互动关系，动态计算当日幸运色、食物、方位说明。

    核心思路（v3 完善版）：
    1. 用神色为基础底色
    2. 流日地支关系按力量排序，最强关系主导颜色调整
    3. 病药通关：忌神五行被强化时，用通关五行颜色化解
    4. 偏枯/极端判断：用神五行太旺时也需要制衡（泄气或生身）
    5. 日主身强/身弱影响：身弱需要生扶色，身强需要泄耗色
    6. 忌色逻辑：忌的是克用神的五行色 + 助忌神的五行色

    五行生克链：
      相生：木→火→土→金→水→木
      相克：木→土→水→火→金→木

    忌色原理（不是简单的"忌绿色因为木泄火气"）：
      - 忌克用神的五行色（如用神火，金克火，忌白色金色）
      - 忌助忌神的五行色（如忌神土，火生土，忌红色助长忌神）
      - 但如果用神本身太旺（三会/三合用神局），需要泄气，此时泄用神的五行反而是好的

    参数：
    - relations: zhi_relations.analyze_zhi_relations() 的完整结果（含 weight）
    - ji_shen: 忌神五行列表（如 ['土']）
    - xi_shen: 喜神五行列表（如 ['木']）
    """
    add_colors = []
    avoid_colors = []
    foods = []
    note_parts = []

    # 基础底色：用神五行对应色
    base_colors = LUCKY_COLORS.get(yong_shen, [])

    # 忌神/喜神默认值
    if ji_shen is None:
        ji_shen = []
    if xi_shen is None:
        xi_shen = []

    # 五行生克关系
    SHENG_CHAIN = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
    KE_CHAIN = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}
    # 反向：谁生我、谁克我
    SHENG_WO = {'木': '水', '火': '木', '土': '火', '金': '土', '水': '金'}  # 生我的五行
    KE_WO = {'木': '金', '火': '水', '土': '木', '金': '火', '水': '土'}    # 克我的五行

    # ── 0. 计算当日五行力量格局 ─────────────────────────────────────
    # 统计当日所有层级中各五行的力量
    day_wuxing_strength = {'木': 0, '火': 0, '土': 0, '金': 0, '水': 0}
    # 流日天干五行
    day_gan_wx = STEM_WUXING.get(day_gan, '')
    if day_gan_wx:
        day_wuxing_strength[day_gan_wx] += 1.0
    # 流日地支五行
    day_zhi_wx = BRANCH_WUXING.get(day_zhi, '')
    if day_zhi_wx:
        day_wuxing_strength[day_zhi_wx] += 1.2  # 地支力量略大于天干
    # 流日藏干五行
    for cg in day_cangygan:
        cg_wx = STEM_WUXING.get(cg, '')
        if cg_wx:
            day_wuxing_strength[cg_wx] += 0.5

    # 从 relations 中统计被强化的五行
    yong_shen_boosted = False  # 用神是否被三会/三合强化
    ji_shen_boosted = False    # 忌神是否被强化
    boosted_element = ''
    boosted_weight = 0

    if relations and relations.get('relations'):
        for rel in relations['relations']:
            rel_elem = rel.get('element', '')
            rel_weight = abs(rel.get('weight', 0))
            is_positive = rel.get('is_positive', True)
            if rel_elem and is_positive and rel_weight >= 2.5:
                day_wuxing_strength[rel_elem] = day_wuxing_strength.get(rel_elem, 0) + rel_weight
                if rel_elem == yong_shen:
                    yong_shen_boosted = True
                    boosted_element = rel_elem
                    boosted_weight = rel_weight
                elif rel_elem in ji_shen:
                    ji_shen_boosted = True
                    boosted_element = rel_elem
                    boosted_weight = rel_weight

    # ── 1. 判断是否存在偏枯/极端情况 ─────────────────────────────────
    # 偏枯：某一五行力量远超其他（>= 5.0），需要制衡
    max_wx = max(day_wuxing_strength, key=day_wuxing_strength.get)
    max_wx_val = day_wuxing_strength[max_wx]
    avg_wx_val = sum(day_wuxing_strength.values()) / 5

    is_extreme = max_wx_val >= 5.0 and max_wx_val >= avg_wx_val * 3

    if is_extreme:
        # 极端偏枯：最旺五行需要泄气或制衡
        xie_wx = SHENG_CHAIN.get(max_wx, '')  # 旺五行所生的（泄气）
        if max_wx == yong_shen:
            # 用神太旺（罕见但可能：如三会用神局）
            # 此时不能再加强用神色，需要用泄气色来平衡
            add_colors += LUCKY_COLORS.get(xie_wx, [])[:2]
            # 用神色本身不忌，但不再作为主推
            note_parts.append(f'今日{max_wx}五行极旺（用神大旺），需{xie_wx}色泄气平衡，避免过犹不及')
        elif max_wx in ji_shen:
            # 忌神极旺：用通关五行化解
            tong_guan = _get_tongguan_element(max_wx, yong_shen)
            if tong_guan:
                add_colors += LUCKY_COLORS.get(tong_guan, [])[:2]
                note_parts.append(f'今日忌神{max_wx}极旺，需{tong_guan}色通关化解')
            avoid_colors += LUCKY_COLORS.get(max_wx, [])
        else:
            # 非用神非忌神的五行极旺
            # 判断对日主的影响
            if KE_CHAIN.get(max_wx) == STEM_WUXING.get(day_gan, ''):
                # 极旺五行克日主 → 需要化解
                tong_guan = _get_tongguan_element(max_wx, yong_shen)
                if tong_guan:
                    add_colors += LUCKY_COLORS.get(tong_guan, [])[:1]
                    note_parts.append(f'今日{max_wx}极旺克身，{tong_guan}色化解')
            else:
                note_parts.append(f'今日{max_wx}五行极旺，能量偏重')

    # ── 2. 力量主导：根据当日最强关系决定颜色调整 ─────────────────────
    elif relations and relations.get('relations'):
        rel_list = relations['relations']
        if rel_list:
            dominant = rel_list[0]
            dominant_element = dominant.get('element', '')
            dominant_weight = abs(dominant.get('weight', 0))
            dominant_positive = dominant.get('is_positive', True)
            dominant_type = dominant.get('type', '')
            dominant_name = dominant.get('name', '')

            if dominant_weight >= 3.0:
                # 三会/三合级别（极强）
                if dominant_positive:
                    if dominant_element == yong_shen:
                        # 用神五行被极强聚合
                        # 判断是否过旺（用神太旺也不好）
                        if day_wuxing_strength.get(yong_shen, 0) >= 4.5:
                            # 用神已经很旺了，再加强会过犹不及
                            xie_wx = SHENG_CHAIN.get(yong_shen, '')
                            add_colors += LUCKY_COLORS.get(xie_wx, [])[:1]
                            note_parts.append(f'今日{dominant_name}，用神{yong_shen}大旺，适当用{xie_wx}色泄气平衡')
                        else:
                            add_colors += LUCKY_COLORS.get(yong_shen, [])
                            note_parts.append(f'今日{dominant_name}，用神{yong_shen}大旺，运势极佳，大胆用{yong_shen}色')
                    elif dominant_element in ji_shen:
                        # 忌神五行被极强聚合 → 需要通关
                        tong_guan = _get_tongguan_element(dominant_element, yong_shen)
                        if tong_guan:
                            add_colors += LUCKY_COLORS.get(tong_guan, [])
                            note_parts.append(f'今日{dominant_name}，忌神{dominant_element}极旺，需{tong_guan}色通关化解')
                        else:
                            add_colors += LUCKY_COLORS.get(yong_shen, [])
                            note_parts.append(f'今日{dominant_name}，忌神{dominant_element}极旺，用{yong_shen}色对抗')
                        avoid_colors += LUCKY_COLORS.get(dominant_element, [])
                    else:
                        # 非用神非忌神的五行被聚合 → 看对日主的影响
                        ri_zhu_wx = STEM_WUXING.get(day_gan, '')
                        if dominant_element == SHENG_WO.get(ri_zhu_wx, ''):
                            # 生日主的五行被强化 → 身旺，可以用财官色
                            note_parts.append(f'今日{dominant_name}，{dominant_element}生身，精力充沛')
                        elif dominant_element == KE_WO.get(ri_zhu_wx, ''):
                            # 克日主的五行被强化 → 压力大
                            add_colors += LUCKY_COLORS.get(SHENG_WO.get(ri_zhu_wx, ''), [])[:1]
                            note_parts.append(f'今日{dominant_name}，{dominant_element}克身，需生扶色护身')
                        else:
                            note_parts.append(f'今日{dominant_name}，{dominant_element}五行极强')
                else:
                    # 负面关系（冲/刑）且力量极强
                    # 被冲的五行需要保护 → 用生扶被冲五行的颜色
                    chong_target_wx = dominant.get('element', '')
                    sheng_target = SHENG_WO.get(chong_target_wx, '')
                    if sheng_target:
                        add_colors += LUCKY_COLORS.get(sheng_target, [])[:2]
                        note_parts.append(f'今日{dominant_name}，动荡极大，{sheng_target}色系稳住气场')
                    else:
                        add_colors += ['白色', '金色', '银色']
                        note_parts.append(f'今日{dominant_name}，动荡极大，白金银色系稳住气场')

            elif dominant_weight >= 2.0:
                # 六合/六冲级别（中等）
                if not dominant_positive:
                    # 有冲/刑 → 需要化解
                    chong_target_wx = dominant.get('element', '')
                    sheng_target = SHENG_WO.get(chong_target_wx, '')
                    if sheng_target:
                        add_colors += LUCKY_COLORS.get(sheng_target, [])[:1]
                    note_parts.append(f'今日{dominant_name}，宜静不宜躁，{sheng_target or "金"}色系可稳住气场')
                else:
                    note_parts.append(f'今日{dominant_name}，运势稳聚，用神{yong_shen}色可以发挥')

            elif dominant_weight >= 1.0:
                if not dominant_positive:
                    note_parts.append(f'今日{dominant_name}，小有压力，注意情绪')
                else:
                    note_parts.append(f'今日{dominant_name}，小有助力')
    else:
        # 没有传入 relations，降级使用旧的布尔逻辑
        if has_chong:
            add_colors += ['白色', '金色']
            note_parts.append('今日地支与命局有冲，宜静不宜躁，白金色系可稳住气场')
        elif has_xing:
            add_colors += ['白色', '银色']
            note_parts.append('今日地支与命局有刑，压力略重，白银色系化煞')
        elif has_he or has_sanhe:
            note_parts.append('今日地支与命局有合，运势稳聚，用神色可以发挥')

    # ── 3. 病药通关：检查当日是否有忌神被强化的情况 ─────────────────────
    if relations and relations.get('relations') and not any('忌神' in n for n in note_parts):
        for rel in relations['relations']:
            rel_elem = rel.get('element', '')
            rel_weight = abs(rel.get('weight', 0))
            if rel_elem in ji_shen and rel.get('is_positive', False) and rel_weight >= 2.0:
                tong_guan = _get_tongguan_element(rel_elem, yong_shen)
                if tong_guan and tong_guan not in [c.replace('色', '') for c in add_colors]:
                    add_colors += LUCKY_COLORS.get(tong_guan, [])[:1]
                    note_parts.append(f'{rel_elem}忌神有聚合，{tong_guan}色通关')
                break

    # ── 4. 忌色逻辑（严谨版）─────────────────────────────────────────
    # 忌色原则：
    #   A. 克用神的五行色（如用神火，金克火 → 忌白色金色）
    #   B. 助忌神的五行色（如忌神土，火生土 → 忌红色）
    #   C. 但如果用神太旺需要泄气，则泄用神的五行色反而是好的，不忌
    if yong_shen and not is_extreme:
        # A. 克用神的五行
        ke_yong = KE_WO.get(yong_shen, '')
        if ke_yong:
            ke_yong_colors = LUCKY_COLORS.get(ke_yong, [])
            for c in ke_yong_colors:
                if c not in avoid_colors and c not in add_colors:
                    avoid_colors.append(c)

    if ji_shen and not is_extreme:
        # B. 助忌神的五行（生忌神的五行）
        for js in ji_shen:
            sheng_ji = SHENG_WO.get(js, '')  # 生忌神的五行
            if sheng_ji and sheng_ji != yong_shen:
                sheng_ji_colors = LUCKY_COLORS.get(sheng_ji, [])
                for c in sheng_ji_colors:
                    if c not in avoid_colors and c not in add_colors:
                        avoid_colors.append(c)

    # ── 5. 喜神色作为辅助加强 ──────────────────────────────────────────
    if xi_shen:
        for xs in xi_shen:
            xs_colors = LUCKY_COLORS.get(xs, [])
            if xs_colors and xs_colors[0] not in add_colors and xs_colors[0] not in avoid_colors:
                add_colors.append(xs_colors[0])

    # ── 6. 天干十神作为辅助参考（不再主导） ────────────────────────────
    gan_hint = SHISHEN_COLOR_HINTS.get(day_gan_shishen, '')
    if gan_hint and not note_parts:
        note_parts.append(f'今日天干{day_gan_shishen}当令，{gan_hint}')

    # ── 6.5 食物推荐（与幸运色同逻辑）────────────────────────────────
    # 基础：用神五行食物
    base_food = WUXING_FOODS.get(yong_shen, {}).get('good', '')
    avoid_food = ''

    if is_extreme:
        # 极端偏枯：用泄气五行的食物
        xie_wx = SHENG_CHAIN.get(max_wx, '')
        if max_wx == yong_shen and xie_wx:
            # 用神太旺，用泄气五行食物平衡
            base_food = WUXING_FOODS.get(xie_wx, {}).get('good', base_food)
            foods.append(f'今日{yong_shen}极旺，宜{xie_wx}性食物平衡：{base_food}')
        elif max_wx in ji_shen:
            # 忌神极旺，用通关五行食物
            tong_guan = _get_tongguan_element(max_wx, yong_shen)
            if tong_guan:
                tg_food = WUXING_FOODS.get(tong_guan, {}).get('good', '')
                foods.append(f'忌神{max_wx}极旺，宜{tong_guan}性食物通关：{tg_food}')
            avoid_food = WUXING_FOODS.get(max_wx, {}).get('good', '')
            foods.append(f'忌：{avoid_food}（助长忌神{max_wx}）')
        else:
            foods.append(f'适宜：{base_food}')
    elif yong_shen_boosted and day_wuxing_strength.get(yong_shen, 0) >= 4.5:
        # 用神被强化且已经很旺
        xie_wx = SHENG_CHAIN.get(yong_shen, '')
        xie_food = WUXING_FOODS.get(xie_wx, {}).get('good', '') if xie_wx else ''
        foods.append(f'用神{yong_shen}大旺，适当搭配{xie_wx}性食物：{xie_food}')
    elif ji_shen_boosted:
        # 忌神被强化
        tong_guan = _get_tongguan_element(boosted_element, yong_shen)
        if tong_guan:
            tg_food = WUXING_FOODS.get(tong_guan, {}).get('good', '')
            foods.append(f'宜{tong_guan}性食物：{tg_food}')
        ji_food = WUXING_FOODS.get(boosted_element, {}).get('good', '')
        foods.append(f'忌：{ji_food}（助长忌神）')
    else:
        # 正常情况：用神食物 + 十神辅助
        foods.append(f'适宜：{base_food}')
        food_hint = SHISHEN_FOOD_HINTS.get(day_gan_shishen, '')
        if food_hint:
            foods.append(food_hint)

    # 忌食：克用神的五行食物 + 助忌神的五行食物
    if not avoid_food and yong_shen:
        ke_yong_wx = KE_WO.get(yong_shen, '')
        if ke_yong_wx:
            avoid_food_item = WUXING_FOODS.get(ke_yong_wx, {}).get('good', '')
            if avoid_food_item and not any('忌' in f for f in foods):
                foods.append(f'避免：{avoid_food_item}（{ke_yong_wx}克{yong_shen}）')

    # ── 7. 综合颜色优先级合并 ────────────────────────────────────────
    final_colors = base_colors.copy()
    for c in add_colors:
        if c not in final_colors:
            final_colors.append(c)
    final_colors = [c for c in final_colors if c not in avoid_colors]
    final_colors = final_colors[:4]

    note = '；'.join(note_parts) if note_parts else f'今日能量平稳，用神{yong_shen}色为主'
    return {
        'add_colors':   add_colors,
        'avoid_colors': avoid_colors,
        'avoid_reason': _build_avoid_reason(avoid_colors, yong_shen, ji_shen, is_extreme),
        'foods':        '；'.join(foods) if foods else f'今日饮食清淡为宜',
        'note':         note,
    }


def _build_avoid_reason(avoid_colors, yong_shen, ji_shen, is_extreme):
    """
    为忌色生成解释说明（供 LLM 输出时引用，避免胡说八道）。

    返回格式：{'颜色': '原因'}
    """
    SHENG_CHAIN = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
    KE_WO = {'木': '金', '火': '水', '土': '木', '金': '火', '水': '土'}
    SHENG_WO = {'木': '水', '火': '木', '土': '火', '金': '土', '水': '金'}

    reasons = {}
    ke_yong = KE_WO.get(yong_shen, '')
    ke_yong_colors = LUCKY_COLORS.get(ke_yong, []) if ke_yong else []

    for c in avoid_colors:
        if c in ke_yong_colors:
            reasons[c] = f'{ke_yong}克{yong_shen}（用神），忌{ke_yong}色系'
        else:
            # 查找是哪个忌神的生扶色
            for js in ji_shen:
                sheng_ji = SHENG_WO.get(js, '')
                if sheng_ji and c in LUCKY_COLORS.get(sheng_ji, []):
                    reasons[c] = f'{sheng_ji}生{js}（忌神），助长忌神力量'
                    break
            if c not in reasons:
                reasons[c] = '与今日气场不合'

    return reasons


def _get_tongguan_element(bing_element, yong_shen):
    """
    病药通关：根据"病"（被强化的忌神五行）和用神，找到通关五行。
    """
    sheng_chain = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
    ke_chain = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}

    # 方案1：病所生的五行（泄病气）
    xie_bing = sheng_chain.get(bing_element, '')
    if xie_bing and xie_bing != yong_shen:
        # 检查泄病的五行是否克用神
        if ke_chain.get(xie_bing) != yong_shen:
            return xie_bing

    # 方案2：克病的五行
    for elem, target in ke_chain.items():
        if target == bing_element and elem != yong_shen:
            # 检查克病的五行是否也克用神
            if ke_chain.get(elem) != yong_shen:
                return elem

    # 方案3：用神本身就是通关
    return yong_shen


def _merge_lucky_colors(base_colors, add_colors, avoid_colors):
    """合并用神底色 + 流日动态调整色，避免色移除 """
    merged = list(base_colors)
    for c in add_colors:
        if c not in merged:
            merged.append(c)
    merged = [c for c in merged if c not in avoid_colors]
    return merged[:4]   # 最多4种


def get_ten_god_cached(stem):
    """已知天干查十神（供藏干分析用）"""
    from .ten_gods_analyzer import get_ten_god as _gtg
    return lambda day_gan: _gtg(day_gan, stem)


# ─────────────────────────────────────────────────────────────────
# 主分析器
# ─────────────────────────────────────────────────────────────────

class DailyFortune:
    """日运分析器，接收 bazi_chart 完整输出。"""

    def __init__(self, chart):
        self.chart   = chart
        self.day_gan = chart.get('day_gan', '')
        gender_raw   = chart.get('meta', {}).get('gender', 'male')
        self.gender  = 'male' if gender_raw.lower() in ('male','m','男') else 'female'
        pillars      = chart.get('pillars', [])
        self.yuanju_zhis = {p['zhi'] for p in pillars if 'zhi' in p}
        current          = chart.get('current', {})
        self.dayun_gz    = current.get('dayun', {}).get('ganzhi', '') if current else ''
        liuyear          = current.get('liuyear', {}) if current else {}
        self.year_gz     = liuyear.get('ganzhi', '') if liuyear else ''
        self.liu_yue     = liuyear.get('liu_yue', []) if liuyear else []

    def _get_day_data(self, target_date, hour=8):
        if not HAS_LUNAR:
            return {'error': 'vendor/lunar_python 未找到'}
        try:
            y, m, d = [int(x) for x in target_date.split('-')]
            solar   = Solar.fromYmdHms(y, m, d, hour, 0, 0)
            lunar   = solar.getLunar()
            pos     = {
                'xi':  f"{lunar.getDayPositionXi()}（{DIRECTION_CN.get(lunar.getDayPositionXi(),'')}）",
                'cai': f"{lunar.getDayPositionCai()}（{DIRECTION_CN.get(lunar.getDayPositionCai(),'')}）",
                'fu':  f"{lunar.getDayPositionFu()}（{DIRECTION_CN.get(lunar.getDayPositionFu(),'')}）",
            }
            return {
                'date':       target_date,
                'lunar_date': f"{lunar.getYearInChinese()}年{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
                'ganzhi': {
                    'year':  lunar.getYearInGanZhi(),
                    'month': lunar.getMonthInGanZhi(),
                    'day':   lunar.getDayInGanZhi(),
                    'hour':  lunar.getTime().getGanZhi(),
                },
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

    def _get_month_gz(self, target_date):
        if not self.liu_yue:
            return ''
        try:
            month = int(target_date.split('-')[1])
            idx   = (month - 2) % 12
            if idx < len(self.liu_yue):
                return self.liu_yue[idx].get('ganzhi', '')
        except Exception:
            pass
        return ''

    def analyze(self, target_date=None, hour=8):
        """
        分析指定日期的日运。

        参数：
          target_date: 'YYYY-MM-DD'，默认今天
          hour: 时辰（0-23），默认早8点
        """
        if not target_date:
            target_date = date.today().strftime('%Y-%m-%d')

        day_data = self._get_day_data(target_date, hour)
        if 'error' in day_data:
            return {'success': False, 'error': day_data['error']}

        day_gz   = day_data['ganzhi']['day']
        month_gz = self._get_month_gz(target_date)

        # 所有层级地支集合
        all_zhis = set(self.yuanju_zhis)
        for gz in [self.dayun_gz, self.year_gz, month_gz]:
            if gz and len(gz) >= 2:
                all_zhis.add(gz[1])

        day_analysis  = _score_day(day_gz, self.day_gan, all_zhis)
        yong_shen     = (
            self.chart.get('yong_shen', {}).get('yong_shen', '')
            or self.chart.get('analysis', {}).get('format_analysis', {}).get('yong_shen', '')
        )
        ji_shen       = (
            self.chart.get('yong_shen', {}).get('ji_shen', [])
            or self.chart.get('analysis', {}).get('format_analysis', {}).get('ji_shen', [])
        )

        # ── 流日干支分析（用于动态幸运色/食物/方位）─────────────────────
        day_gan = day_gz[0] if len(day_gz) >= 1 else ''
        day_zhi = day_gz[1] if len(day_gz) >= 2 else ''
        day_cangygan = ZHI_CANGYGAN.get(day_zhi, [])
        # 计算流日对日主构成的十神（主十神 = 天干十神；副十神 = 藏干十神，取旺者）
        from .ten_gods_analyzer import get_ten_god
        day_gan_shishen = get_ten_god(self.day_gan, day_gan) if day_gan else ''
        # 藏干十神取最旺者（按通根程度简化：第一个藏干为主）
        day_zhi_shishen = get_ten_god(self.day_gan, day_cangygan[0]) if day_cangygan else ''
        # 流日地支与命局的冲合（有冲则能量强，可加重某色）
        day_zhi_interacts = _get_interactions(day_zhi, all_zhis) if day_zhi else []
        has_chong = any(i['type'] == '冲' for i in day_zhi_interacts)
        has_xing  = any(i['type'] == '刑' for i in day_zhi_interacts)
        has_he    = any(i['type'] == '合' for i in day_zhi_interacts)
        has_sanhe = any(i['type'] == '三合' for i in day_zhi_interacts)

        # 用神/忌神五行
        yong_wuxing = STEM_WUXING.get(yong_shen, '') if len(yong_shen) == 1 else ''

        # ── 完整地支关系分析（用于力量主导的幸运色计算）─────────────────
        # 收集所有层级天干（用于透出检查）
        all_tiangan = list(self.yuanju_gans)  # 原局四柱天干
        for gz in [self.dayun_gz, self.year_gz, month_gz, day_gz]:
            if gz and len(gz) >= 1:
                all_tiangan.append(gz[0])

        # 使用 lib/zhi_relations.py 的完整分析引擎
        try:
            from .zhi_relations import analyze_zhi_relations
            existing_zhis_for_day = frozenset(all_zhis - {day_zhi})
            full_relations = analyze_zhi_relations(day_zhi, existing_zhis_for_day, all_tiangan=all_tiangan)
        except (ImportError, Exception):
            full_relations = None

        # 喜神五行列表
        xi_shen_list = []
        if yong_shen:
            xi_shen_list = [STEM_WUXING.get(yong_shen, '')] if len(yong_shen) == 1 else []

        # ── 动态幸运色：根据流日十神 + 命局互动 综合判断 ─────────────────
        lucky_result = _compute_lucky(
            day_gan=day_gan,
            day_gan_shishen=day_gan_shishen,
            day_zhi_shishen=day_zhi_shishen,
            day_zhi=day_zhi,
            day_cangygan=day_cangygan,
            yong_shen=yong_shen,
            yong_wuxing=yong_wuxing,
            has_chong=has_chong,
            has_xing=has_xing,
            has_he=has_he,
            has_sanhe=has_sanhe,
            day_analysis=day_analysis,
            relations=full_relations,
            ji_shen=ji_shen if isinstance(ji_shen, list) else [ji_shen] if ji_shen else [],
            xi_shen=xi_shen_list,
        )
        lucky_colors_base = LUCKY_COLORS.get(yong_shen, [])
        # 最终幸运色 = 用神底色 + 流日动态调整（合并去重，保留优先级）
        lucky_colors = _merge_lucky_colors(lucky_colors_base, lucky_result['add_colors'], lucky_result['avoid_colors'])
        lucky_dir = day_data['positions'].get('xi', '')
        lucky_foods = lucky_result['foods']

        layers = []
        if self.dayun_gz: layers.append(f"{self.dayun_gz}大运")
        if self.year_gz:  layers.append(f"{self.year_gz}流年")
        if month_gz:      layers.append(f"{month_gz}流月")
        layers.append(f"{day_gz}流日")

        return {
            'success':      True,
            'date':         target_date,
            'day_data':     day_data,
            'month_gz':     month_gz,
            'day_analysis': day_analysis,
            'lucky': {
                'colors':    lucky_colors,
                'direction': lucky_dir,
                'cai_pos':   day_data['positions'].get('cai', ''),
                'fu_pos':    day_data['positions'].get('fu', ''),
                'foods':     lucky_foods,
                'day_gan_shishen': day_gan_shishen,
                'day_zhi_shishen': day_zhi_shishen,
                'lucky_note': lucky_result['note'],
            },
            'layer_desc':   ' → '.join(layers),
            'prompt_for_llm': self._build_prompt(
                target_date, day_data, day_analysis, month_gz, lucky_colors, lucky_dir, lucky_foods
            ),
        }

    def _build_prompt(self, target_date, day_data, day_analysis, month_gz, lucky_colors, lucky_dir, lucky_foods):
        meta    = self.chart.get('meta', {})
        gz      = self.chart.get('ganzhi', {})
        fmt     = self.chart.get('yong_shen', {})
        yong    = fmt.get('yong_shen', '') or self.chart.get('analysis', {}).get('format_analysis', {}).get('yong_shen', '')
        ji      = fmt.get('ji_shen', []) or self.chart.get('analysis', {}).get('format_analysis', {}).get('ji_shen', [])
        huangli = day_data.get('huangli', {})
        pos     = day_data.get('positions', {})
        gender_cn = '男' if meta.get('gender','').lower() in ('male','m','男') else '女'
        day_gz    = day_data['ganzhi']['day']
        rating    = day_analysis.get('rating', '平')
        notes     = day_analysis.get('notes', [])
        yi_str    = '、'.join(huangli.get('yi', [])[:5])
        ji_str    = '、'.join(huangli.get('ji', [])[:4])
        # 从lucky对象拿额外信息（由 analyze 新增）
        lucky     = getattr(self, '_last_lucky', {})
        day_gan_shishen = lucky.get('day_gan_shishen', '')
        day_zhi_shishen = lucky.get('day_zhi_shishen', '')
        lucky_note      = lucky.get('lucky_note', '')

        lucky_colors_str = ''.join(lucky_colors) if lucky_colors else ''
        lucky_note_block = f'\n## 今日幸运提示说明\n  {lucky_note}' if lucky_note else ''
        notes_block = '\n'.join(f'- {n}' for n in notes) if notes else '- 今日干支与命局无明显刑冲，运势平稳'
        ji_str_joined = '、'.join(ji) if ji else ''
        month_gz_block = f' × {month_gz}流月' if month_gz else ''

        return f"""你是一位精通子平八字的命理师，请为以下用户写一份简洁有温度的日运分析。

## 用户命盘
- 四柱：年{gz.get('year','')} 月{gz.get('month','')} 日{gz.get('day','')} 时{gz.get('hour','')}（{gender_cn}命）
- 日主：{self.day_gan}  用神：{yong}  忌神：{ji_str_joined}
- 当前：{self.dayun_gz}大运 × {self.year_gz}流年{month_gz_block}

## 今日信息（{target_date}）
- 农历：{day_data.get('lunar_date','')}
- 今日干支：{day_gz}  建除：{huangli.get('zhi_xing','')}日  纳音：{huangli.get('nayin','')}
- 冲：{huangli.get('chong','')}  煞：{huangli.get('sha','')}方
- 黄历宜：{yi_str}
- 黄历忌：{ji_str}
- 喜神方位：{pos.get('xi','')}  财神方位：{pos.get('cai','')}  福神方位：{pos.get('fu','')}

## 今日干支十神分析（命盘层面）
- 今日天干 {day_gz[0]}：{day_gan_shishen}（对日主的关系）
- 今日地支 {day_gz[1]} 主藏干：{day_zhi_shishen}
{lucky_note_block}

## 命盘与今日干支的关系
今日综合评级：【{rating}】
{notes_block}

## 写作要求
请写一份300-500字的日运分析，包含：

1. **今日整体运势**：结合命盘和今日干支，说明今天的整体气场（2句话）

2. **重点提示**：今日最值得关注的一个命盘互动，用通俗语言解释对今天的影响

3. **黄历建议**：结合宜忌，给出1-2条今天适合/不适合做的事

4. **幸运提示**（基于今日干支与命局的互动综合给出，不是固定值）：
   - 幸运色：{lucky_colors_str}
   - 幸运方位：{lucky_dir}
   - 今日食物建议：{lucky_foods or ''}

语气轻松亲切，像朋友发早安消息，结尾加一句鼓励的话。
"""''