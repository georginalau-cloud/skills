---
name: garmin-connect
description: Garmin Connect CLI - 获取Garmin健康和运动数据（中国区支持）
metadata:
  emoji: ⌚
  os: [darwin, linux]
  requires:
    bins: [gccli]
  install:
    - id: source
      kind: source
      label: 源码编译
      command: |
        git clone https://github.com/bpauli/gccli.git /tmp/gccli
        cd /tmp/gccli && make build
        cp /tmp/gccli/bin/gccli /opt/homebrew/bin/
  config:
    - id: domain
      label: Garmin 域名
      default: garmin.cn
      description: 中国区用 garmin.cn，全球用 garmin.com
    - id: keyring_backend
      label: 凭证存储
      default: file
      description: 使用文件存储凭证（推荐）
---

# Garmin Connect

使用 `gccli` 获取 Garmin 健康和运动数据。支持中国区 (garmin.cn) 账号。

## 首次配置

### 1. 安装 gccli（如未安装）
```bash
git clone https://github.com/bpauli/gccli.git /tmp/gccli
cd /tmp/gccli && make build
cp /tmp/gccli/bin/gccli /opt/homebrew/bin/
```

### 2. 配置并登录
```bash
# 配置使用中国区
echo '{"default_account": "你的邮箱@163.com", "domain": "garmin.cn", "keyring_backend": "file"}' > ~/Library/Application\ Support/gccli/config.json

# 登录（会打开浏览器）
gccli auth login 你的邮箱@163.com
```

## 常用命令

### 健康数据
```bash
# 今日健康摘要
gccli health summary today

# 心率
gccli health hr today
gccli health rhr today

# HRV
gccli health hrv today

# 睡眠
gccli health sleep today

# Body Battery
gccli health body-battery today

# 压力
gccli health stress today

# 训练状态
gccli health training-status today
gccli health training-readiness today

# VO2max / 最大摄氧量
gccli health max-metrics today
```

### 活动数据
```bash
# 活动列表
gccli activities list --limit 10

# 活动详情
gccli activity summary <活动ID>

# 今日所有活动
gccli activities list --start-date 2026-03-21 --end-date 2026-03-21
```

### 身体数据
```bash
# 身体成分（体重、体脂等）
gccli body composition today

# 体重记录
gccli body weigh-ins --start 2026-01-01 --end 2026-03-21
```

### 训练记录
```bash
# 训练计划
gccli workouts list --limit 10

# 课程
gccli courses list
```

## 重要说明

- **中国区账号**: 设置 `domain: garmin.cn`
- **凭证存储**: 首次登录后，token 自动保存，后续无需再次输入密码
- **Token 刷新**: gccli 会自动刷新过期的 token
- **时区**: 数据默认使用账户时区（可通过 Garmin App 修改）


## ⚠️ Self-Verify 输出前核查

使用本 skill 产出结论后、发给用户之前，必须完成以下核查：

1. **数据溯源**：所有结论必须能在原始数据/脚本输出中找到对应依据，禁止脑补
2. **不确定降级**：出现"绝对/肯定/永远"→ 改写为"可能/通常/大概率"
3. **矛盾检查**：是否与之前说过的内容矛盾？矛盾则明说"之前说错了"
4. **通过检查后再输出**
