# 🥗 Skill: usda-lookup

## 功能说明

查询 USDA FoodData Central 数据库，获取食物的精确营养成分信息。

---

## 输入参数

| 参数 | 类型 | 说明 |
|-----|-----|-----|
| `--food` | string | 食物名称（支持中英文） |
| `--weight` | float | 食物重量（克） |
| `--list` | flag | 返回多个匹配结果（不计算热量） |
| `--id` | int | 使用 USDA fdcId 直接查询 |

---

## 输出

成功时返回 JSON：

```json
{
  "success": true,
  "food_name": "brown rice",
  "food_name_zh": "糙米饭",
  "usda_description": "Rice, brown, cooked",
  "fdc_id": 168875,
  "weight_g": 250,
  "calories": 272,
  "protein_g": 5.5,
  "carbs_g": 56.8,
  "fat_g": 2.2,
  "fiber_g": 3.5,
  "sugar_g": 0.8,
  "sodium_mg": 8.0,
  "source": "USDA Foundation"
}
```

---

## USDA API 配额

| Key 类型 | 每小时限制 | 每天限制 |
|---------|---------|---------|
| DEMO_KEY | 30 次 | 50 次 |
| 注册免费 Key | 1000 次 | 无限制 |

申请注册 Key：https://fdc.nal.usda.gov/api-guide.html

---

## 使用示例

```bash
# 查询糙米饭 250g 的热量
python3 usda_lookup.py --food "brown rice" --weight 250

# 查询中文食物名
python3 usda_lookup.py --food "鸡胸肉" --weight 150

# 列出多个匹配结果
python3 usda_lookup.py --food "salmon" --list

# 使用 fdcId 精确查询
python3 usda_lookup.py --id 175167 --weight 200
```

---

## 依赖

- Python 3.8+
- requests

```bash
pip3 install requests
```


## ⚠️ Self-Verify 输出前核查

使用本 skill 产出结论后、发给用户之前，必须完成以下核查：

1. **数据溯源**：所有结论必须能在原始数据/脚本输出中找到对应依据，禁止脑补
2. **不确定降级**：出现"绝对/肯定/永远"→ 改写为"可能/通常/大概率"
3. **矛盾检查**：是否与之前说过的内容矛盾？矛盾则明说"之前说错了"
4. **通过检查后再输出**
