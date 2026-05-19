"""
[03] lib/ganzhi_calculator.py - 干支四柱计算模块
调用层级：被 src/yuanju.py、lib/format_analyzer.py、lib/yongshen_analyzer.py 等调用
依赖：无（纯计算，无外部依赖）

实现万年历算法，根据公历生日计算年月日时四柱干支。
支持 1900-2100 年范围。
"""

# 天干
HEAVENLY_STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']

# 地支
EARTHLY_BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']

# 地支对应生肖
ZODIAC_ANIMALS = ['鼠', '牛', '虎', '兔', '龙', '蛇', '马', '羊', '猴', '鸡', '狗', '猪']

# 天干五行（0=木, 1=火, 2=土, 3=金, 4=水）
STEM_ELEMENTS = {
    '甲': '木', '乙': '木',
    '丙': '火', '丁': '火',
    '戊': '土', '己': '土',
    '庚': '金', '辛': '金',
    '壬': '水', '癸': '水',
}

# 天干阴阳
STEM_POLARITY = {
    '甲': '阳', '乙': '阴', '丙': '阳', '丁': '阴', '戊': '阳',
    '己': '阴', '庚': '阳', '辛': '阴', '壬': '阳', '癸': '阴',
}

# 地支五行
BRANCH_ELEMENTS = {
    '子': '水', '丑': '土', '寅': '木', '卯': '木',
    '辰': '土', '巳': '火', '午': '火', '未': '土',
    '申': '金', '酉': '金', '戌': '土', '亥': '水',
}

# 地支阴阳
BRANCH_POLARITY = {
    '子': '阳', '丑': '阴', '寅': '阳', '卯': '阴',
    '辰': '阳', '巳': '阴', '午': '阳', '未': '阴',
    '申': '阳', '酉': '阴', '戌': '阳', '亥': '阴',
}

# 藏干（地支藏干）- [主气, 中气, 余气]，None表示无
HIDDEN_STEMS = {
    '子': ['癸', None, None],
    '丑': ['己', '癸', '辛'],
    '寅': ['甲', '丙', '戊'],
    '卯': ['乙', None, None],
    '辰': ['戊', '乙', '癸'],
    '巳': ['丙', '戊', '庚'],
    '午': ['丁', '己', None],
    '未': ['己', '丁', '乙'],
    '申': ['庚', '壬', '戊'],
    '酉': ['辛', None, None],
    '戌': ['戊', '辛', '丁'],
    '亥': ['壬', '甲', None],
}

# 节气数据（每年节气对应月柱起始）
# 月支对应（寅月=1月建寅，从立春开始）
MONTH_BRANCH_ORDER = ['寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥', '子', '丑']

# 节气参考日期（近似，实际按天文计算）
# 格式：(月, 日) 表示该节气通常在该月该日前后
SOLAR_TERMS_APPROX = [
    (2, 4),   # 立春 - 寅月开始
    (3, 6),   # 惊蛰 - 卯月开始
    (4, 5),   # 清明 - 辰月开始
    (5, 6),   # 立夏 - 巳月开始
    (6, 6),   # 芒种 - 午月开始
    (7, 7),   # 小暑 - 未月开始
    (8, 7),   # 立秋 - 申月开始
    (9, 8),   # 白露 - 酉月开始
    (10, 8),  # 寒露 - 戌月开始
    (11, 7),  # 立冬 - 亥月开始
    (12, 7),  # 大雪 - 子月开始
    (1, 6),   # 小寒 - 丑月开始（次年）
]

# 时辰对应（地支）
HOUR_BRANCHES = [
    (23, 1, '子'),   # 23:00 - 00:59
    (1, 3, '丑'),    # 01:00 - 02:59
    (3, 5, '寅'),    # 03:00 - 04:59
    (5, 7, '卯'),    # 05:00 - 06:59
    (7, 9, '辰'),    # 07:00 - 08:59
    (9, 11, '巳'),   # 09:00 - 10:59
    (11, 13, '午'),  # 11:00 - 12:59
    (13, 15, '未'),  # 13:00 - 14:59
    (15, 17, '申'),  # 15:00 - 16:59
    (17, 19, '酉'),  # 17:00 - 18:59
    (19, 21, '戌'),  # 19:00 - 20:59
    (21, 23, '亥'),  # 21:00 - 22:59
]

# 月干起始规则（五虎遁年起月法）
# 年干 -> 寅月（正月）天干起始
MONTH_STEM_START = {
    '甲': 2, '己': 2,   # 寅月从丙起
    '乙': 4, '庚': 4,   # 寅月从戊起
    '丙': 6, '辛': 6,   # 寅月从庚起
    '丁': 8, '壬': 8,   # 寅月从壬起
    '戊': 0, '癸': 0,   # 寅月从甲起
}

# 时干起始规则（五鼠遁日起时法）
# 日干 -> 子时天干起始
HOUR_STEM_START = {
    '甲': 0, '己': 0,   # 子时从甲起
    '乙': 2, '庚': 2,   # 子时从丙起
    '丙': 4, '辛': 4,   # 子时从戊起
    '丁': 6, '壬': 6,   # 子时从壬起（实际是壬，索引8）
    '戊': 8, '癸': 8,   # 子时从壬起（实际是庚，索引6）
}

# 修正五鼠遁日起时法
HOUR_STEM_START = {
    '甲': 0, '己': 0,   # 子时甲子，索引0
    '乙': 2, '庚': 2,   # 子时丙子，索引2
    '丙': 4, '辛': 4,   # 子时戊子，索引4
    '丁': 6, '壬': 6,   # 子时庚子，索引6
    '戊': 8, '癸': 8,   # 子时壬子，索引8
}


# 五行生克关系（供其他模块共用）
GENERATES = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
CONTROLS  = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}

# ─────────────────────────────────────────────────────────────────
# 地支关系常量（力量从强到弱）
# ─────────────────────────────────────────────────────────────────

# 地支三会局（方位会局，力量最强，三支齐全方成）
# 格式：(成员集合, 化成五行, 名称)
ZHI_SANHUI = [
    (frozenset({'寅', '卯', '辰'}), '木', '东方三会木局'),
    (frozenset({'巳', '午', '未'}), '火', '南方三会火局'),
    (frozenset({'申', '酉', '戌'}), '金', '西方三会金局'),
    (frozenset({'亥', '子', '丑'}), '水', '北方三会水局'),
]

# 地支三合局（力量次于三会，三支齐全方成）
ZHI_SANHE = [
    (frozenset({'申', '子', '辰'}), '水', '三合水局'),
    (frozenset({'寅', '午', '戌'}), '火', '三合火局'),
    (frozenset({'巳', '酉', '丑'}), '金', '三合金局'),
    (frozenset({'亥', '卯', '未'}), '木', '三合木局'),
]

# 地支半三合（两支，力量弱于三合）
# 格式：(支A, 支B, 化成五行, 说明)  — 只列旺支+库支或旺支+生支的组合
ZHI_BAN_SANHE = [
    ('子', '辰', '水', '子辰半合水'),
    ('申', '子', '水', '申子半合水'),
    ('午', '戌', '火', '午戌半合火'),
    ('寅', '午', '火', '寅午半合火'),
    ('酉', '丑', '金', '酉丑半合金'),
    ('巳', '酉', '金', '巳酉半合金'),
    ('卯', '未', '木', '卯未半合木'),
    ('亥', '卯', '木', '亥卯半合木'),
]

# 地支六合（两支相合，力量中等）
ZHI_HE6 = {
    '子': '丑', '丑': '子',
    '寅': '亥', '亥': '寅',
    '卯': '戌', '戌': '卯',
    '辰': '酉', '酉': '辰',
    '巳': '申', '申': '巳',
    '午': '未', '未': '午',
}
# 六合化成五行
ZHI_HE6_ELEMENT = {
    ('子', '丑'): '土', ('丑', '子'): '土',
    ('寅', '亥'): '木', ('亥', '寅'): '木',
    ('卯', '戌'): '火', ('戌', '卯'): '火',
    ('辰', '酉'): '金', ('酉', '辰'): '金',
    ('巳', '申'): '水', ('申', '巳'): '水',
    ('午', '未'): '火', ('未', '午'): '火',
}

# 地支六冲（两支相冲，动荡破坏）
ZHI_CHONG = {
    '子': '午', '午': '子',
    '丑': '未', '未': '丑',
    '寅': '申', '申': '寅',
    '卯': '酉', '酉': '卯',
    '辰': '戌', '戌': '辰',
    '巳': '亥', '亥': '巳',
}

# 地支三刑（三支或两支相刑）
# 无恩之刑：寅巳申（三支互刑）
# 持势之刑：丑戌未（三支互刑）
# 无礼之刑：子卯（两支互刑）
# 自刑：辰辰、午午、酉酉、亥亥
ZHI_XING = {
    '寅': ['巳'],   '巳': ['申'],   '申': ['寅'],   # 无恩之刑
    '丑': ['戌'],   '戌': ['未'],   '未': ['丑'],   # 持势之刑
    '子': ['卯'],   '卯': ['子'],                   # 无礼之刑
    '辰': ['辰'],   '午': ['午'],   '酉': ['酉'],   '亥': ['亥'],  # 自刑
}

# 地支六害（两支相害，力量弱于冲）
ZHI_HAI = {
    '子': '未', '未': '子',
    '丑': '午', '午': '丑',
    '寅': '巳', '巳': '寅',
    '卯': '辰', '辰': '卯',
    '申': '亥', '亥': '申',
    '酉': '戌', '戌': '酉',
}

# 地支相破（力量最弱）
ZHI_PO = {
    '子': '酉', '酉': '子',
    '丑': '辰', '辰': '丑',
    '寅': '亥', '亥': '寅',
    '卯': '午', '午': '卯',
    '巳': '申', '申': '巳',
    '未': '戌', '戌': '未',
}

# 地支关系力量权重（用于评分）
ZHI_RELATION_WEIGHTS = {
    '三会': 4.0,
    '三合': 3.0,
    '半三合': 1.5,
    '六合': 2.0,
    '拱合': 0.8,
    '六冲': -2.5,
    '三刑': -1.5,
    '六害': -1.0,
    '相破': -0.5,
}


def _julian_day(year, month, day):
    """计算儒略日数（用于日柱计算）"""
    if month <= 2:
        year -= 1
        month += 12
    A = int(year / 100)
    B = 2 - A + int(A / 4)
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + B - 1524


def get_year_pillar(year, month, day):
    """
    计算年柱（以立春为界，立春前属上一年）
    返回 (天干, 地支) 元组
    """
    # 判断是否已过立春（立春约2月4日）
    actual_year = year
    if month < 2 or (month == 2 and day < 4):
        actual_year = year - 1

    stem_idx = (actual_year - 4) % 10
    branch_idx = (actual_year - 4) % 12
    return HEAVENLY_STEMS[stem_idx], EARTHLY_BRANCHES[branch_idx]


def get_month_pillar(year, month, day, year_stem):
    """
    计算月柱（以节气为界）
    返回 (天干, 地支) 元组
    """
    # 确定月支（以节气为界）
    month_branch_idx = _get_month_branch_index(year, month, day)
    branch = MONTH_BRANCH_ORDER[month_branch_idx]

    # 确定月干（五虎遁年起月法）
    stem_start = MONTH_STEM_START.get(year_stem, 0)
    stem_idx = (stem_start + month_branch_idx) % 10
    stem = HEAVENLY_STEMS[stem_idx]

    return stem, branch


def _get_month_branch_index(year, month, day):
    """
    确定月支索引（0=寅月, 1=卯月, ..., 11=丑月）
    基于节气近似日期判断
    """
    # 查找当前所在月份的节气
    for i, (st_month, st_day) in enumerate(SOLAR_TERMS_APPROX):
        # 处理小寒在1月的特殊情况
        if st_month == 1:
            check_month = 1
            check_day = st_day
            if month == 1:
                if day >= check_day:
                    return 11  # 丑月
                else:
                    return 10  # 子月
            elif month == 12:
                # 12月需要判断是否过大雪（子月起始）
                continue

        if month == st_month:
            if day < st_day:
                # 还未到该节气，属于上个月支
                prev_idx = (i - 1) % 12
                return prev_idx
            else:
                return i
        elif month == st_month - 1 or (st_month == 1 and month == 12):
            # 跨月检查
            pass

    # 简化处理：直接按月份映射（近似）
    month_to_branch = {
        1: 11,   # 1月多数时间为丑月
        2: 0,    # 2月多数时间为寅月（立春后）
        3: 1,    # 3月为卯月
        4: 2,    # 4月为辰月
        5: 3,    # 5月为巳月
        6: 4,    # 6月为午月
        7: 5,    # 7月为未月
        8: 6,    # 8月为申月
        9: 7,    # 9月为酉月
        10: 8,   # 10月为戌月
        11: 9,   # 11月为亥月
        12: 10,  # 12月为子月
    }

    base_idx = month_to_branch.get(month, 0)

    # 节气日期前后的修正（1月立春前仍为上年丑月，2月立春前仍为丑月）
    if month in [1, 2] and day < 6:
        if month == 2 and day < 4:
            return 11  # 还在丑月
        elif month == 1:
            return 11  # 1月初通常还在丑月

    return base_idx


def get_day_pillar(year, month, day):
    """
    计算日柱
    参考点：1900年1月1日为甲戌日
    返回 (天干, 地支) 元组
    """
    # 计算与参考日的儒略日差
    ref_jd = _julian_day(1900, 1, 1)
    cur_jd = _julian_day(year, month, day)
    diff = cur_jd - ref_jd

    # 1900年1月1日：甲=0, 戌=10（六十甲子第11个）
    # 实际上1900年1月1日是甲戌日
    ref_stem_idx = 0    # 甲
    ref_branch_idx = 10  # 戌

    stem_idx = (ref_stem_idx + diff) % 10
    branch_idx = (ref_branch_idx + diff) % 12

    return HEAVENLY_STEMS[stem_idx], EARTHLY_BRANCHES[branch_idx]


def get_hour_pillar(hour, day_stem):
    """
    计算时柱（五鼠遁日起时法）
    hour: 0-23 的整数
    返回 (天干, 地支) 元组
    """
    # 确定时支
    hour_branch = '子'
    branch_idx = 0
    if hour == 23 or hour == 0:
        hour_branch = '子'
        branch_idx = 0
    else:
        for i, (start, end, branch) in enumerate(HOUR_BRANCHES[1:], 1):
            if start <= hour < end:
                hour_branch = branch
                branch_idx = i
                break

    # 确定时干
    stem_start = HOUR_STEM_START.get(day_stem, 0)
    stem_idx = (stem_start + branch_idx) % 10

    return HEAVENLY_STEMS[stem_idx], hour_branch


def calculate_four_pillars(year, month, day, hour=0):
    """
    计算四柱（年月日时）
    参数：
        year: 公历年份 (int)
        month: 公历月份 1-12 (int)
        day: 公历日期 1-31 (int)
        hour: 出生时辰 0-23 (int)，默认0
    返回：包含四柱信息的字典
    """
    # 年柱
    year_stem, year_branch = get_year_pillar(year, month, day)

    # 月柱
    month_stem, month_branch = get_month_pillar(year, month, day, year_stem)

    # 日柱
    day_stem, day_branch = get_day_pillar(year, month, day)

    # 时柱
    hour_stem, hour_branch = get_hour_pillar(hour, day_stem)

    # 生肖（根据年支）
    zodiac_idx = EARTHLY_BRANCHES.index(year_branch)
    zodiac = ZODIAC_ANIMALS[zodiac_idx]

    return {
        'year_pillar': {
            'stem': year_stem,
            'branch': year_branch,
            'gz': year_stem + year_branch,
            'stem_element': STEM_ELEMENTS[year_stem],
            'branch_element': BRANCH_ELEMENTS[year_branch],
            'hidden_stems': [s for s in HIDDEN_STEMS[year_branch] if s],
        },
        'month_pillar': {
            'stem': month_stem,
            'branch': month_branch,
            'gz': month_stem + month_branch,
            'stem_element': STEM_ELEMENTS[month_stem],
            'branch_element': BRANCH_ELEMENTS[month_branch],
            'hidden_stems': [s for s in HIDDEN_STEMS[month_branch] if s],
        },
        'day_pillar': {
            'stem': day_stem,
            'branch': day_branch,
            'gz': day_stem + day_branch,
            'stem_element': STEM_ELEMENTS[day_stem],
            'branch_element': BRANCH_ELEMENTS[day_branch],
            'hidden_stems': [s for s in HIDDEN_STEMS[day_branch] if s],
        },
        'hour_pillar': {
            'stem': hour_stem,
            'branch': hour_branch,
            'gz': hour_stem + hour_branch,
            'stem_element': STEM_ELEMENTS[hour_stem],
            'branch_element': BRANCH_ELEMENTS[hour_branch],
            'hidden_stems': [s for s in HIDDEN_STEMS[hour_branch] if s],
        },
        'day_master': day_stem,
        'day_master_element': STEM_ELEMENTS[day_stem],
        'zodiac': zodiac,
        'birth_info': {
            'year': year,
            'month': month,
            'day': day,
            'hour': hour,
        },
    }


def get_all_stems(pillars):
    """提取命局所有天干（含藏干）"""
    stems = []
    for pillar_key in ['year_pillar', 'month_pillar', 'day_pillar', 'hour_pillar']:
        p = pillars[pillar_key]
        stems.append(p['stem'])
        stems.extend(p['hidden_stems'])
    return stems


def get_element_counts(pillars):
    """统计命局五行数量（天干地支）"""
    counts = {'木': 0, '火': 0, '土': 0, '金': 0, '水': 0}
    for pillar_key in ['year_pillar', 'month_pillar', 'day_pillar', 'hour_pillar']:
        p = pillars[pillar_key]
        counts[p['stem_element']] += 1
        counts[p['branch_element']] += 1
        for s in p['hidden_stems']:
            counts[STEM_ELEMENTS[s]] += 1
    return counts


def get_daymaster_strength(pillars):
    """
    粗略判断日主旺衰
    返回: '旺', '中', '弱'
    """
    day_stem = pillars['day_master']
    day_element = STEM_ELEMENTS[day_stem]
    month_branch = pillars['month_pillar']['branch']
    month_element = BRANCH_ELEMENTS[month_branch]

    # 生克关系
    GENERATES = {'木': '火', '火': '土', '土': '金', '金': '水', '水': '木'}
    CONTROLS = {'木': '土', '火': '金', '土': '水', '金': '木', '水': '火'}

    # 统计帮身（比劫）和生身（印星）的数量
    all_stems = get_all_stems(pillars)
    help_count = 0
    oppose_count = 0

    for s in all_stems:
        if s == day_stem:
            continue
        s_element = STEM_ELEMENTS[s]
        if s_element == day_element:  # 比劫
            help_count += 1
        elif GENERATES.get(s_element) == day_element:  # 印星生身
            help_count += 1
        elif CONTROLS.get(day_element) == s_element:  # 财星耗身
            oppose_count += 1
        elif CONTROLS.get(s_element) == day_element:  # 官杀克身
            oppose_count += 1

    # 得令（月令是否帮身）
    di_ling = False
    if month_element == day_element:
        di_ling = True
        help_count += 2
    elif GENERATES.get(month_element) == day_element:
        di_ling = True
        help_count += 1

    total = help_count - oppose_count
    if total >= 3 or (di_ling and total >= 1):
        return '旺'
    elif total <= -2:
        return '弱'
    else:
        return '中'
