#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
肌肉 Agent 日报生成脚本
收集所有数据源，生成每日健康日报 markdown 文件

数据来源：
  - 有品秤 OCR（早/晚体重数据）
  - 三餐热量数据（USDA 查询结果）
  - Garmin 数据（步数、运动、睡眠、心率）

用法：
    python3 daily-report-generator.py
    python3 daily-report-generator.py --date 2024-01-15
    python3 daily-report-generator.py --date 2024-01-15 --output /path/to/report.md
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.expanduser("~/.openclaw/.env"))
except ImportError:
    pass

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(
            os.path.expanduser('~/.openclaw/workspace-jirou/logs/daily-report.log'),
            mode='a',
            encoding='utf-8'
        ) if os.path.exists(os.path.expanduser('~/.openclaw/workspace-jirou/logs')) else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

# 路径配置
WORKSPACE = os.path.expanduser('~/.openclaw/workspace-jirou')
PENDING_DIR = os.path.join(WORKSPACE, 'memory', 'pending')
REPORTS_DIR = os.path.join(WORKSPACE, 'memory', 'reports')


def load_json_file(filepath: str) -> dict:
    """安全加载 JSON 文件"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"加载文件失败 {filepath}：{e}")
    return {}


def load_scale_data(date_str: str, time_of_day: str) -> dict:
    """
    加载有品秤数据

    Args:
        date_str: 日期字符串 YYYY-MM-DD
        time_of_day: 'morning' 或 'evening'

    Returns:
        秤数据字典，失败返回空字典
    """
    # 文件命名规则：morning-scale-YYYY-MM-DD.md（与 WORKFLOW.md 和 cron 一致）
    filepath = os.path.join(PENDING_DIR, f'{time_of_day}-scale-{date_str}.md')
    # 兼容旧格式 JSON 文件
    if not os.path.exists(filepath):
        filepath = os.path.join(PENDING_DIR, f'{time_of_day}-scale-{date_str}.json')
    if not os.path.exists(filepath):
        filepath = os.path.join(PENDING_DIR, f'{date_str}-{time_of_day}-scale.json')
    data = load_json_file(filepath)
    # 支持两种格式：
    #   1. 包裹格式（有 success + data 字段）：4/15 后的数据
    #   2. 平铺格式（直接存储）：4/14 及更早的数据
    if data.get('success') and data.get('data'):
        raw = data['data']
    elif data.get('weight_kg') or data.get('weight'):
        raw = data
    else:
        logger.info(f"{time_of_day}体重数据不存在：{filepath}")
        return {}
    logger.info(f"加载{time_of_day}体重数据：{filepath}")
    return {
        'weight': raw.get('weight_kg') or raw.get('weight'),
        'body_fat': raw.get('body_fat_pct') or raw.get('body_fat_percent') or raw.get('body_fat'),
        'muscle_rate': raw.get('muscle_rate_pct') or raw.get('muscle_rate_percent') or raw.get('muscle_rate'),
        'muscle_level': raw.get('muscle_level') or raw.get('muscle_storage_grade'),
        'visceral_fat': raw.get('visceral_fat') or raw.get('visceral_fat_index'),
        'water': raw.get('water_pct') or raw.get('water_percent') or raw.get('water'),
        'protein': raw.get('protein_pct') or raw.get('protein_percent') or raw.get('protein'),
        'bone_mass': raw.get('bone_mass_kg') or raw.get('bone_mass'),
        'bmr': raw.get('bmr_kcal') or raw.get('bmr'),
        'total_score': raw.get('total_score') or raw.get('score'),
    }


def load_meal_data(date_str: str, meal_type: str) -> dict:
    """
    加载餐食数据

    Args:
        date_str: 日期字符串 YYYY-MM-DD
        meal_type: 'breakfast'、'lunch'、'dinner' 或 'snack'

    Returns:
        餐食数据字典，失败返回空字典
    """
    # 文件命名规则：breakfast-YYYY-MM-DD.md（与 WORKFLOW.md 和 cron 一致）
    filepath_md = os.path.join(PENDING_DIR, f'{meal_type}-{date_str}.md')
    filepath_json = os.path.join(PENDING_DIR, f'{meal_type}-{date_str}.json')
    filepath_old = os.path.join(PENDING_DIR, f'{date_str}-{meal_type}.json')

    # 按优先级尝试加载
    for filepath in [filepath_md, filepath_json, filepath_old]:
        if os.path.exists(filepath):
            data = load_json_file(filepath)
            if data.get('items'):
                logger.info(f"加载{meal_type}数据：{filepath}")
                return data
            # .md 文件可能不是 JSON 格式，尝试解析 markdown
            if filepath.endswith('.md'):
                # 如果是 markdown 格式的餐食记录，返回原始内容标记
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    if content:
                        logger.info(f"加载{meal_type}数据（md格式）：{filepath}")
                        return {"raw_content": content, "items": []}
                except IOError:
                    pass

    logger.info(f"{meal_type}数据不存在")
    return {}


def get_garmin_data(date_str: str) -> dict:
    """
    从 Garmin CLI 获取当天数据

    Args:
        date_str: 日期字符串 YYYY-MM-DD

    Returns:
        Garmin 数据字典
    """
    garmin_data = {}

    # 获取活动数据（使用 search 而不是 --date）
    try:
        result = subprocess.run(
            ['gccli', 'activities', 'search', '--start-date', date_str, '--end-date', date_str, '--json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            activities = json.loads(result.stdout)
            garmin_data['activities'] = activities
            logger.info(f"Garmin 活动数据获取成功：{len(activities)} 条")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Garmin 活动数据获取失败：{e}")

    # 获取步数数据
    try:
        result = subprocess.run(
            ['gccli', 'health', 'steps', 'daily', '--start', date_str, '--end', date_str, '--json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            steps_data = json.loads(result.stdout)
            garmin_data['steps'] = steps_data
            logger.info("Garmin 步数数据获取成功")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Garmin 步数数据获取失败：{e}")

    # 获取睡眠数据（使用 health sleep，包含完整睡眠阶段）
    try:
        result = subprocess.run(
            ['gccli', 'health', 'sleep', date_str, '--json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            sleep_data = json.loads(result.stdout)
            garmin_data['sleep'] = sleep_data
            logger.info("Garmin 睡眠数据获取成功")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Garmin 睡眠数据获取失败：{e}")

    # 获取 HRV 数据
    try:
        result = subprocess.run(
            ['gccli', 'health', 'hrv', date_str, '--json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            hrv_data = json.loads(result.stdout)
            garmin_data['hrv'] = hrv_data
            logger.info("Garmin HRV 数据获取成功")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Garmin HRV 数据获取失败：{e}")

    # 获取最大摄氧量
    try:
        result = subprocess.run(
            ['gccli', 'health', 'max-metrics', date_str, '--json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            vo2_data = json.loads(result.stdout)
            if vo2_data and len(vo2_data) > 0:
                garmin_data['vo2max'] = vo2_data[0]
                logger.info("Garmin VO2max 数据获取成功")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Garmin VO2max 数据获取失败：{e}")

    # 获取每日健康摘要（包含正确的 BMR）
    try:
        result = subprocess.run(
            ['gccli', 'health', 'summary', date_str, '--json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            health_data = json.loads(result.stdout)
            garmin_data['health_summary'] = health_data
            logger.info("Garmin 健康摘要获取成功")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Garmin 健康摘要获取失败：{e}")

    return garmin_data


def parse_garmin_summary(garmin_data: dict) -> dict:
    """
    解析 Garmin 数据，提取关键指标

    Args:
        garmin_data: 原始 Garmin 数据

    Returns:
        解析后的摘要数据
    """
    summary = {
        'steps': None,
        'distance_km': None,
        'active_calories': None,
        'exercise_calories': None,
        'total_calories_burned': None,
        'bmr_calories': None,
        'resting_heart_rate': None,
        'hrv': None,
        'hrv_status': None,
        'sleep_score': None,
        'sleep_score_qualifier': None,
        'sleep_duration_min': None,
        'sleep_deep_min': None,
        'sleep_light_min': None,
        'sleep_rem_min': None,
        'sleep_awake_min': None,
        'sleep_spo2_avg': None,
        'sleep_spo2_low': None,
        'vo2max': None,
        'exercises': [],
    }

    # 优先从 health_summary 解析（包含正确的 BMR 和总消耗）
    health = garmin_data.get('health_summary', {})
    if health:
        summary['total_calories_burned'] = health.get('totalKilocalories')
        summary['active_calories'] = health.get('activeKilocalories')
        summary['bmr_calories'] = health.get('bmrKilocalories')
        summary['steps'] = health.get('totalSteps')
        summary['distance_km'] = (health.get('totalDistanceMeters') or 0) / 1000
        summary['resting_heart_rate'] = health.get('restingHeartRate')

    # 备用：从 summary 字典解析（gccli activities 的输出格式）
    # 格式：{total_kcal, active_kcal, bmr_kcal, total_steps, ...}
    raw_summary = garmin_data.get('summary', {})
    if raw_summary:
        if summary.get('bmr_calories') is None:
            summary['bmr_calories'] = raw_summary.get('bmr_kcal') or raw_summary.get('bmr')
        if summary.get('total_calories_burned') is None:
            summary['total_calories_burned'] = raw_summary.get('total_kcal') or raw_summary.get('totalKilocalories')
        if summary.get('active_calories') is None:
            summary['active_calories'] = raw_summary.get('active_kcal') or raw_summary.get('activeKilocalories')
        if summary.get('steps') is None:
            summary['steps'] = raw_summary.get('total_steps')
        if summary.get('distance_km') is None:
            summary['distance_km'] = raw_summary.get('total_distance_m', 0) / 1000 if raw_summary.get('total_distance_m') else None

    # 解析 HRV 数据（health hrv）
    hrv_data = garmin_data.get('hrv', {})
    if isinstance(hrv_data, dict):
        hrv_summary = hrv_data.get('hrvSummary', {})
        summary['hrv'] = hrv_summary.get('lastNightAvg')
        summary['hrv_status'] = hrv_summary.get('status')

    # 解析睡眠数据（health sleep → dailySleepDTO）
    sleep_wrapper = garmin_data.get('sleep', {})
    if isinstance(sleep_wrapper, dict):
        # gccli health sleep 返回的结构是 {dailySleepDTO: {...}}
        sleep_data = sleep_wrapper.get('dailySleepDTO', sleep_wrapper)
        if isinstance(sleep_data, dict) and sleep_data:
            summary['sleep_score'] = sleep_data.get('sleepScores', {}).get('overall', {}).get('value')
            summary['sleep_score_qualifier'] = sleep_data.get('sleepScores', {}).get('overall', {}).get('qualifierKey')
            duration = sleep_data.get('sleepTimeSeconds', 0)
            summary['sleep_duration_min'] = round(duration / 60) if duration else None
            summary['sleep_deep_min'] = round((sleep_data.get('deepSleepSeconds') or 0) / 60)
            summary['sleep_light_min'] = round((sleep_data.get('lightSleepSeconds') or 0) / 60)
            summary['sleep_rem_min'] = round((sleep_data.get('remSleepSeconds') or 0) / 60)
            summary['sleep_awake_min'] = round((sleep_data.get('awakeSleepSeconds') or 0) / 60)
            summary['sleep_spo2_avg'] = sleep_data.get('averageSpO2Value')
            summary['sleep_spo2_low'] = sleep_data.get('lowestSpO2Value')

    # 解析 VO2max 数据
    vo2_data = garmin_data.get('vo2max', {})
    if isinstance(vo2_data, dict):
        summary['vo2max'] = vo2_data.get('generic', {}).get('vo2MaxValue')

    # 解析步数数据（备用，覆盖 health_summary）
    steps_data = garmin_data.get('steps', {})
    if isinstance(steps_data, dict) and not summary.get('steps'):
        summary['steps'] = steps_data.get('totalSteps') or steps_data.get('steps')
        summary['distance_km'] = steps_data.get('totalDistance') or steps_data.get('distanceInMeters', 0) / 1000
        summary['active_calories'] = steps_data.get('activeKilocalories') or steps_data.get('calories') or summary.get('active_calories')
    elif isinstance(steps_data, list) and steps_data and not summary.get('steps'):
        day = steps_data[0]
        summary['steps'] = day.get('totalSteps')
        summary['distance_km'] = day.get('totalDistanceMeters', 0) / 1000
        summary['active_calories'] = day.get('activeKilocalories') or summary.get('active_calories')

    # 解析活动数据（运动）
    activities = garmin_data.get('activities', [])
    if isinstance(activities, list):
        for activity in activities:
            exercise = {
                'name': activity.get('activityName', '未知运动'),
                'duration_min': round(activity.get('duration', 0) / 60),
                'calories': activity.get('calories'),
                'avg_hr': activity.get('averageHR'),
                'max_hr': activity.get('maxHR'),
            }
            summary['exercises'].append(exercise)
            if exercise.get('calories'):
                summary['exercise_calories'] = (summary['exercise_calories'] or 0) + exercise['calories']

    # 如果没有 health_summary 数据，才用活动+运动计算总消耗
    if not garmin_data.get('health_summary'):
        active = summary.get('active_calories') or 0
        exercise = summary.get('exercise_calories') or 0
        if active or exercise:
            summary['total_calories_burned'] = active + exercise

    return summary


def format_minutes(minutes) -> str:
    """将分钟数格式化为 Xh Xm 格式"""
    if minutes is None:
        return '-'
    h = minutes // 60
    m = minutes % 60
    if h == 0:
        return f'{m}m'
    if m == 0:
        return f'{h}h'
    return f'{h}h {m}m'


def format_meal_section(meal_data: dict, meal_name: str) -> str:
    """格式化餐食章节"""
    if not meal_data or not meal_data.get('items'):
        return f'  - {meal_name}：-'

    lines = [f'  - {meal_name}：']
    for item in meal_data['items']:
        name = item.get('name', item.get('food_name', '未知'))
        weight = item.get('weight_g', item.get('estimated_weight_g', 0))
        cals = item.get('calories', item.get('calories_kcal', 0))
        estimated = '（估算）' if item.get('estimated') else ''
        lines.append(f'    - {name}（{weight}g）：{cals} kcal{estimated}')

    total = meal_data.get('total_calories', meal_data.get('total_calories_kcal', 0))
    lines.append(f'    小计：{total} kcal')
    return '\n'.join(lines)


def get_calorie_status(calorie_diff: int) -> str:
    """根据热量差返回状态描述"""
    if calorie_diff < -500:
        return '⚠️ 摄入严重不足'
    elif calorie_diff < -200:
        return '✅ 健康减脂区间'
    elif calorie_diff < 200:
        return '⚖️ 基本持平'
    elif calorie_diff < 500:
        return '📈 轻度盈余'
    else:
        return '⚠️ 热量盈余过多'


def get_weekday_zh(date_obj: date) -> str:
    """获取中文星期"""
    weekdays = ['一', '二', '三', '四', '五', '六', '日']
    return f'星期{weekdays[date_obj.weekday()]}'


def generate_report(date_str: str) -> str:
    """
    生成指定日期的健康日报

    Args:
        date_str: 日期字符串 YYYY-MM-DD

    Returns:
        markdown 格式的日报内容
    """
    logger.info(f"开始生成 {date_str} 的日报...")

    report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    # ── 1. 加载所有数据 ──
    morning_scale = load_scale_data(date_str, 'morning')
    evening_scale = load_scale_data(date_str, 'evening')
    breakfast = load_meal_data(date_str, 'breakfast')
    lunch = load_meal_data(date_str, 'lunch')
    dinner = load_meal_data(date_str, 'dinner')
    # 零食文件可能是 snack 或 afternoon-snack，尝试两种文件名
    snack = load_meal_data(date_str, 'snack')
    if not snack or not snack.get('items'):
        snack = load_meal_data(date_str, 'afternoon-snack')
    if not snack or not snack.get('items'):
        snack = load_meal_data(date_str, 'afternoon_snack')

    # ── 2. 获取 Garmin 数据 ──
    # 优先从 cron 预抓取的文件读取（Garmin-YYYY-MM-DD.md）
    garmin_file = os.path.join(PENDING_DIR, f'Garmin-{date_str}.md')
    garmin_file_json = os.path.join(PENDING_DIR, f'Garmin-{date_str}.json')
    garmin_raw = {}
    if os.path.exists(garmin_file):
        garmin_raw = load_json_file(garmin_file)
        logger.info(f"从预抓取文件加载 Garmin 数据：{garmin_file}")
    elif os.path.exists(garmin_file_json):
        garmin_raw = load_json_file(garmin_file_json)
        logger.info(f"从预抓取文件加载 Garmin 数据：{garmin_file_json}")

    # 如果预抓取文件不存在或为空，实时抓取
    if not garmin_raw:
        logger.info("预抓取文件不存在，尝试实时抓取 Garmin 数据...")
        garmin_raw = get_garmin_data(date_str)
    garmin = parse_garmin_summary(garmin_raw)

    # ── 3. 计算热量 ──
    total_intake = sum([
        breakfast.get('total_calories', breakfast.get('total_calories_kcal', 0)) or 0,
        lunch.get('total_calories', lunch.get('total_calories_kcal', 0)) or 0,
        dinner.get('total_calories', dinner.get('total_calories_kcal', 0)) or 0,
        snack.get('total_calories', snack.get('total_calories_kcal', 0)) or 0,
    ])

    # BMR 以 Garmin 为准（有品秤数据仅作参考）
    bmr = garmin.get('bmr_calories') or morning_scale.get('bmr') or evening_scale.get('bmr')

    total_burned = None
    calorie_diff = None
    if garmin.get('total_calories_burned'):
        total_burned = garmin['total_calories_burned']
        if total_intake > 0 and total_burned > 0:
            calorie_diff = total_intake - total_burned

    # ── 4. 格式化日报 ──
    date_display = f"{report_date.year}年{report_date.month}月{report_date.day}日 {get_weekday_zh(report_date)}"

    # 体重数据行
    def fmt(val, unit=''):
        return f"{val}{unit}" if val is not None else '-'

    weight_morning = fmt(morning_scale.get('weight'), ' kg')
    weight_evening = fmt(evening_scale.get('weight'), ' kg')
    fat_morning = fmt(morning_scale.get('body_fat'), '%')
    fat_evening = fmt(evening_scale.get('body_fat'), '%')
    muscle_morning = fmt(morning_scale.get('muscle_rate'), '%')
    muscle_evening = fmt(evening_scale.get('muscle_rate'), '%')
    muscle_level_morning = fmt(morning_scale.get('muscle_level'))
    muscle_level_evening = fmt(evening_scale.get('muscle_level'))
    visceral_morning = fmt(morning_scale.get('visceral_fat'))
    visceral_evening = fmt(evening_scale.get('visceral_fat'))
    water_morning = fmt(morning_scale.get('water'), '%')
    water_evening = fmt(evening_scale.get('water'), '%')
    protein_morning = fmt(morning_scale.get('protein'), '%')
    protein_evening = fmt(evening_scale.get('protein'), '%')
    bone_morning = fmt(morning_scale.get('bone_mass'), ' kg')
    bone_evening = fmt(evening_scale.get('bone_mass'), ' kg')
    resting_hr = fmt(garmin.get('resting_heart_rate'), ' bpm')
    hrv_val = garmin.get('hrv')
    hrv_status = garmin.get('hrv_status', '')
    hrv = f"{hrv_val} ms" if hrv_val else '-'
    if hrv_status:
        hrv += f"（{hrv_status}）"
    bmr_display = fmt(bmr, ' kcal')
    vo2max_display = fmt(garmin.get('vo2max'))
    sleep_score = fmt(garmin.get('sleep_score'))
    sleep_duration = format_minutes(garmin.get('sleep_duration_min'))
    sleep_deep = format_minutes(garmin.get('sleep_deep_min'))
    sleep_light = format_minutes(garmin.get('sleep_light_min'))
    sleep_rem = format_minutes(garmin.get('sleep_rem_min'))
    sleep_awake = format_minutes(garmin.get('sleep_awake_min'))

    steps = fmt(garmin.get('steps'))
    if garmin.get('steps'):
        steps = f"{garmin['steps']:,}步"
    distance = f"{garmin['distance_km']:.1f} km" if garmin.get('distance_km') else '-'
    active_cals = fmt(garmin.get('active_calories'), ' kcal')
    exercise_cals = fmt(garmin.get('exercise_calories'), ' kcal')
    total_burned_display = fmt(total_burned, ' kcal')
    total_intake_display = f"~{total_intake} kcal" if total_intake > 0 else '-'

    # 热量差
    if calorie_diff is not None:
        status = get_calorie_status(calorie_diff)
        diff_sign = '+' if calorie_diff > 0 else ''
        calorie_diff_display = f"{diff_sign}{calorie_diff} kcal（{status}）"
    else:
        calorie_diff_display = '-'

    # 运动详情
    exercise_lines = []
    if garmin.get('exercises'):
        for ex in garmin['exercises']:
            ex_name = ex.get('name', '未知运动')
            ex_dur = format_minutes(ex.get('duration_min'))
            ex_cals = fmt(ex.get('calories'), ' kcal')
            ex_avg_hr = fmt(ex.get('avg_hr'), ' bpm')
            ex_max_hr = fmt(ex.get('max_hr'), ' bpm')
            exercise_lines.extend([
                f'  - 运动类型：{ex_name}',
                f'  - 运动时长：{ex_dur}',
                f'  - 运动消耗：{ex_cals}',
                f'  - 平均心率：{ex_avg_hr}',
                f'  - 最大心率：{ex_max_hr}',
            ])
    else:
        exercise_lines = [
            '  - 运动类型：-',
            '  - 运动时长：-',
            '  - 运动消耗：-',
            '  - 平均心率：-',
            '  - 最大心率：-',
        ]

    # 消耗说明（包含 BMR）
    active_sum = garmin.get('active_calories') or 0
    exercise_sum = garmin.get('exercise_calories') or 0
    bmr_sum = garmin.get('bmr_calories') or 0
    if total_burned:
        consumption_note = f"*消耗 = BMR {bmr_sum} + 活动 {active_sum} + 运动 {exercise_sum} = {total_burned} kcal"
    else:
        consumption_note = '*消耗 = 数据不可用'

    report = f"""📊 {date_display} 健康日报

## ⚖️ 身体数据
  - 体重: {weight_morning}（晨）/ {weight_evening}（晚）
  - 体脂: {fat_morning}（晨）/ {fat_evening}（晚）
  - 肌肉：{muscle_morning}（晨）/ {muscle_evening}（晚）
  - 储肌能力：{muscle_level_morning}（晨）/ {muscle_level_evening}（晚）
  - 内脏脂肪：{visceral_morning}（晨）/ {visceral_evening}（晚）
  - 水分：{water_morning}（晨）/ {water_evening}（晚）
  - 蛋白质：{protein_morning}（晨）/ {protein_evening}（晚）
  - 骨量：{bone_morning}（晨）/ {bone_evening}（晚）
  - 静息心率: {resting_hr}
  - HRV: {hrv}
  - BMR: {bmr_display}
  - 最大摄氧量: {vo2max_display}

## 😴 睡眠情况
  - 得分: {sleep_score}
  - 时长: {sleep_duration}
  - 阶段：深睡{sleep_deep} / 浅睡{sleep_light} / REM {sleep_rem} / 清醒{sleep_awake}

## 🔥 热量情况
  - 总摄入: {total_intake_display}
  - 总消耗: {total_burned_display}
  - 缺口: {calorie_diff_display}

### 🍽️ 昨日摄入
{format_meal_section(breakfast, '早餐')}
{format_meal_section(lunch, '午餐')}
{format_meal_section(dinner, '晚餐')}
{format_meal_section(snack, '零食')}

### 💪 昨日消耗
#### 🏃 日常活动（支出1）
  - 步数: {steps}
  - 距离: {distance}
  - 活动消耗: {active_cals}

#### 🏋️ 昨日运动（支出2）
{chr(10).join(exercise_lines)}

{consumption_note}
"""
    return report.strip()


def main():
    parser = argparse.ArgumentParser(
        description='肌肉 Agent 日报生成脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python3 daily-report-generator.py
  python3 daily-report-generator.py --date 2024-01-15
  python3 daily-report-generator.py --date 2024-01-15 --output /tmp/report.md
        """
    )
    parser.add_argument(
        '--date',
        default=datetime.now().strftime('%Y-%m-%d'),
        help='日期 YYYY-MM-DD（默认今天）'
    )
    parser.add_argument('--output', help='输出文件路径（默认：memory/pending/YYYY-MM-DD.md）')
    parser.add_argument('--debug', action='store_true', help='启用调试日志')

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 确保目录存在
    os.makedirs(PENDING_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # 生成日报
    try:
        report_content = generate_report(args.date)
    except Exception as e:
        logger.error(f"日报生成失败：{e}", exc_info=True)
        sys.exit(1)

    # 确定输出路径（默认保存到 pending 目录，命名为 YYYY-MM-DD.md）
    output_path = args.output or os.path.join(PENDING_DIR, f'{args.date}.md')
    output_path = os.path.expanduser(output_path)

    # 保存日报（pending 目录，待用户确认后归档到 reports/）
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    logger.info(f"日报已保存至：{output_path}")

    # 同时归档到 reports 目录
    archive_path = os.path.join(REPORTS_DIR, f'{args.date}.md')
    with open(archive_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    logger.info(f"日报已归档至：{archive_path}")

    # 同时输出到 stdout
    print(report_content)


if __name__ == '__main__':
    main()
