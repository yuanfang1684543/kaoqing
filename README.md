# Telegram 上下班打卡机器人

一个基于 Telegram 的考勤打卡机器人，支持上班/下班打卡、生成日报/周报/月报，每天凌晨自动推送考勤日报。

## 功能

| 命令 | 说明 |
|------|------|
| `/start` | 查看帮助 |
| `/punchin` | 上班打卡 |
| `/punchout` | 下班打卡 |
| `/report` | 今日考勤日报 |
| `/weekly` | 本周考勤周报 |
| `/monthly` | 本月考勤月报 |
| `/history` | 历史打卡记录 |
| *(自动)* | 每天 00:05 (UTC+8) 推送前一天日报 |

---

## 部署到 Railway（推荐）

一键部署到 [Railway](https://railway.app) 免费 plan，无需自己维护服务器。

### 前置条件

- 一个 [Railway](https://railway.app) 账号（GitHub 登录）
- 一个 Telegram Bot Token（找 [@BotFather](https://t.me/BotFather) 创建）

### 部署步骤

#### 1. 通过 GitHub 部署

```bash
# 创建 GitHub 仓库
git init
git add .
git commit -m "init: attendance bot"

# 推送到 GitHub
git remote add origin https://github.com/你的用户名/attendance-bot.git
git push -u origin main
```

#### 2. 在 Railway 创建项目

1. 进入 Railway Dashboard → **New Project** → **Deploy from GitHub repo**
2. 选择刚推送的仓库
3. 项目自动部署，Railway 会自动检测 `requirements.txt` 和 `Procfile`

#### 3. 配置环境变量

在 Railway 项目 → **Variables** 中设置：

| 变量 | 说明 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | **必填** — 你的 Telegram Bot Token |
| `DATA_DIR` | **选填** — 数据目录，配合 Volumes 使用（见下方） |

#### 4. 配置数据持久化（推荐）

Railway 的磁盘是临时性的，重启会丢失数据。使用 **Volumes** 持久化打卡记录：

1. 项目 → **Volumes** → **New Volume**
2. 名称：`attendance-data`
3. 挂载路径：`/data`
4. 在 **Variables** 中添加 `DATA_DIR=/data`

> 不配置 Volume 也可以使用，但 Railway 重启后历史打卡记录会丢失。

### 部署架构

```
┌─────────────┐     polling     ┌──────────────┐
│  Telegram   │ ◄──────────────► │   Railway    │
│  （用户）    │                  │  Worker 进程  │
└─────────────┘                  │  bot.py      │
                                 │              │
                                 │  Volumes     │
                                 │  /data/      │
                                 │  ├ attendance.json
                                 │  └ subscribed_chats.json
                                 └──────────────┘
```

---

## 本地运行

### 1. 准备工作

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 Token（从 @BotFather 获取）
cp .env.example .env
# 编辑 .env 文件，填入你的机器人 Token
```

### 2. 启动机器人

```bash
python bot.py
```

机器人启动后持续运行，接收 Telegram 命令，并在每天 00:05 自动推送日报。

### 3. 开始使用

在 Telegram 中找到你的机器人，发送 `/start` 查看帮助，然后就可以打卡了：

```
/punchin   - 上班打卡
/punchout  - 下班打卡
/report    - 查看今日考勤
```

---

## 使用场景

### 单人使用
直接与机器人私聊，打卡记录以你的 Telegram 显示名为准。

### 群组使用
将机器人拉入群组，每个成员用 `/punchin` 和 `/punchout` 打卡。日报会自动推送到所有与机器人对话过的聊天。

---

## 数据存储

打卡数据存储在 JSON 文件中，默认路径为 `data/attendance.json`（可通过 `DATA_DIR` 环境变量修改）：

```json
{
  "2026-04-30": {
    "date": "2026-04-30",
    "records": {
      "张三": { "clock_in": "09:01:23", "clock_out": "18:30:45" }
    }
  }
}
```

---

## 项目结构

```
├── bot.py                  # Telegram 机器人入口
├── Procfile                # Railway 进程配置
├── .env                    # 本地环境变量（已 gitignore）
├── .env.example            # 环境变量示例
├── requirements.txt        # 依赖清单
├── .gitignore
├── attendance_bot/
│   ├── __init__.py
│   ├── storage.py          # 数据持久化（支持 DATA_DIR 环境变量）
│   └── reporter.py         # 报表生成
└── README.md
```
