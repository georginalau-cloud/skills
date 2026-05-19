# 🔍 Skill: ocr-scale

## 功能说明

使用 EasyOCR 识别有品智能体重秤截图，提取身体数据。

---

## 输入

- `--image`：图片路径（JPG/PNG/WEBP）
- `--output`：输出 JSON 文件路径（可选）

---

## 输出

成功时返回 JSON：

```json
{
  "success": true,
  "timestamp": "2024-01-15T08:05:00",
  "data": {
    "weight": 65.5,
    "body_fat": 18.2,
    "muscle_rate": 46.3,
    "visceral_fat": 7,
    "bmr": 1589,
    "water": 57.8,
    "protein": 18.5,
    "bone_mass": 2.8,
    "muscle_level": "标准"
  },
  "confidence": 0.92,
  "raw_text": ["65.5 kg", "体脂 18.2%", ...]
}
```

失败时返回：

```json
{
  "success": false,
  "error": "错误信息",
  "confidence": 0.0
}
```

---

## 识别字段

| 字段 | 中文名 | 单位 | 正则匹配 |
|-----|-------|------|---------|
| weight | 体重 | kg | `(\d+\.?\d*)\s*kg` |
| body_fat | 体脂率 | % | `体脂[率]?\s*(\d+\.?\d*)` |
| muscle_rate | 肌肉率 | % | `肌肉[率]?\s*(\d+\.?\d*)` |
| visceral_fat | 内脏脂肪指数 | - | `内脏脂肪\s*(\d+)` |
| bmr | 基础代谢率 | kcal | `基础代谢[率]?\s*(\d+)` |
| water | 水分 | % | `水分\s*(\d+\.?\d*)` |
| protein | 蛋白质 | % | `蛋白质\s*(\d+\.?\d*)` |
| bone_mass | 骨量 | kg | `骨量\s*(\d+\.?\d*)` |
| muscle_level | 储肌能力等级 | - | `储肌能力\s*([优良标准偏低不足]+)` |

---

## 使用示例

```bash
# 识别早晨体重截图
python3 ocr_scale.py --image ~/Downloads/scale_morning.jpg

# 识别并保存结果
python3 ocr_scale.py \
    --image ~/.openclaw/media/inbound/scale.jpg \
    --output ~/.openclaw/workspace-jirou/memory/pending/2024-01-15-morning-scale.json
```

---

## 依赖

- Python 3.8+
- easyocr
- Pillow
- numpy

安装：

```bash
pip3 install easyocr Pillow numpy
```

---

## 注意事项

1. 首次运行会下载 EasyOCR 模型文件（约 500MB），后续从缓存加载
2. 无 GPU 时识别较慢（约 5-10 秒/张图）
3. 图片清晰度越高识别越准确，建议图片分辨率 ≥ 720p
4. 有品秤截图需完整显示所有数据（勿裁剪）


## ⚠️ Self-Verify 输出前核查

使用本 skill 产出结论后、发给用户之前，必须完成以下核查：

1. **数据溯源**：所有结论必须能在原始数据/脚本输出中找到对应依据，禁止脑补
2. **不确定降级**：出现"绝对/肯定/永远"→ 改写为"可能/通常/大概率"
3. **矛盾检查**：是否与之前说过的内容矛盾？矛盾则明说"之前说错了"
4. **通过检查后再输出**
