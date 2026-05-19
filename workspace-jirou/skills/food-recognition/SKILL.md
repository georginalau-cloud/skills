# 🍽️ Skill: food-recognition

## 功能说明

识别图片或文字描述中的食物，并查询 USDA 数据库获取热量信息。

支持三种输入方式：
1. **餐食图片** → Google Vision API 或 MiniMax 识别 → USDA 查询热量
2. **菜单/外卖截图** → EasyOCR 提取文字 → USDA 查询热量
3. **文字描述** → 直接 USDA 查询热量

---

## 输入参数

| 参数 | 类型 | 说明 |
|-----|-----|-----|
| `--image` | string | 图片路径（餐食照片或菜单截图） |
| `--text` | string | 文字描述（如"米饭250g，红烧肉200g"） |
| `--meal-type` | string | 餐次类型（breakfast/lunch/dinner/snack） |
| `--date` | string | 日期（YYYY-MM-DD，默认今天） |
| `--output` | string | 输出 JSON 文件路径（可选） |
| `--ocr-mode` | string | OCR 模式（vision/minimax/easyocr，默认 vision） |

---

## 输出

成功时返回 JSON：

```json
{
  "success": true,
  "meal_type": "lunch",
  "date": "2024-01-15",
  "items": [
    {
      "name": "米饭",
      "name_en": "Rice, white, cooked",
      "weight_g": 250,
      "calories": 290,
      "protein_g": 5.4,
      "carbs_g": 63.8,
      "fat_g": 0.5,
      "source": "USDA"
    },
    {
      "name": "清蒸鲈鱼",
      "name_en": "Fish, bass, sea, cooked",
      "weight_g": 200,
      "calories": 184,
      "protein_g": 38.2,
      "carbs_g": 0,
      "fat_g": 3.8,
      "source": "USDA"
    }
  ],
  "total_calories": 474,
  "total_protein_g": 43.6,
  "total_carbs_g": 63.8,
  "total_fat_g": 4.3,
  "user_message": "🍱 午餐识别结果：\n• 米饭 (250g): 290 kcal\n• 清蒸鲈鱼 (200g): 184 kcal\n📊 合计：474 kcal"
}
```

---

## 食物 API 优先级

```
Google Vision API（每月 1000 次免费）
    ↓ 配额不足时
MiniMax M2.7（年包用户）
    ↓ API 不可用时
提示用户文字输入
```

---

## 中英文食物名称映射

内置常见中文食物的英文名称映射，用于 USDA 查询：

- 米饭 → rice white cooked
- 面条 → noodles cooked
- 包子 → steamed bun
- 饺子 → dumpling
- 红烧肉 → pork braised
- 炒鸡蛋 → eggs scrambled
- 豆腐 → tofu
- 西兰花 → broccoli cooked
- （更多映射见代码）

---

## 使用示例

```bash
# 识别餐食图片
python3 food_recognition.py --image ~/Downloads/lunch.jpg --meal-type lunch

# 使用 MiniMax 识别
python3 food_recognition.py --image meal.jpg --ocr-mode minimax

# 文字描述直接查询
python3 food_recognition.py --text "米饭250g 红烧肉150g 炒青菜200g" --meal-type lunch

# 菜单/外卖截图（EasyOCR 模式）
python3 food_recognition.py --image menu_screenshot.jpg --ocr-mode easyocr --meal-type dinner

# 保存结果
python3 food_recognition.py \
    --image lunch.jpg \
    --meal-type lunch \
    --date 2024-01-15 \
    --output ~/.openclaw/workspace-jirou/memory/pending/2024-01-15-lunch.json
```

---

## 依赖

- Python 3.8+
- requests
- easyocr（菜单 OCR 模式）
- google-cloud-vision（Vision API 模式）
- Pillow

```bash
pip3 install requests easyocr google-cloud-vision Pillow
```


## ⚠️ Self-Verify 输出前核查

使用本 skill 产出结论后、发给用户之前，必须完成以下核查：

1. **数据溯源**：所有结论必须能在原始数据/脚本输出中找到对应依据，禁止脑补
2. **不确定降级**：出现"绝对/肯定/永远"→ 改写为"可能/通常/大概率"
3. **矛盾检查**：是否与之前说过的内容矛盾？矛盾则明说"之前说错了"
4. **通过检查后再输出**
