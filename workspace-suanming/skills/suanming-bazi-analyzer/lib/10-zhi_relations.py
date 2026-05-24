#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[10] lib/zhi_relations.py - 地支关系分析引擎
调用层级：被 lib/luck_cycle_analyzer.py、lib/wuyu_analyzer.py、bin/bazi 调用
依赖：lib/ganzhi_calculator.py [03]

统一处理地支之间的所有关系，按力量从强到弱：
  三会局 > 三合局 > 六合 > 半三合 > 六冲 > 三刑 > 六害 > 相破

重要规则：
  - 冲可解合：六冲可以破坏六合/三合的化合
  - 合可制冲：六合/三合可以减弱六冲的破坏力
  - 三会局力量最强，不被冲破
  - 同一地支同时存在多种关系时，按优先级取最强者描述

供 luck_cycle_analyzer、wuyu_analyzer、format_analyzer 等模块统一调用。
"""

from .ganzhi_calculator import (
    ZHI_SANHUI, ZHI_SANHE, ZHI_BAN_SANHE,
    ZHI_HE6, ZHI_HE6_ELEMENT,
    ZHI_CHONG, ZHI_XING, ZHI_HAI, ZHI_PO,
    ZHI_RELATION_WEIGHTS,
    BRANCH_ELEMENTS,
)

# ── 三刑完整组定义 ──────────────────────────────────────────────
# 三刑必须三支到齐才算完整三刑，两支只算"半刑"（力量大幅削减）
# 无恩之刑：寅巳申（三支循环互刑）
# 持势之刑：丑未戌（三支循环互刑）
# 无礼之刑：子卯（两支即成立，不需要第三支）
# 自刑：辰辰、午午、酉酉、亥亥（需要同支出现2次）
ZHI_SANXING_GROUPS = [
    (frozenset({'寅', '巳', '申'}), '无恩之刑（寅巳申）'),
    (frozenset({'丑', '未', '戌'}), '持势之刑（丑未戌）'),
]
# 无礼之刑只需两支
ZHI_WULI_XING = frozenset({'子', '卯'})
# 自刑支
ZHI_ZIXING = {'辰', '午', '酉', '亥'}


def analyze_zhi_relations(new_zhi: str, existing_zhis: frozenset, all_tiangan: list = None) -> dict:
    """
    分析一个新地支与现有地支集合之间的所有关系。

    参数：
        new_zhi:       新加入的地支（大运/流年/流月/流日）
        existing_zhis: 已有的地支集合（命局 + 已叠加的大运/流年等）
        all_tiangan:   所有层级的天干列表（用于检查透出），如 ['己','丁','癸','己','庚','丙','癸','甲']
                       不传则不做透出检查（向后兼容）

    返回：
        {
            'relations': [  # 按力量从强到弱排序
                {
                    'type':    '三会',        # 关系类型
                    'name':    '南方三会火局', # 具体名称
                    'element': '火',          # 涉及五行
                    'weight':  4.0,           # 力量权重
                    'desc':    '...',         # 描述文字
                    'is_positive': True,      # 是否为正面（合/会为正，冲/刑/害/破为负）
                    'touchu':  True,          # 天干是否透出（三合/三会才有此字段）
                }
            ],
            'net_score':   2.5,   # 综合得分（正=有利，负=不利）
            'summary':     '...',  # 一句话总结
            'dominant':    {...},  # 最强的那个关系
        }
    """
    all_zhis = existing_zhis | {new_zhi}
    relations = []

    # ── 1. 三会局（力量最强）────────────────────────────────────
    for members, element, name in ZHI_SANHUI:
        if new_zhi in members and members.issubset(all_zhis):
            # 天干透出检查：该五行的天干是否在 all_tiangan 中出现
            touchu = _check_touchu(element, all_tiangan)
            touchu_factor = 1.0 if touchu else 0.75  # 无透出力量打75折
            touchu_note = '' if touchu else '（天干未透出，力量略减）'
            relations.append({
                'type':        '三会',
                'name':        name,
                'element':     element,
                'weight':      ZHI_RELATION_WEIGHTS['三会'] * touchu_factor,
                'desc':        f'{name}：{element}五行力量极强，可改变命局格局{touchu_note}',
                'is_positive': True,
                'members':     list(members),
                'touchu':      touchu,
            })

    # ── 2. 三合局（力量次之）────────────────────────────────────
    for members, element, name in ZHI_SANHE:
        if new_zhi in members and members.issubset(all_zhis):
            # 检查是否已被三会覆盖
            already_in_sanhui = any(
                r['type'] == '三会' and set(r['members']) >= members
                for r in relations
            )
            if not already_in_sanhui:
                # 三合不被六冲破，但旺支被冲时力量削减
                # 旺支：申子辰→子，寅午戌→午，巳酉丑→酉，亥卯未→卯
                wang_zhi_map = {
                    frozenset({'申','子','辰'}): '子',
                    frozenset({'寅','午','戌'}): '午',
                    frozenset({'巳','酉','丑'}): '酉',
                    frozenset({'亥','卯','未'}): '卯',
                }
                wang_zhi = wang_zhi_map.get(members, '')
                wang_zhi_chonged = (
                    wang_zhi and
                    ZHI_CHONG.get(wang_zhi) and
                    ZHI_CHONG[wang_zhi] in all_zhis
                )
                # 天干透出检查
                touchu = _check_touchu(element, all_tiangan)
                touchu_factor = 1.0 if touchu else 0.7  # 无透出力量打70折
                chong_factor = 0.5 if wang_zhi_chonged else 1.0
                weight = ZHI_RELATION_WEIGHTS['三合'] * chong_factor * touchu_factor
                notes = []
                if wang_zhi_chonged:
                    notes.append(f'旺支{wang_zhi}被冲，力量减半')
                if not touchu:
                    notes.append('天干未透出，力量略减')
                note = f'（{"；".join(notes)}）' if notes else ''
                relations.append({
                    'type':        '三合',
                    'name':        name,
                    'element':     element,
                    'weight':      weight,
                    'desc':        f'{name}：{element}五行聚合，力量较强{note}',
                    'is_positive': True,
                    'members':     list(members),
                    'touchu':      touchu,
                })

    # ── 3. 六合（两支相合）──────────────────────────────────────
    # 理论依据（梁湘润/《子平真诠》）：
    # 地支六合极难真正化气，大多数情况下是"合而不化"——
    # 两支相互吸引，有助力，但各自五行属性保留，不改变五行格局。
    # 只有月令支持化神且无冲破时，才可能真正化气。
    he6_partner = ZHI_HE6.get(new_zhi)
    if he6_partner and he6_partner in existing_zhis:
        he6_element = ZHI_HE6_ELEMENT.get((new_zhi, he6_partner), '')
        # 冲能破六合：检查是否有六冲破坏此六合
        chong_of_new  = ZHI_CHONG.get(new_zhi)
        chong_of_he6  = ZHI_CHONG.get(he6_partner)
        broken_by_new  = chong_of_new  and chong_of_new  in existing_zhis
        broken_by_he6  = chong_of_he6  and chong_of_he6  in existing_zhis
        is_broken = broken_by_new or broken_by_he6

        if not is_broken:
            # 合而不化（常态）：有助力，但不改变五行属性
            # 注：化气需月令支持，此处保守处理，不标注化气
            desc = f'{new_zhi}与{he6_partner}六合，有助力（合而不化，各自五行属性保留）'
            if he6_element:
                desc = f'{new_zhi}与{he6_partner}六合（{he6_element}），有助力'
            relations.append({
                'type':        '六合',
                'name':        f'{new_zhi}{he6_partner}六合',
                'element':     he6_element,
                'weight':      ZHI_RELATION_WEIGHTS['六合'],
                'desc':        desc,
                'is_positive': True,
                'partner':     he6_partner,
            })
        else:
            breaker = chong_of_new if broken_by_new else chong_of_he6
            relations.append({
                'type':        '六合被冲',
                'name':        f'{new_zhi}{he6_partner}六合被{breaker}冲破',
                'element':     he6_element,
                'weight':      0,
                'desc':        f'{new_zhi}{he6_partner}六合，但{breaker}冲破此合，合力消散',
                'is_positive': False,
                'partner':     he6_partner,
            })

    # ── 4. 半三合（两支）────────────────────────────────────────
    for zhi_a, zhi_b, element, name in ZHI_BAN_SANHE:
        if new_zhi == zhi_a and zhi_b in existing_zhis:
            # 检查是否已被三合/三会覆盖
            already_covered = any(
                r['type'] in ('三会', '三合') and
                zhi_a in r.get('members', []) and zhi_b in r.get('members', [])
                for r in relations
            )
            if not already_covered:
                relations.append({
                    'type':        '半三合',
                    'name':        name,
                    'element':     element,
                    'weight':      ZHI_RELATION_WEIGHTS['半三合'],
                    'desc':        f'{name}：{element}五行有一定聚合力',
                    'is_positive': True,
                    'partner':     zhi_b,
                })
        elif new_zhi == zhi_b and zhi_a in existing_zhis:
            already_covered = any(
                r['type'] in ('三会', '三合') and
                zhi_a in r.get('members', []) and zhi_b in r.get('members', [])
                for r in relations
            )
            if not already_covered:
                relations.append({
                    'type':        '半三合',
                    'name':        name,
                    'element':     element,
                    'weight':      ZHI_RELATION_WEIGHTS['半三合'],
                    'desc':        f'{name}：{element}五行有一定聚合力',
                    'is_positive': True,
                    'partner':     zhi_a,
                })

    # ── 4.5 三合拱（三合局缺旺支/中神）──────────────────────────
    # 理论依据（《三命通会》）：
    # 三合局三字中，缺旺支（中神）时，另外两支仍有聚合该五行的趋势，
    # 称为"拱合"或"拱局"。力量弱于完整三合，但强于普通半三合。
    # 条件：被拱的旺支不能在命局中出现（填实则破拱）。
    #
    # 四组三合拱：
    #   申子辰合水 → 旺支=子 → 申辰拱子(水)
    #   寅午戌合火 → 旺支=午 → 寅戌拱午(火)
    #   巳酉丑合金 → 旺支=酉 → 巳丑拱酉(金)
    #   亥卯未合木 → 旺支=卯 → 亥未拱卯(木)
    GONG_SANHE = [
        # (支A, 支B, 被拱旺支, 五行, 名称)
        ('申', '辰', '子', '水', '申辰拱子（水局）'),
        ('寅', '戌', '午', '火', '寅戌拱午（火局）'),
        ('巳', '丑', '酉', '金', '巳丑拱酉（金局）'),
        ('亥', '未', '卯', '木', '亥未拱卯（木局）'),
    ]
    for zhi_a, zhi_b, gong_zhi, gong_element, gong_name in GONG_SANHE:
        # 条件1：新地支是其中一个，另一个在已有集合中
        # 条件2：被拱的旺支不在命局中（填实则破拱）
        if new_zhi == zhi_a and zhi_b in existing_zhis and gong_zhi not in all_zhis:
            relations.append({
                'type':        '三合拱',
                'name':        gong_name,
                'element':     gong_element,
                'weight':      ZHI_RELATION_WEIGHTS.get('拱合', 0.8),
                'desc':        f'{gong_name}：{zhi_a}{zhi_b}夹拱旺支{gong_zhi}，{gong_element}五行有暗聚趋势',
                'is_positive': True,
                'partner':     zhi_b,
            })
        elif new_zhi == zhi_b and zhi_a in existing_zhis and gong_zhi not in all_zhis:
            relations.append({
                'type':        '三合拱',
                'name':        gong_name,
                'element':     gong_element,
                'weight':      ZHI_RELATION_WEIGHTS.get('拱合', 0.8),
                'desc':        f'{gong_name}：{zhi_a}{zhi_b}夹拱旺支{gong_zhi}，{gong_element}五行有暗聚趋势',
                'is_positive': True,
                'partner':     zhi_a,
            })

    # ── 5. 六冲（动荡破坏）──────────────────────────────────────
    chong_partner = ZHI_CHONG.get(new_zhi)
    if chong_partner and chong_partner in existing_zhis:
        # 三会/三合可以抵抗六冲（六合不能制冲）
        # 检查被冲的支是否在三会/三合局中
        in_sanhui = any(
            r['type'] == '三会' and chong_partner in r.get('members', [])
            for r in relations
        )
        in_sanhe = any(
            r['type'] == '三合' and chong_partner in r.get('members', [])
            for r in relations
        )
        if in_sanhui:
            # 三会最强，冲力被完全压制
            relations.append({
                'type':        '冲被三会压制',
                'name':        f'{new_zhi}冲{chong_partner}（被三会压制）',
                'element':     BRANCH_ELEMENTS.get(chong_partner, ''),
                'weight':      0,
                'desc':        f'{new_zhi}冲{chong_partner}，但{chong_partner}在三会局中，冲力被压制',
                'is_positive': False,
                'partner':     chong_partner,
            })
        elif in_sanhe:
            # 三合削减冲力约50%
            weight = ZHI_RELATION_WEIGHTS['六冲'] * 0.5
            relations.append({
                'type':        '六冲（三合减弱）',
                'name':        f'{new_zhi}冲{chong_partner}（三合减弱）',
                'element':     BRANCH_ELEMENTS.get(chong_partner, ''),
                'weight':      weight,
                'desc':        f'{new_zhi}冲{chong_partner}，{chong_partner}在三合局中，冲力减半',
                'is_positive': False,
                'partner':     chong_partner,
            })
        else:
            relations.append({
                'type':        '六冲',
                'name':        f'{new_zhi}冲{chong_partner}',
                'element':     BRANCH_ELEMENTS.get(chong_partner, ''),
                'weight':      ZHI_RELATION_WEIGHTS['六冲'],
                'desc':        f'{new_zhi}冲{chong_partner}，动荡变化，{chong_partner}所代表的事项受冲',
                'is_positive': False,
                'partner':     chong_partner,
            })

    # ── 6. 三刑（摩擦压力）──────────────────────────────────────
    # 规则：
    #   - 无恩之刑（寅巳申）/ 持势之刑（丑未戌）：三支到齐=完整三刑，两支=半刑（力量打3折）
    #   - 无礼之刑（子卯）：两支即成立
    #   - 自刑（辰辰/午午/酉酉/亥亥）：需要同支出现2次

    # 检查完整三刑组
    for group_members, group_name in ZHI_SANXING_GROUPS:
        if new_zhi in group_members:
            # 该组中除 new_zhi 外的其他成员
            others_in_group = group_members - {new_zhi}
            others_present = others_in_group & existing_zhis
            if len(others_present) == 2:
                # 三支到齐 → 完整三刑
                relations.append({
                    'type':        '三刑',
                    'name':        group_name,
                    'element':     BRANCH_ELEMENTS.get(new_zhi, ''),
                    'weight':      ZHI_RELATION_WEIGHTS['三刑'],
                    'desc':        f'{group_name}：三支到齐，刑力极强，易生是非或健康问题',
                    'is_positive': False,
                    'members':     list(group_members),
                })
            elif len(others_present) == 1:
                # 只有两支 → 半刑（力量打3折）
                partner = list(others_present)[0]
                half_weight = ZHI_RELATION_WEIGHTS['三刑'] * 0.3
                relations.append({
                    'type':        '半刑',
                    'name':        f'{new_zhi}与{partner}半刑（缺第三支）',
                    'element':     BRANCH_ELEMENTS.get(new_zhi, ''),
                    'weight':      half_weight,
                    'desc':        f'{new_zhi}与{partner}有刑的趋势，但第三支未到，力量很弱',
                    'is_positive': False,
                    'partner':     partner,
                })

    # 无礼之刑（子卯）：两支即成立
    if new_zhi in ZHI_WULI_XING:
        wuli_partner = '卯' if new_zhi == '子' else '子'
        if wuli_partner in existing_zhis:
            relations.append({
                'type':        '三刑',
                'name':        f'无礼之刑（{new_zhi}{wuli_partner}）',
                'element':     BRANCH_ELEMENTS.get(wuli_partner, ''),
                'weight':      ZHI_RELATION_WEIGHTS['三刑'],
                'desc':        f'{new_zhi}与{wuli_partner}无礼之刑，两支即成立，主口舌是非',
                'is_positive': False,
                'partner':     wuli_partner,
            })

    # 自刑：需要同支出现2次（existing_zhis 中已有该支）
    if new_zhi in ZHI_ZIXING and new_zhi in existing_zhis:
        relations.append({
            'type':        '自刑',
            'name':        f'{new_zhi}自刑',
            'element':     BRANCH_ELEMENTS.get(new_zhi, ''),
            'weight':      ZHI_RELATION_WEIGHTS['三刑'] * 0.7,
            'desc':        f'{new_zhi}自刑（同支重现），内耗较重，易有自我矛盾或反复',
            'is_positive': False,
            'partner':     new_zhi,
        })

    # ── 7. 六害（力量较弱）──────────────────────────────────────
    hai_partner = ZHI_HAI.get(new_zhi)
    if hai_partner and hai_partner in existing_zhis:
        relations.append({
            'type':        '六害',
            'name':        f'{new_zhi}害{hai_partner}',
            'element':     BRANCH_ELEMENTS.get(hai_partner, ''),
            'weight':      ZHI_RELATION_WEIGHTS['六害'],
            'desc':        f'{new_zhi}与{hai_partner}相害，暗中损耗，需防小人或暗伤',
            'is_positive': False,
            'partner':     hai_partner,
        })

    # ── 8. 相破（力量最弱）──────────────────────────────────────
    po_partner = ZHI_PO.get(new_zhi)
    if po_partner and po_partner in existing_zhis:
        relations.append({
            'type':        '相破',
            'name':        f'{new_zhi}破{po_partner}',
            'element':     BRANCH_ELEMENTS.get(po_partner, ''),
            'weight':      ZHI_RELATION_WEIGHTS['相破'],
            'desc':        f'{new_zhi}与{po_partner}相破，小有损耗，影响较轻',
            'is_positive': False,
            'partner':     po_partner,
        })

    # ── 计算综合得分 ─────────────────────────────────────────────
    net_score = sum(r['weight'] for r in relations)

    # ── 按力量绝对值排序（最强的排前面）────────────────────────
    relations.sort(key=lambda r: abs(r['weight']), reverse=True)

    # ── 生成总结 ─────────────────────────────────────────────────
    dominant = relations[0] if relations else None
    summary = _build_summary(new_zhi, relations, net_score)

    return {
        'relations':  relations,
        'net_score':  round(net_score, 2),
        'summary':    summary,
        'dominant':   dominant,
        'has_sanhui': any(r['type'] == '三会' for r in relations),
        'has_sanhe':  any(r['type'] == '三合' for r in relations),
        'has_chong':  any(r['type'] == '六冲' for r in relations),
        'has_he':     any(r['type'] in ('六合', '半三合') for r in relations),
        'has_xing':   any(r['type'] in ('三刑', '自刑') for r in relations),
        'has_hai':    any(r['type'] == '六害' for r in relations),
    }


def analyze_all_zhi_relations(pillars_zhis: list) -> list:
    """
    分析命局内部所有地支之间的关系（用于原局分析）。

    参数：
        pillars_zhis: 四柱地支列表，如 ['巳', '丑', '酉', '未']

    返回：关系列表
    """
    results = []
    zhi_set = frozenset(pillars_zhis)

    # 检测三会局
    for members, element, name in ZHI_SANHUI:
        if members.issubset(zhi_set):
            results.append({
                'type': '三会', 'name': name, 'element': element,
                'weight': ZHI_RELATION_WEIGHTS['三会'],
                'desc': f'命局{name}，{element}五行力量极强',
                'is_positive': True,
                'members': list(members),
            })

    # 检测三合局（未被三会覆盖的）
    for members, element, name in ZHI_SANHE:
        if members.issubset(zhi_set):
            covered = any(
                r['type'] == '三会' and set(r['members']) >= members
                for r in results
            )
            if not covered:
                results.append({
                    'type': '三合', 'name': name, 'element': element,
                    'weight': ZHI_RELATION_WEIGHTS['三合'],
                    'desc': f'命局{name}，{element}五行聚合',
                    'is_positive': True,
                    'members': list(members),
                })

    # 检测六合
    checked_he6 = set()
    for zhi in pillars_zhis:
        partner = ZHI_HE6.get(zhi)
        if partner and partner in zhi_set and (zhi, partner) not in checked_he6:
            checked_he6.add((zhi, partner))
            checked_he6.add((partner, zhi))
            element = ZHI_HE6_ELEMENT.get((zhi, partner), '')
            results.append({
                'type': '六合', 'name': f'{zhi}{partner}六合',
                'element': element, 'weight': ZHI_RELATION_WEIGHTS['六合'],
                'desc': f'命局{zhi}与{partner}六合（{element}），有助力，合而不化',
                'is_positive': True,
            })

    # 检测六冲
    checked_chong = set()
    for zhi in pillars_zhis:
        partner = ZHI_CHONG.get(zhi)
        if partner and partner in zhi_set and (zhi, partner) not in checked_chong:
            checked_chong.add((zhi, partner))
            checked_chong.add((partner, zhi))
            results.append({
                'type': '六冲', 'name': f'{zhi}冲{partner}',
                'element': BRANCH_ELEMENTS.get(partner, ''),
                'weight': ZHI_RELATION_WEIGHTS['六冲'],
                'desc': f'命局{zhi}冲{partner}，动荡变化',
                'is_positive': False,
            })

    # 检测三刑（完整三刑组）
    for group_members, group_name in ZHI_SANXING_GROUPS:
        present = group_members & zhi_set
        if len(present) == 3:
            # 三支到齐 → 完整三刑
            results.append({
                'type': '三刑', 'name': group_name,
                'element': '',
                'weight': ZHI_RELATION_WEIGHTS['三刑'],
                'desc': f'命局{group_name}，三支到齐，刑力极强',
                'is_positive': False,
                'members': list(group_members),
            })
        elif len(present) == 2:
            # 两支 → 半刑
            pair = list(present)
            half_weight = ZHI_RELATION_WEIGHTS['三刑'] * 0.3
            results.append({
                'type': '半刑', 'name': f'{pair[0]}与{pair[1]}半刑（缺第三支）',
                'element': '',
                'weight': half_weight,
                'desc': f'命局{pair[0]}与{pair[1]}有刑的趋势，但第三支未到，力量很弱',
                'is_positive': False,
            })

    # 无礼之刑（子卯）
    if '子' in zhi_set and '卯' in zhi_set:
        results.append({
            'type': '三刑', 'name': '无礼之刑（子卯）',
            'element': BRANCH_ELEMENTS.get('卯', ''),
            'weight': ZHI_RELATION_WEIGHTS['三刑'],
            'desc': '命局子与卯无礼之刑，主口舌是非',
            'is_positive': False,
        })

    # 自刑（需要同支出现2次）
    from collections import Counter
    zhi_counts = Counter(pillars_zhis)
    for zhi, count in zhi_counts.items():
        if zhi in ZHI_ZIXING and count >= 2:
            results.append({
                'type': '自刑', 'name': f'{zhi}自刑',
                'element': BRANCH_ELEMENTS.get(zhi, ''),
                'weight': ZHI_RELATION_WEIGHTS['三刑'] * 0.7,
                'desc': f'命局{zhi}自刑（同支出现{count}次），内耗较重',
                'is_positive': False,
            })

    # 检测六害
    checked_hai = set()
    for zhi in pillars_zhis:
        partner = ZHI_HAI.get(zhi)
        if partner and partner in zhi_set and (zhi, partner) not in checked_hai:
            checked_hai.add((zhi, partner))
            checked_hai.add((partner, zhi))
            results.append({
                'type': '六害', 'name': f'{zhi}害{partner}',
                'element': BRANCH_ELEMENTS.get(partner, ''),
                'weight': ZHI_RELATION_WEIGHTS['六害'],
                'desc': f'命局{zhi}与{partner}相害，暗中损耗',
                'is_positive': False,
            })

    results.sort(key=lambda r: abs(r['weight']), reverse=True)
    return results


def _build_summary(new_zhi: str, relations: list, net_score: float) -> str:
    """生成地支关系一句话总结"""
    if not relations:
        return f'{new_zhi}与命局无明显刑冲合，运势平稳'

    dominant = relations[0]
    rel_type = dominant['type']
    rel_name = dominant['name']

    if net_score >= 3:
        tone = '运势大旺'
    elif net_score >= 1:
        tone = '运势有助'
    elif net_score >= -1:
        tone = '吉凶参半'
    elif net_score >= -2:
        tone = '运势受阻'
    else:
        tone = '运势大损'

    rel_count = len(relations)
    if rel_count == 1:
        return f'{new_zhi}与命局：{rel_name}，{tone}'
    else:
        other_names = '、'.join(r['name'] for r in relations[1:3])
        return f'{new_zhi}与命局：主要为{rel_name}，另有{other_names}，综合{tone}'


def analyze_zhi_relations_layered(
    yuanju_zhis: list,
    dayun_zhi: str = None,
    liunian_zhi: str = None,
    liuyue_zhi: str = None,
    liuri_zhi: str = None,
    all_tiangan: list = None,
) -> dict:
    """
    分层分析地支关系：每层只输出该层新增的关系。

    参数：
        yuanju_zhis:  原局四柱地支列表，如 ['巳','丑','酉','未']
        dayun_zhi:    大运地支（可选）
        liunian_zhi:  流年地支（可选）
        liuyue_zhi:   流月地支（可选）
        liuri_zhi:    流日地支（可选）
        all_tiangan:  所有层级天干列表（用于透出检查）

    返回：
        {
            'yuanju': [...],                              # 原局内部关系
            'yuanju_dayun': [...],                        # +大运后的新增关系
            'yuanju_dayun_liunian': [...],                # +流年后的新增关系
            'yuanju_dayun_liunian_liuyue': [...],         # +流月后的新增关系
            'yuanju_dayun_liunian_liuyue_liuri': [...],   # +流日后的新增关系
            'all_relations': [...],                       # 所有层级合并
            'layer_summaries': {                          # 每层一句话总结
                'yuanju': '...',
                'yuanju_dayun': '...',
                ...
            },
            'net_scores': {                              # 每层净分
                'yuanju': 0.0,
                'yuanju_dayun': 1.5,
                ...
            },
        }

    适用场景：
        - 八字精批第一步：只看 yuanju
        - 八字精批当前运：yuanju + yuanju_dayun + yuanju_dayun_liunian
        - 月运分析：上面 + yuanju_dayun_liunian_liuyue
        - 日运推送：上面 + yuanju_dayun_liunian_liuyue_liuri
    """
    result = {
        'yuanju': [],
        'yuanju_dayun': [],
        'yuanju_dayun_liunian': [],
        'yuanju_dayun_liunian_liuyue': [],
        'yuanju_dayun_liunian_liuyue_liuri': [],
        'all_relations': [],
        'layer_summaries': {},
        'net_scores': {},
    }

    # ── 第1层：原局内部关系 ──────────────────────────────────────
    yuanju_relations = analyze_all_zhi_relations(yuanju_zhis)
    result['yuanju'] = yuanju_relations
    result['net_scores']['yuanju'] = round(
        sum(r['weight'] for r in yuanju_relations), 2
    )
    result['layer_summaries']['yuanju'] = _build_layer_summary('原局', yuanju_relations)

    # 用于追踪已发现的关系（去重用）
    seen_relation_keys = set()
    for r in yuanju_relations:
        seen_relation_keys.add(_relation_key(r))

    # 当前累积的地支集合
    current_zhis = set(yuanju_zhis)

    # ── 逐层叠加 ────────────────────────────────────────────────
    layers = [
        ('yuanju_dayun',                        dayun_zhi,   '大运'),
        ('yuanju_dayun_liunian',                liunian_zhi, '流年'),
        ('yuanju_dayun_liunian_liuyue',         liuyue_zhi,  '流月'),
        ('yuanju_dayun_liunian_liuyue_liuri',   liuri_zhi,   '流日'),
    ]

    for layer_key, new_zhi, layer_name in layers:
        if not new_zhi:
            # 该层无地支，跳过但保留空列表
            result['net_scores'][layer_key] = 0.0
            result['layer_summaries'][layer_key] = f'{layer_name}：无'
            continue

        # 用现有的 analyze_zhi_relations 分析新地支与已有集合的关系
        existing_frozenset = frozenset(current_zhis)
        layer_result = analyze_zhi_relations(
            new_zhi, existing_frozenset, all_tiangan=all_tiangan
        )

        # 过滤出本层新增的关系（排除已在上层出现的）
        new_relations = []
        for r in layer_result.get('relations', []):
            rkey = _relation_key(r)
            if rkey not in seen_relation_keys:
                # 标注来源层
                r['source_layer'] = layer_name
                new_relations.append(r)
                seen_relation_keys.add(rkey)

        # 同时检查：新地支加入后，是否让已有地支之间形成了新的三方关系
        # （例如：原局有巳、丑，大运来酉 → 巳酉丑三合金局）
        # 这在 analyze_zhi_relations 中已经处理了（它检查 all_zhis = existing | {new_zhi}）
        # 但还需要检查新地支是否让已有的两个地支形成了新的三会/三合
        # → analyze_zhi_relations 的逻辑已覆盖：它检查 new_zhi in members and members.issubset(all_zhis)

        result[layer_key] = new_relations
        result['net_scores'][layer_key] = round(
            sum(r['weight'] for r in new_relations), 2
        )
        result['layer_summaries'][layer_key] = _build_layer_summary(
            f'{layer_name}({new_zhi})', new_relations
        )

        # 将新地支加入累积集合
        current_zhis.add(new_zhi)

    # ── 合并所有层级关系 ─────────────────────────────────────────
    all_rels = list(result['yuanju'])
    for layer_key, _, _ in layers:
        all_rels.extend(result[layer_key])
    all_rels.sort(key=lambda r: abs(r['weight']), reverse=True)
    result['all_relations'] = all_rels

    return result


def _relation_key(r: dict) -> str:
    """
    生成关系的唯一标识 key，用于跨层去重。
    基于关系类型 + 涉及的地支（排序后）来去重。
    """
    rtype = r.get('type', '')
    # 获取涉及的所有地支
    members = r.get('members', [])
    partner = r.get('partner', '')
    if members:
        zhis = tuple(sorted(members))
    elif partner:
        # 对于六合/六冲等双支关系，需要从 name 中提取或用 partner
        # name 格式如 "巳丑六合" 或 "巳冲亥"
        zhis = tuple(sorted([partner, r.get('name', '')[0] if r.get('name') else '']))
    else:
        zhis = (r.get('name', ''),)
    return f"{rtype}|{''.join(zhis)}"


def _build_layer_summary(layer_name: str, relations: list) -> str:
    """生成某一层的关系总结"""
    if not relations:
        return f'{layer_name}：无新增刑冲合关系'

    positive = [r for r in relations if r.get('is_positive')]
    negative = [r for r in relations if not r.get('is_positive')]

    parts = []
    if positive:
        names = '、'.join(r['name'] for r in positive[:3])
        parts.append(f'合会：{names}')
    if negative:
        names = '、'.join(r['name'] for r in negative[:3])
        parts.append(f'冲刑：{names}')

    net = sum(r['weight'] for r in relations)
    if net >= 2:
        tone = '整体有利'
    elif net >= 0:
        tone = '吉凶参半'
    elif net >= -2:
        tone = '略有不利'
    else:
        tone = '冲击较大'

    return f'{layer_name}：{"；".join(parts)}（{tone}）'


def score_relation_for_element(relations: list, target_element: str) -> float:
    """
    计算地支关系对特定五行的净影响分数。
    用于判断某个五行（用神/忌神）在这些关系中是被加强还是被削弱。

    参数：
        relations:      analyze_zhi_relations 返回的关系列表
        target_element: 目标五行（如用神'火'）

    返回：正数=有利，负数=不利
    """
    score = 0.0
    for r in relations:
        element = r.get('element', '')
        weight  = r['weight']
        if element == target_element:
            # 合/会强化该五行 → 正分；冲/刑/害弱化 → 负分
            score += weight  # weight 本身已经有正负
    return score


# ─────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────

# 五行对应的天干
_ELEMENT_TO_STEMS = {
    '木': {'甲', '乙'},
    '火': {'丙', '丁'},
    '土': {'戊', '己'},
    '金': {'庚', '辛'},
    '水': {'壬', '癸'},
}


def _check_touchu(element: str, all_tiangan: list = None) -> bool:
    """
    检查某五行是否在天干中透出。

    参数：
        element:      五行（如 '金'）
        all_tiangan:  所有层级的天干列表（年干、月干、日干、时干、大运干、流年干、流月干、流日干）

    返回：
        True = 有透出（天干中有该五行的干），False = 无透出

    理论依据（梁湘润《子平真诠》）：
        地支合局要真正发挥力量，需要天干有该五行的干透出。
        无透出的合局力量打折（约70-75%），但不是完全无效。
    """
    if all_tiangan is None:
        return True  # 不传天干信息时，保守处理，默认有透出（向后兼容）

    target_stems = _ELEMENT_TO_STEMS.get(element, set())
    return bool(target_stems & set(all_tiangan))
