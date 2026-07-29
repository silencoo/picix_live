# Telegram 机器人使用说明

## 📋 功能特性

- ✅ 查看当前状态（任务进度、统计、收益）
- ✅ 执行每日解锁任务
- ✅ 查看资源包信息
- ✅ 自动监控剩余额度并通知
- ✅ 定时检查资源包状态

## 🚀 快速开始

### 1. 创建 Telegram 机器人

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 命令
3. 按照提示设置机器人名称和用户名
4. 获取 Bot Token（格式：`<bot-id>:<bot-token>`）

### 2. 配置机器人

复制本地环境变量示例并填写：

```powershell
Copy-Item .env.example .env
```

```dotenv
PICIX_BOT_TOKEN=你的Bot Token
PICIX_ALLOWED_USER_IDS=你的Telegram用户ID
PICIX_NOTIFICATION_THRESHOLD=10
```

### 3. 安装依赖

```bash
uv sync --locked
```

### 4. 运行机器人

```bash
uv run --locked --env-file .env python -m picix_bot
```

Linux/macOS 也可以使用：

```bash
chmod +x start.sh bot.sh status.sh unlock.sh
./start.sh bot
```

### 5. 在 Telegram 中使用

1. 搜索你的机器人（使用 BotFather 创建时设置的用户名）
2. 发送 `/start` 开始使用
3. 发送 `/setuser` 将你的用户ID添加到允许列表（如果设置了权限限制）

## 📱 可用命令

| 命令 | 说明 |
|------|------|
| `/start` | 开始使用机器人，显示欢迎信息 |
| `/status` | 查看当前状态（任务进度、统计、收益预估） |
| `/unlock` | 执行每日解锁任务 |
| `/package` | 查看资源包详情（剩余次数、过期时间） |
| `/reauth` | 获取 Picix 动态登录指令并自动等待续期 |
| `/help` | 显示帮助信息 |
| `/setuser` | 将当前用户添加到允许列表 |

## 🔔 自动通知功能

机器人会每小时自动检查一次资源包状态：

- 当剩余次数 ≤ `NOTIFICATION_THRESHOLD`（默认10次）时，会自动发送通知
- 通知会发送给所有已添加的用户
- 避免重复通知（同一天且剩余次数未变化时不重复通知）

## ⚙️ 配置说明

### 用户权限管理

**方式1：所有人可用（默认）**
```python
ALLOWED_USER_IDS = []  # 空列表
```

**方式2：限制特定用户**
```python
ALLOWED_USER_IDS = [123456789, 987654321]  # 填入用户ID列表
```

用户ID获取方法：
- 在 Telegram 中搜索 `@userinfobot`
- 发送任意消息，它会返回你的用户ID

### 通知阈值

```python
NOTIFICATION_THRESHOLD = 10  # 剩余次数低于此值时通知
```

可以根据需要调整，例如：
- `5` - 剩余5次时通知
- `20` - 剩余20次时通知

## 🔧 部署建议

### 本地运行

直接运行脚本：
```bash
uv run --locked --env-file .env python -m picix_bot
```

### 后台运行（Linux）

使用 `nohup` 或 `screen`：
```bash
nohup ./start.sh bot > bot.log 2>&1 &
```

或使用 `screen`：
```bash
screen -S picix-bot
./start.sh bot
# 按 Ctrl+A 然后 D 退出screen
```

### Windows 服务

可以使用 `NSSM` (Non-Sucking Service Manager) 将脚本注册为 Windows 服务。

### 定时任务

如果需要定时执行解锁，可以结合系统的定时任务：
- Windows: 任务计划程序
- Linux: crontab

## 📊 使用示例

### 查看状态
```
用户: /status

机器人: 📊 当前状态

📦 资源包
剩余次数: 25/30
过期时间: 2026-02-22 10:30
剩余天数: 30 天

📋 任务进度
✅ 每日解锁: 1/1 (100.0%)
   奖励: 15分
⏳ 每月解锁: 15/50 (30.0%)
   奖励: 640分
⏳ 每月解锁（片单）: 8/20 (40.0%)
   奖励: 100分

📈 本月统计 (2026-01)
总解锁数: 15/50
片单解锁数: 8/20
已解锁电影总数: 15

💰 收益预估
已获得: 225 分
待获得: 965 分
总计: 1190 分
成本: 900 分 (2次轻量包)
净收益: +290 分
```

### 执行解锁
```
用户: /unlock

机器人: ⏳ 正在执行解锁任务...
机器人: 🔓 正在解锁电影 ID: 75180 (来源: 片单1)...
机器人: ✅ 解锁成功！

更新后的任务进度：
✅ 每日解锁: 1/1
⏳ 每月解锁: 16/50
⏳ 每月解锁（片单）: 9/20
```

### 资源包通知
```
机器人: ⚠️ 资源包提醒

剩余次数: 8/30
剩余次数不足 10 次，请及时购买资源包！

过期时间: 2026-02-22 10:30
剩余天数: 30 天
```

## 🛠️ 故障排除

### 问题1: 机器人无响应

**检查：**
1. 确认 `BOT_TOKEN` 配置正确
2. 检查网络连接
3. 查看控制台错误信息

### 问题2: 无法接收通知

**检查：**
1. 确认已使用 `/setuser` 添加用户ID
2. 检查 `NOTIFICATION_THRESHOLD` 设置
3. 查看 `unlock_data/notification_log.json` 日志

### 问题3: 解锁失败

**检查：**
1. 确认 `AUTHORIZATION` token 有效
2. 检查资源包是否还有剩余次数
3. 查看网络连接

### 问题4: 权限错误

**检查：**
1. 如果设置了 `ALLOWED_USER_IDS`，确认用户ID已添加
2. 使用 `/setuser` 命令添加用户ID
3. 检查 `unlock_data/bot_config.json` 文件

## 📝 注意事项

1. **Token 安全**: 不要将 `BOT_TOKEN` 和 `AUTHORIZATION` 提交到公开仓库
2. **资源包监控**: 机器人每小时检查一次，如需更频繁，可修改代码中的 `interval` 参数
3. **通知频率**: 同一天且剩余次数未变化时不会重复通知
4. **数据存储**: 所有数据保存在 `unlock_data/` 目录

## 🔄 与原有脚本的关系

- Telegram 机器人集成了 `auto_unlock_helper.py` 的所有功能
- 数据文件共享（`unlock_data/` 目录）
- 可以同时使用命令行脚本和 Telegram 机器人
- 解锁记录和统计信息同步

## 💡 最佳实践

1. **日常使用**: 每天通过 Telegram 发送 `/unlock` 命令
2. **状态监控**: 定期使用 `/status` 查看进度
3. **资源包管理**: 使用 `/package` 查看剩余次数，及时购买
4. **自动化**: 让机器人后台运行，自动监控和通知
