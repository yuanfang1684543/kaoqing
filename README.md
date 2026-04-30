# 🕐 Telegram 考勤打卡机器人

基于 Telegram Bot API 的上下班打卡机器人，托管于 [Railway](https://railway.app)。

## 功能

| 功能 | 说明 |
|------|------|
| 🏢 **上班打卡** | 点击按钮记录上班时间 |
| 🏠 **下班打卡** | 需先上班打卡，避免漏打卡 |
| 📊 **今日记录** | 查看当天打卡记录 |
| 📅 **近7天记录** | 查看最近一周打卡历史 |
| 👑 **管理员功能** | 查看全员今日记录 / 近30天考勤统计 |

## 快速部署到 Railway（推荐）

### 第 1 步：创建 Telegram Bot

在 Telegram 中搜索 [@BotFather](https://t.me/botfather)，发送：

```
/newbot
```

按提示设置 Bot 名称和用户名，保存获得的 **Bot Token**。

### 第 2 步：获取你的 User ID

在 Telegram 中搜索 [@userinfobot](https://t.me/userinfobot)，发送任意消息，获取你的 **User ID**。

### 第 3 步：一键部署到 Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template/python)

或手动部署：

1. **Fork/Clone 本项目** 并推送到你的 GitHub 仓库
2. 登录 [Railway](https://railway.app)，点击 **New Project** → **Deploy from GitHub repo**
3. 选择你的仓库，Railway 自动识别 Python 项目并开始构建
4. 构建成功后，在项目 **Variables** 中添加环境变量：

| 环境变量 | 必填 | 说明 |
|----------|------|------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `ADMIN_IDS` | ❌ | 管理员 User ID（多个用逗号分隔，如 `123,456`） |
| `DB_TYPE` | ❌ | 数据库类型，建议 Railway 生产环境设为 `postgres` |

5. **添加 PostgreSQL 数据库**（推荐）：
   - 点击 **New** → **Database** → **Add PostgreSQL**  
   - Railway 会自动创建 PostgreSQL 实例并注入 `DATABASE_URL` 环境变量  
   - 设置 `DB_TYPE=postgres` —— 数据将持久化存储，重启不会丢失
   - 如果不使用 PostgreSQL，`DB_TYPE` 留空或设为 `sqlite`（⚠️ 注意：SQLite 文件在 Railway 重启后会丢失）

6. 部署完成后，Railway 会自动启动 Bot。在 Telegram 中给你的 Bot 发送 `/start` 即可使用！

> **提示**：Railway 免费额度每月 500 小时（约 20 天），请留意用量。

## 本地开发

### 前提条件

- Python 3.9+
- pip

### 步骤

```bash
# 1. 克隆项目
git clone https://github.com/your-username/telegram-attendance-bot.git
cd telegram-attendance-bot

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的 BOT_TOKEN 和 ADMIN_IDS

# 4. 运行
python bot.py
```

### 使用 PostgreSQL（本地）

```bash
# 安装 psycopg2（已包含在 requirements.txt 中）

# 设置环境变量
export DB_TYPE=postgres
export DATABASE_URL=postgresql://user:password@localhost:5432/attendance

# 运行
python bot.py
```

## 项目结构

```
├── bot.py              # 机器人主程序（核心逻辑）
├── requirements.txt    # Python 依赖
├── Procfile            # Railway 启动配置
├── railway.json        # Railway 部署配置
├── .env.example        # 环境变量模板
├── .gitignore
└── README.md
```

## 命令列表

| 命令 | 权限 | 说明 |
|------|------|------|
| `/start` | 所有人 | 启动机器人，显示主菜单 |
| `/menu` | 所有人 | 显示操作菜单 |
| `/help` | 所有人 | 显示帮助信息 |
| `/today_all` | 管理员 | 查看今日全员打卡记录 |
| `/summary` | 管理员 | 查看近30天考勤统计摘要 |

## 技术栈

- **语言**: Python 3.9+
- **框架**: [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v20
- **数据库**: SQLite（本地） / PostgreSQL（Railway 生产）
- **托管**: Railway（Nixpacks 自动构建）

## 许可证

MIT License
