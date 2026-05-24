#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[20] lib/wuyu_analyzer.py - 妻财子禄寿五运分析引擎
调用层级：被 bin/bazi 调用
依赖：lib/ten_gods_analyzer.py [11]、lib/zhi_relations.py [10]

五运维度：
  妻（感情/婚姻）  财（财运/事业）  子（子女/后代）
  禄（官禄/地位）  寿（健康/寿元）

层级结构（强制，不可跳级）：
  原局（命局底色）
    └── 大运（10年背景）
          └── 流年（年度叠加）
                └── 流月（月度叠加）
                      └── 流日（日度叠加）

每一层分析都必须包含上层的影响，输出时明确标注各层贡献。
"""

import os
import sys
from typing import Dict, List

_LIB_DIR   = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_LIB_DIR)
sys.path.insert(0, os.path.join(_SKILL_DIR, "vendor"))

# ─────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────

GAN_WUXING = {
    "甲":"木","乙":"木","丙":"火","丁":"火","戊":"土",
    "己":"土","庚":"金","辛":"金","壬":"水","癸":"水",
}
ZHI_WUXING = {
    "子":"水","丑":"土","寅":"木","卯":"木","辰":"土","巳":"火",
    "午":"火","未":"土","申":"金","酉":"金","戌":"土","亥":"水",
}
ZHI_CANGYGAN = {
    "子":["癸"],"丑":["己","癸","辛"],"寅":["甲","丙","戊"],
    "卯":["乙"],"辰":["戊","乙","癸"],"巳":["丙","戊","庚"],
    "午":["丁","己"],"未":["己","丁","乙"],"申":["庚","壬","戊"],
    "酉":["辛"],"戌":["戊","辛","丁"],"亥":["壬","甲"],
}
SHISHEN_FULL = {
    "比":"比肩","劫":"劫财","食":"食神","伤":"伤官",
    "才":"偏财","财":"正财","杀":"七杀","官":"正官",
    "枭":"偏印","印":"正印","日主":"日主",
}
CHONG = {
    "子":"午","午":"子","丑":"未","未":"丑",
    "寅":"申","申":"寅","卯":"酉","酉":"卯",
    "辰":"戌","戌":"辰","巳":"亥","亥":"巳",
}
HE6 = {
    "子":"丑","丑":"子","寅":"亥","亥":"寅",
    "卯":"戌","戌":"卯","辰":"酉","酉":"辰",
    "巳":"申","申":"巳","午":"未","未":"午",
}
SANHE = [
    ({"申","子","辰"}, "水局"),
    ({"寅","午","戌"}, "火局"),
    ({"巳","酉","丑"}, "金局"),
    ({"亥","卯","未"}, "木局"),
]
SANHUI = [
    ({"寅","卯","辰"}, "木局", "东方三会"),
    ({"巳","午","未"}, "火局", "南方三会"),
    ({"申","酉","戌"}, "金局", "西方三会"),
    ({"亥","子","丑"}, "水局", "北方三会"),
]
XING = {
    "子":"卯","卯":"子",
    "寅":"巳","巳":"申","申":"寅",
    "丑":"戌","戌":"未","未":"丑",
}

WUYU_DIMS = {
    "qi":   {"name_male": "妻", "name_female": "夫", "label_male": "妻（感情/婚姻）", "label_female": "夫（感情/婚姻）"},
    "cai":  {"name_male": "财", "name_female": "财", "label_male": "财（财运/事业）", "label_female": "财（财运/事业）"},
    "zi":   {"name_male": "子", "name_female": "子", "label_male": "子（子女/后代）", "label_female": "子（子女/后代）"},
    "lu":   {"name_male": "禄", "name_female": "禄", "label_male": "禄（官禄/地位）", "label_female": "禄（官禄/地位）"},
    "shou": {"name_male": "寿", "name_female": "寿", "label_male": "寿（健康/寿元）", "label_female": "寿（健康/寿元）"},
}

def _dim_name(dim: str, gender: str) -> str:
    """根据性别返回维度名称（妻/夫）。"""
    key = "name_female" if gender == "female" else "name_male"
    return WUYU_DIMS[dim].get(key, WUYU_DIMS[dim].get("name_male", dim))

def _dim_label(dim: str, gender: str) -> str:
    """根据性别返回维度标签。"""
    key = "label_female" if gender == "female" else "label_male"
    return WUYU_DIMS[dim].get(key, WUYU_DIMS[dim].get("label_male", dim))

# 男命：妻=正财/偏财，财=财星+食伤，子=食伤，禄=官杀，寿=印比
# 女命：妻=官杀（夫星），财=财星+食伤，子=食伤，禄=官杀，寿=印比
WUYU_SHISHEN_MAP = {
    "male": {
        "qi":   ["财","才"],
        "cai":  ["财","才","食","伤"],
        "zi":   ["食","伤"],
        "lu":   ["官","杀"],
        "shou": ["印","枭","比","劫"],
    },
    "female": {
        "qi":   ["官","杀"],
        "cai":  ["财","才","食","伤"],
        "zi":   ["食","伤"],
        "lu":   ["官","杀"],
        "shou": ["印","枭","比","劫"],
    },
}

LAYER_WEIGHTS = {"原局": 3.0, "大运": 2.0, "流年": 1.5, "流月": 1.0, "流日": 0.5}

# 不同场景下的权重分配
# 原则：
#   - 原局永远是底色（权重最高），但随着层级增加，焦点层的权重相对提升
#   - 太岁（流年）在所有场景中都有较高权重（太岁为尊）
#   - 应期层（流月/流日）在对应场景中权重提升
SCENE_WEIGHTS = {
    "full": {
        # 原局精批：原局为主，大运+流年为辅
        "原局": 3.0, "大运": 2.0, "流年": 1.5, "流月": 0.8, "流日": 0.3,
    },
    "yearly": {
        # 年运分析：流年为焦点（太岁为尊），原局和大运为背景
        "原局": 2.0, "大运": 2.0, "流年": 3.0, "流月": 0.8, "流日": 0.3,
    },
    "monthly": {
        # 月运分析：流月为应期焦点，流年仍为太岁
        "原局": 1.5, "大运": 1.5, "流年": 2.5, "流月": 3.0, "流日": 0.3,
    },
    "daily": {
        # 日运分析：太岁（流年）为尊，流月为应期，流日为触发引动
        "原局": 1.0, "大运": 1.5, "流年": 2.5, "流月": 2.0, "流日": 2.0,
    },
}


# ─────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────

def _gz_split(gz):
    if gz and len(gz) >= 2:
        return gz[0], gz[1]
    return None, None


# 十神全称→简称映射
_SHISHEN_FULL_TO_SHORT = {v: k for k, v in SHISHEN_FULL.items()}
# 补充：如果传入的已经是简称，直接返回
_SHISHEN_FULL_TO_SHORT.update({k: k for k in SHISHEN_FULL.keys()})


def _full_to_short(shishen: str) -> str:
    """将十神全称转为简称：'正官'→'官'，'七杀'→'杀'，已是简称则不变"""
    return _SHISHEN_FULL_TO_SHORT.get(shishen, shishen)


def _get_interactions(zhi_a, zhi_set):
    """
    获取地支关系描述列表，调用统一的 zhi_relations 引擎。
    力量排序：三会 > 三合 > 六合 > 半三合 > 六冲 > 三刑 > 六害 > 相破
    """
    from .zhi_relations import analyze_zhi_relations
    result = analyze_zhi_relations(zhi_a, frozenset(zhi_set) - {zhi_a})
    # 返回描述列表（供原有逻辑使用）
    return [r['desc'] for r in result['relations']]


def _score_shishen(shishen, dim, gender):
    """
    评估某十神对某维度的影响分数。

    正官 vs 七杀的区别（禄维度）：
    - 正官：稳定的权力和地位，无条件正面 → +2
    - 七杀：压力和竞争，有制则为权（+1），无制则为祸（0或-1）
      七杀是否有制需要在通关逻辑（_check_tongguan）中判断，
      这里给七杀基础分 +1（中性偏正面，因为杀本身代表"有事业心"）

    食神 vs 伤官的区别（子维度）：
    - 食神：温和的才华表达，无条件正面 → +2
    - 伤官：锋利的才华但易惹祸，基础 +1（有印制则好，无印制则伤官见官）
    """
    relevant = WUYU_SHISHEN_MAP.get(gender, WUYU_SHISHEN_MAP["male"]).get(dim, [])

    if shishen in relevant:
        # 特殊处理：七杀和伤官不给满分
        if shishen == '杀' and dim == 'lu':
            return 1  # 七杀基础+1（有制才升为+2，在通关逻辑中处理）
        elif shishen == '伤' and dim == 'zi':
            return 1  # 伤官基础+1（锋利但易惹祸）
        elif shishen == '杀' and dim == 'qi' and gender == 'female':
            return 1  # 女命七杀为偏夫/情人，不如正官稳定
        return 2

    BAD_FOR = {
        "qi":   ["劫","比"],
        "cai":  ["劫","杀"],
        "zi":   ["杀","官"],
        "lu":   ["伤"],  # 伤官见官为祸（食神不算，食神制杀反而好）
        "shou": ["财","才"],
    }
    if shishen in BAD_FOR.get(dim, []):
        return -1
    return 0


# ─────────────────────────────────────────────────────────────────
# 单层分析
# ─────────────────────────────────────────────────────────────────

def _analyze_one_layer(gz, day_gan, gender, layer_name, yuanju_zhis):
    gan, zhi = _gz_split(gz)
    if not gan:
        return {}

    from .ten_gods_analyzer import get_ten_god
    shishen_gan_full = get_ten_god(day_gan, gan)
    cangygan     = ZHI_CANGYGAN.get(zhi, [])
    shishen_zhi_full = get_ten_god(day_gan, cangygan[0]) if cangygan else ""

    # 全称→简称映射（get_ten_god返回'正官'，但评分系统用'官'）
    shishen_gan = _full_to_short(shishen_gan_full)
    shishen_zhi = _full_to_short(shishen_zhi_full)

    # 获取完整的地支关系（带结构化数据）
    from .zhi_relations import analyze_zhi_relations
    rel_result = analyze_zhi_relations(zhi, frozenset(yuanju_zhis) - {zhi})
    relations = rel_result.get('relations', [])

    # 旧接口兼容（纯文字描述列表）
    interactions = [r['desc'] for r in relations]

    wuyu = {}
    for dim in WUYU_DIMS:
        score    = _score_shishen(shishen_gan, dim, gender)
        score   += _score_shishen(shishen_zhi, dim, gender) // 2
        notes    = []
        relevant = WUYU_SHISHEN_MAP.get(gender, WUYU_SHISHEN_MAP["male"]).get(dim, [])
        full_gan = SHISHEN_FULL.get(shishen_gan, shishen_gan)
        full_zhi = SHISHEN_FULL.get(shishen_zhi, shishen_zhi)
        dim_n    = _dim_name(dim, gender)  # 妻/夫/财/子/禄/寿

        if shishen_gan in relevant:
            notes.append(f"天干{gan}（{full_gan}）为{dim_n}星，{layer_name}有力")
        elif _score_shishen(shishen_gan, dim, gender) < 0:
            notes.append(f"天干{gan}（{full_gan}）克制{dim_n}星，{dim_n}受压")
        if shishen_zhi in relevant:
            notes.append(f"地支{zhi}藏{cangygan[0] if cangygan else ''}（{full_zhi}）为{dim_n}星，有根")
        elif _score_shishen(shishen_zhi, dim, gender) < 0:
            notes.append(f"地支{zhi}藏{cangygan[0] if cangygan else ''}（{full_zhi}）克制{dim_n}星")

        # ── 关键改动：只选取与该维度相关的地支关系 ──────────────
        # 每个维度关注的五行/宫位不同：
        #   夫/妻宫 = 日支的关系（日支代表配偶宫）
        #   财宫 = 财星五行相关的关系
        #   子宫 = 食伤五行相关的关系
        #   禄宫 = 官杀五行相关的关系
        #   寿宫 = 印比五行相关的关系
        dim_relations = _filter_relations_for_dim(
            dim, relations, day_gan, gender, yuanju_zhis
        )

        # ── 地支关系对分数的贡献 ──────────────────────────────────
        # 三会/三合/六合等正面关系：如果五行与维度相关 → 加分
        # 六冲/三刑/六害等负面关系：如果五行与维度相关 → 减分
        # 间接影响（泄/克/生）也计入，但力度减半
        for rel in dim_relations:
            rweight = rel.get('weight', 0)
            indirect = rel.get('_indirect', '')

            if indirect:
                # 间接影响：力度打折
                if indirect == 'benefit':
                    score += 0.5  # 间接得益
                elif indirect == 'drain':
                    score -= 0.5  # 被泄
                elif indirect == 'harm':
                    score -= 0.8  # 被克
            else:
                # 直接影响：根据关系权重换算
                # 正面关系（三会4.0, 三合3.0, 六合2.0, 半合1.5）→ 加分
                # 负面关系（六冲-2.5, 三刑-1.5, 六害-1.0）→ 减分
                if rweight > 0:
                    score += min(2, rweight * 0.5)  # 正面关系加分，上限+2
                elif rweight < 0:
                    score += max(-2, rweight * 0.4)  # 负面关系减分，下限-2

        for rel in dim_relations:
            rtype = rel['type']
            rname = rel.get('name', '')
            element = rel.get('element', '')
            is_positive = rel.get('is_positive', True)
            indirect = rel.get('_indirect', '')
            indirect_note = rel.get('_indirect_note', '')

            # 间接影响的描述需要特殊处理
            if indirect:
                if indirect == 'benefit':
                    notes.append(f"{rname}（{indirect_note}），{dim_n}星间接得益")
                elif indirect == 'drain':
                    notes.append(f"{rname}（{indirect_note}），{dim_n}星被泄耗")
                elif indirect == 'harm':
                    notes.append(f"{rname}（{indirect_note}），{dim_n}星受克损")
            elif is_positive:
                if '三会' in rtype:
                    notes.append(f"{rname}，{dim_n}星五行大旺")
                elif '三合' in rtype:
                    notes.append(f"{rname}，{dim_n}星五行聚合，有助力")
                elif '六合' in rtype and '被冲' not in rtype:
                    notes.append(f"{rname}，{dim_n}宫得合，有稳定助力")
                elif '半' in rtype:
                    notes.append(f"{rname}，{dim_n}宫有聚合之力")
                else:
                    notes.append(f"{rname}，对{dim_n}有利")
            else:
                if '冲' in rtype:
                    notes.append(f"{rname}，{dim_n}宫受冲，需防波动")
                elif '刑' in rtype:
                    notes.append(f"{rname}，易生是非口舌或健康问题")
                elif '害' in rtype:
                    notes.append(f"{rname}，{dim_n}宫暗损，需防小人")
                elif '破' in rtype:
                    notes.append(f"{rname}，{dim_n}宫小有损耗")
                elif '被冲破' in rname:
                    notes.append(f"{rname}，{dim_n}宫合力消散")
                else:
                    notes.append(f"{rname}，对{dim_n}不利")

        wuyu[dim] = {
            "score":       max(-3, min(3, score)),
            "notes":       notes,
            "shishen_gan": shishen_gan,
            "shishen_zhi": shishen_zhi,
        }

    return {
        "gz":           gz,
        "layer":        layer_name,
        "gan_wuxing":   GAN_WUXING.get(gan, ""),
        "zhi_wuxing":   ZHI_WUXING.get(zhi, ""),
        "shishen_gan":  shishen_gan,
        "shishen_zhi":  shishen_zhi,
        "interactions": interactions,
        "wuyu":         wuyu,
    }


def _filter_relations_for_dim(dim: str, relations: list, day_gan: str,
                              gender: str, yuanju_zhis: set) -> list:
    """
    根据维度筛选相关的地支关系。

    原则：
    - 夫/妻宫（qi）：关注日支（配偶宫）相关的关系
    - 财宫（cai）：关注财星五行相关的关系
    - 子宫（zi）：关注食伤五行相关的关系
    - 禄宫（lu）：关注官杀五行相关的关系
    - 寿宫（shou）：关注印比五行相关的关系

    如果某个关系涉及的五行与该维度的代表五行一致，或者涉及的地支是该维度的宫位，
    则该关系与此维度相关。

    对于三会/三合等大格局关系，如果其五行恰好是该维度的代表五行，影响更大。
    """
    from .ten_gods_analyzer import get_ten_god

    # 确定该维度关注的五行
    # 日主五行
    day_element = GAN_WUXING.get(day_gan, '')

    # 五行生克关系映射（基于日主）
    # 相生：木→火→土→金→水→木
    # 相克：木→土→水→火→金→木
    SHENG_WO = {'木': '水', '火': '木', '土': '火', '金': '土', '水': '金'}  # 生我者（印）
    WO_SHENG = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}  # 我生者（食伤）
    KE_WO = {'木': '金', '火': '水', '土': '木', '金': '火', '水': '土'}     # 克我者（官杀）
    WO_KE = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}     # 我克者（财）

    if not day_element:
        return relations[:2]

    yin_element = SHENG_WO.get(day_element, '')    # 印星五行
    shi_element = WO_SHENG.get(day_element, '')    # 食伤五行
    guan_element = KE_WO.get(day_element, '')      # 官杀五行
    cai_element = WO_KE.get(day_element, '')       # 财星五行
    bi_element = day_element                       # 比劫五行

    # 维度 → 关注的五行
    dim_elements = {
        'qi':   [cai_element] if gender == 'male' else [guan_element],  # 男财女官
        'cai':  [cai_element, shi_element],  # 财星 + 食伤生财
        'zi':   [shi_element],               # 食伤
        'lu':   [guan_element],              # 官杀
        'shou': [yin_element, bi_element],   # 印星 + 比劫
    }

    target_elements = dim_elements.get(dim, [])

    # 筛选：关系涉及的五行与维度相关，或者是大格局（三会/三合/六冲）
    filtered = []
    for rel in relations:
        rel_element = rel.get('element', '')
        rtype = rel.get('type', '')
        weight = abs(rel.get('weight', 0))

        # 条件1：关系涉及的五行与该维度相关
        if rel_element and rel_element in target_elements:
            filtered.append(rel)
            continue

        # 条件2：大格局关系（三会/三合）且力量很强
        # 检查该五行是否与维度关注的五行有生克关系
        if weight >= 3.0 and rtype in ('三会', '三合') and rel_element:
            if rel_element in target_elements:
                # 已在条件1处理，不重复
                pass
            else:
                # 间接影响判断：
                # - 维度五行生了大格局五行 → 被泄（木生火→火旺泄木）
                # - 大格局五行克维度五行 → 被克（火克金→金受损）
                # - 大格局五行生维度五行 → 被生（火生土→土得益）
                WO_SHENG_MAP = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
                WO_KE_MAP = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}

                for te in target_elements:
                    if not te:
                        continue
                    # 维度五行生大格局五行？（被泄）
                    if WO_SHENG_MAP.get(te) == rel_element:
                        tagged = dict(rel)
                        tagged['_indirect'] = 'drain'  # 被泄
                        tagged['_indirect_note'] = f'{te}生{rel_element}，{te}被泄耗'
                        filtered.append(tagged)
                        break
                    # 大格局五行克维度五行？（被克）
                    if WO_KE_MAP.get(rel_element) == te:
                        tagged = dict(rel)
                        tagged['_indirect'] = 'harm'  # 被克
                        tagged['_indirect_note'] = f'{rel_element}克{te}，{te}受损'
                        filtered.append(tagged)
                        break
                    # 大格局五行生维度五行？（得益）
                    if WO_SHENG_MAP.get(rel_element) == te:
                        tagged = dict(rel)
                        tagged['_indirect'] = 'benefit'  # 得益
                        tagged['_indirect_note'] = f'{rel_element}生{te}，{te}得益'
                        filtered.append(tagged)
                        break
            continue

        # 条件3：夫/妻宫特殊 — 日支（配偶宫）被冲/合/刑直接影响感情
        # 日支在 yuanju_zhis 中，如果关系的 partner 是日支所在位置
        # （这里简化处理：如果关系涉及"酉"且dim是qi，因为日支=酉=配偶宫）
        # 注意：这需要知道日支是什么，从 yuanju_zhis 无法直接得知哪个是日支
        # 暂时跳过这个优化，后续可以传入日支参数

    # 如果筛选后为空，不强制填充（该维度确实没有相关的地支关系）
    # 限制数量，避免信息过载
    return filtered[:3]


# ─────────────────────────────────────────────────────────────────
# 多层叠加
# ─────────────────────────────────────────────────────────────────

def _merge_layers(layers, gender, scene="full"):
    """
    多层叠加合并，根据场景动态调整权重。

    参数：
        layers: 各层分析结果列表
        gender: 性别
        scene:  场景类型 "full"/"yearly"/"monthly"/"daily"
    """
    weights = SCENE_WEIGHTS.get(scene, LAYER_WEIGHTS)
    merged = {}
    for dim in WUYU_DIMS:
        total_score     = 0.0
        all_notes       = []
        layer_summaries = []

        for layer in layers:
            layer_name = layer.get("layer", "")
            w          = weights.get(layer_name, 1.0)
            dim_data   = layer.get("wuyu", {}).get(dim, {})
            score      = dim_data.get("score", 0)
            notes      = dim_data.get("notes", [])

            total_score += score * w
            if notes:
                all_notes.extend([f"[{layer_name}] {n}" for n in notes])
            layer_summaries.append({
                "layer": layer_name,
                "gz":    layer.get("gz", ""),
                "score": score,
                "notes": notes,
            })

        # ── 通关逻辑：跨维度互动调整 ──────────────────────────────
        # 收集所有层级的十神信息，用于判断通关关系
        all_shishen_gan = [l.get("shishen_gan", "") for l in layers if l.get("shishen_gan")]
        all_shishen_zhi = [l.get("shishen_zhi", "") for l in layers if l.get("shishen_zhi")]
        all_shishen = set(all_shishen_gan + all_shishen_zhi)

        tongguan_notes = _check_tongguan(dim, all_shishen, gender)
        if tongguan_notes:
            for tn in tongguan_notes:
                total_score += tn['score_adj']
                all_notes.append(f"[通关] {tn['note']}")

        if total_score >= 3:
            rating = "大吉"
        elif total_score >= 1:
            rating = "小吉"
        elif total_score >= -1:
            rating = "平"
        elif total_score >= -3:
            rating = "需防"
        else:
            rating = "凶"

        merged[dim] = {
            "dim_name":        _dim_name(dim, gender),
            "dim_label":       _dim_label(dim, gender),
            "total_score":     round(total_score, 1),
            "rating":          rating,
            "notes":           all_notes,
            "layer_summaries": layer_summaries,
        }
    return merged


def _check_tongguan(dim: str, all_shishen: set, gender: str) -> list:
    """
    通关逻辑：检查跨维度的十神互动关系，返回评分调整。

    核心通关关系（子平法）：
    1. 食神制杀 → 禄维度：如果有杀（禄的负面压力），同时有食神，食神制杀，禄的压力减轻
    2. 印化杀 → 禄维度：如果有杀，同时有印星，印化杀生身，禄的压力减轻
    3. 伤官见官 → 禄维度：如果有伤官+正官同现，且无印制伤，禄维度受损
    4. 财星坏印 → 寿维度：如果有财星+印星同现，财克印，寿维度受损
    5. 食伤生财 → 财维度：如果有食伤+财星同现，食伤生财，财维度加分
    6. 官印相生 → 禄/寿维度：如果有官+印同现，官生印，禄寿双利
    """
    results = []

    if dim == 'lu':  # 禄（官禄/事业）
        has_sha = '杀' in all_shishen
        has_guan = '官' in all_shishen
        has_shi = '食' in all_shishen
        has_shang = '伤' in all_shishen
        has_yin = '印' in all_shishen or '枭' in all_shishen

        # 食神制杀：杀有食制，压力减轻
        if has_sha and has_shi:
            results.append({
                'score_adj': 1.0,
                'note': '食神制杀，七杀压力被食神牵制，事业压力有化解'
            })
        # 印化杀：杀有印化，化杀为权
        elif has_sha and has_yin:
            results.append({
                'score_adj': 0.8,
                'note': '印化杀，七杀被印星化解，化杀为权，有贵人助力'
            })
        # 伤官见官：伤官克正官，事业受损（除非有印制伤）
        if has_shang and has_guan and not has_yin:
            results.append({
                'score_adj': -1.0,
                'note': '伤官见官，伤官克正官且无印制，事业易有口舌是非'
            })
        elif has_shang and has_guan and has_yin:
            results.append({
                'score_adj': 0.3,
                'note': '伤官见官有印制，印星化解伤官之害，事业无大碍'
            })

    elif dim == 'shou':  # 寿（健康）
        has_cai = '财' in all_shishen or '才' in all_shishen
        has_yin = '印' in all_shishen or '枭' in all_shishen
        has_guan = '官' in all_shishen
        has_sha = '杀' in all_shishen

        # 财星坏印：财克印，印为寿星，寿受损
        if has_cai and has_yin:
            results.append({
                'score_adj': -0.5,
                'note': '财星坏印，财克印星（寿星），健康需多留意'
            })
        # 官印相生：官生印，印为寿星，寿得益
        if (has_guan or has_sha) and has_yin:
            results.append({
                'score_adj': 0.5,
                'note': '官印相生，官杀生印（寿星），生命力有源'
            })

    elif dim == 'cai':  # 财（财运）
        has_shi = '食' in all_shishen
        has_shang = '伤' in all_shishen
        has_cai = '财' in all_shishen or '才' in all_shishen

        # 食伤生财：食伤生财星，财运加分
        if (has_shi or has_shang) and has_cai:
            results.append({
                'score_adj': 0.8,
                'note': '食伤生财，才华转化为财富，求财有道'
            })

    elif dim == 'qi':  # 妻/夫（感情）
        has_bi = '比' in all_shishen or '劫' in all_shishen

        if gender == 'female':
            # 女命：夫星=官杀，比劫争夫
            has_guan = '官' in all_shishen or '杀' in all_shishen
            if has_guan and has_bi:
                results.append({
                    'score_adj': -0.5,
                    'note': '比劫争夫，感情易有竞争者出现'
                })
        else:
            # 男命：妻星=财星，比劫夺财
            has_cai = '财' in all_shishen or '才' in all_shishen
            if has_cai and has_bi:
                results.append({
                    'score_adj': -0.5,
                    'note': '比劫夺财，感情易有波折或竞争'
                })

    return results


def _build_text(merged, layers, title):
    """
    生成五运分析文字报告。
    不只是罗列要点，而是对每个维度做叙述性分析：
    - 原局底色（命局先天基础）
    - 大运背景（10年运势走向）
    - 流年叠加（当年具体影响）
    - 综合评级与建议
    """
    lines = [f"【{title}】", "─" * 50]
    layer_desc = " → ".join(f"{l['layer']}（{l.get('gz', '')}）" for l in layers)
    lines.append(f"分析层级：{layer_desc}")
    lines.append("")

    # 评级说明
    rating_desc = {
        '大吉': '运势旺盛，宜主动出击，把握机遇',
        '小吉': '运势偏顺，稳步推进，可适度扩展',
        '平':   '运势平稳，维持现状，不宜大动',
        '需防': '运势偏弱，宜守不宜攻，注意防范',
        '凶':   '运势受阻，需谨慎行事，避免冒险',
    }

    for dim in WUYU_DIMS:
        d = merged[dim]
        rating = d['rating']
        label  = d['dim_label']
        notes  = d['notes']
        layer_summaries = d.get('layer_summaries', [])

        lines.append(f"▶ {label}  【{rating}】")
        lines.append(f"  总评：{rating_desc.get(rating, '')}")

        # 寿星维度加注释说明
        if dim == 'shou':
            lines.append(f"  注：寿星包含印星（生身）和比劫（帮身），均代表日主生命力的来源")

        # 按层级分组叙述
        for ls in layer_summaries:
            layer_name = ls['layer']
            gz         = ls.get('gz', '')
            layer_notes = ls.get('notes', [])

            if not layer_notes:
                if layer_name == '原局':
                    lines.append(f"  ◆ 原局底色：此维度命局中无明显星曜，先天基础中性")
                else:
                    lines.append(f"  ◆ {layer_name}（{gz}）：对此维度影响平稳，无特别加减")
                continue

            if layer_name == '原局':
                lines.append(f"  ◆ 原局底色（先天基础）：")
            elif layer_name == '大运':
                lines.append(f"  ◆ {gz}大运背景（10年走向）：")
            elif layer_name == '流年':
                lines.append(f"  ◆ {gz}流年叠加（当年影响）：")
            elif layer_name == '流月':
                lines.append(f"  ◆ {gz}流月（本月影响）：")
            elif layer_name == '流日':
                lines.append(f"  ◆ {gz}流日（今日影响）：")

            for note in layer_notes[:3]:
                lines.append(f"    • {note}")

        # 综合建议
        if rating in ('大吉', '小吉'):
            advice = _get_dim_positive_advice(dim)
        elif rating in ('需防', '凶'):
            advice = _get_dim_caution_advice(dim)
        else:
            advice = _get_dim_neutral_advice(dim)
        if advice:
            lines.append(f"  ➤ 建议：{advice}")

        lines.append("")

    return "\n".join(lines)


def _get_dim_positive_advice(dim: str) -> str:
    """运势好时的维度建议"""
    advice_map = {
        'qi':   '感情运顺，已婚者宜增进感情，未婚者可主动拓展社交，缘分易至',
        'cai':  '财运旺盛，可适度投资或拓展业务，正财偏财均有进账机会',
        'zi':   '子女缘好，已有子女者亲子关系融洽，有生育计划者时机较佳',
        'lu':   '事业运旺，宜主动争取晋升机会，贵人相助，名声地位有望提升',
        'shou': '健康状态良好，精力充沛，适合开展新计划，注意保持规律作息',
    }
    return advice_map.get(dim, '')


def _get_dim_caution_advice(dim: str) -> str:
    """运势弱时的维度建议"""
    advice_map = {
        'qi':   '感情易生波折，已婚者多沟通避免误解，未婚者不宜仓促定情，耐心等待',
        'cai':  '财运偏弱，宜守不宜攻，避免大额投资或借贷，谨防财务损失',
        'zi':   '子女缘稍弱，与子女相处需多耐心，有生育计划者可稍作等待',
        'lu':   '事业压力较大，宜低调行事，避免与上司冲突，守住现有成果为先',
        'shou': '健康需注意，宜定期体检，避免过度劳累，注意饮食作息规律',
    }
    return advice_map.get(dim, '')


def _get_dim_neutral_advice(dim: str) -> str:
    """运势平稳时的维度建议"""
    advice_map = {
        'qi':   '感情平稳，维持现状，用心经营即可',
        'cai':  '财运平稳，稳健理财，量入为出',
        'zi':   '子女关系平稳，多陪伴交流',
        'lu':   '事业平稳推进，积累实力，等待时机',
        'shou': '健康状态平稳，保持良好生活习惯',
    }
    return advice_map.get(dim, '')


# ─────────────────────────────────────────────────────────────────
# 主分析器
# ─────────────────────────────────────────────────────────────────

class WuyuAnalyzer:
    """妻财子禄寿五运分析器，接收 bazi_chart 完整输出。"""

    def __init__(self, chart):
        self.chart   = chart
        self.day_gan = chart.get("day_gan", "")
        gender_raw   = chart.get("meta", {}).get("gender", "male")
        self.gender  = "male" if gender_raw.lower() in ("male", "m", "男") else "female"
        pillars      = chart.get("pillars", [])
        self.yuanju_zhis = {p["zhi"] for p in pillars if "zhi" in p}
        self._yuanju_layer = self._build_yuanju_layer()

    def _build_yuanju_layer(self):
        from .ten_gods_analyzer import get_ten_god
        pillars = self.chart.get("pillars", [])
        wuyu = {dim: {"score": 0, "notes": [], "shishen_gan": "", "shishen_zhi": ""} for dim in WUYU_DIMS}

        for p in pillars:
            gan      = p.get("gan", "")
            zhi      = p.get("zhi", "")
            is_day   = (p.get("index") == 2)
            shishen_gan      = p.get("gan_shishen", "")
            cangygan_details = p.get("cangygan_details", [])

            for dim in WUYU_DIMS:
                relevant = WUYU_SHISHEN_MAP.get(self.gender, WUYU_SHISHEN_MAP["male"]).get(dim, [])
                score    = _score_shishen(shishen_gan, dim, self.gender)
                notes    = wuyu[dim]["notes"]
                full     = SHISHEN_FULL.get(shishen_gan, shishen_gan)
                dim_n    = _dim_name(dim, self.gender)

                if shishen_gan in relevant and not is_day:
                    notes.append(f"{p['name']}天干{gan}（{full}）为{dim_n}星")

                for cd in cangygan_details:
                    ss = cd.get("shishen", "")
                    if ss in relevant:
                        notes.append(
                            f"{p['name']}地支{zhi}藏{cd['gan']}"
                            f"（{SHISHEN_FULL.get(ss, ss)}）为{dim_n}星"
                        )
                        score += 1

                wuyu[dim]["score"] = min(3, wuyu[dim]["score"] + score)

        return {"gz": "原局", "layer": "原局", "wuyu": wuyu}

    def _layer(self, gz, name):
        return _analyze_one_layer(gz, self.day_gan, self.gender, name, self.yuanju_zhis)

    # ── 公开接口 ──────────────────────────────────────────────────

    def analyze_yuanju(self):
        """原局五运（命局底色）。"""
        layers = [self._yuanju_layer]
        merged = _merge_layers(layers, self.gender)
        return {"title": "原局五运分析", "layers": layers, "merged": merged,
                "text": _build_text(merged, layers, "原局五运分析")}

    def analyze_with_dayun(self, dayun_gz):
        """原局 + 大运。"""
        layers = [self._yuanju_layer, self._layer(dayun_gz, "大运")]
        merged = _merge_layers(layers, self.gender, scene="full")
        title  = f"原局 × {dayun_gz}大运 五运分析"
        return {"title": title, "layers": layers, "merged": merged,
                "text": _build_text(merged, layers, title)}

    def analyze_with_liuyear(self, dayun_gz, year_gz):
        """原局 + 大运 + 流年（年运分析：流年为太岁，权重最高）。"""
        layers = [self._yuanju_layer, self._layer(dayun_gz, "大运"), self._layer(year_gz, "流年")]
        merged = _merge_layers(layers, self.gender, scene="yearly")
        title  = f"原局 × {dayun_gz}大运 × {year_gz}流年 五运分析"
        return {"title": title, "layers": layers, "merged": merged,
                "text": _build_text(merged, layers, title)}

    def analyze_with_liuyue(self, dayun_gz, year_gz, month_gz):
        """原局 + 大运 + 流年 + 流月（月运分析：流月为应期焦点，流年仍为太岁）。"""
        layers = [self._yuanju_layer, self._layer(dayun_gz, "大运"),
                  self._layer(year_gz, "流年"), self._layer(month_gz, "流月")]
        merged = _merge_layers(layers, self.gender, scene="monthly")
        title  = f"原局 × {dayun_gz}大运 × {year_gz}流年 × {month_gz}流月 五运分析"
        return {"title": title, "layers": layers, "merged": merged,
                "text": _build_text(merged, layers, title)}

    def analyze_with_liuri(self, dayun_gz, year_gz, month_gz, day_gz):
        """原局 + 大运 + 流年 + 流月 + 流日（日运分析：流日为当日焦点，流年为太岁，流月为应期）。"""
        layers = [self._yuanju_layer, self._layer(dayun_gz, "大运"),
                  self._layer(year_gz, "流年"), self._layer(month_gz, "流月"),
                  self._layer(day_gz, "流日")]
        merged = _merge_layers(layers, self.gender, scene="daily")
        title  = f"原局 × {dayun_gz}大运 × {year_gz}流年 × {month_gz}流月 × {day_gz}流日 五运分析"
        return {"title": title, "layers": layers, "merged": merged,
                "text": _build_text(merged, layers, title)}

    def analyze_current(self):
        """自动分析当前时间点（原局 + 当前大运 + 当前流年）。"""
        current  = self.chart.get("current", {})
        if not current:
            return self.analyze_yuanju()
        dayun_gz = current.get("dayun", {}).get("ganzhi", "")
        liuyear  = current.get("liuyear", {})
        year_gz  = liuyear.get("ganzhi", "") if liuyear else ""
        if dayun_gz and year_gz:
            return self.analyze_with_liuyear(dayun_gz, year_gz)
        elif dayun_gz:
            return self.analyze_with_dayun(dayun_gz)
        return self.analyze_yuanju()

    def analyze_current_with_month(self, month_gz):
        """当前大运 + 当前流年 + 指定流月（不可跳过大运和流年）。"""
        current  = self.chart.get("current", {})
        dayun_gz = current.get("dayun", {}).get("ganzhi", "") if current else ""
        liuyear  = current.get("liuyear", {}) if current else {}
        year_gz  = liuyear.get("ganzhi", "") if liuyear else ""
        if not dayun_gz or not year_gz:
            return {"error": "无法获取当前大运或流年，无法分析流月"}
        return self.analyze_with_liuyue(dayun_gz, year_gz, month_gz)

    def analyze_current_with_day(self, month_gz, day_gz):
        """当前大运 + 当前流年 + 指定流月 + 指定流日（完整五层）。"""
        current  = self.chart.get("current", {})
        dayun_gz = current.get("dayun", {}).get("ganzhi", "") if current else ""
        liuyear  = current.get("liuyear", {}) if current else {}
        year_gz  = liuyear.get("ganzhi", "") if liuyear else ""
        if not dayun_gz or not year_gz:
            return {"error": "无法获取当前大运或流年，无法分析流日"}
        return self.analyze_with_liuri(dayun_gz, year_gz, month_gz, day_gz)
