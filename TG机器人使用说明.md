# Telegram Bot 使用说明

## 快速开始

1. 从 `@BotFather` 创建机器人并取得 Bot Token。
2. 复制 `.env.example` 为 `.env`。
3. 至少填写：

   ```dotenv
   PICIX_BOT_TOKEN=你的Bot Token
   PICIX_ALLOWED_USER_IDS=你的Telegram用户ID
   ```

4. 同步并启动：

   ```bash
   uv sync --locked
   uv run --locked --env-file .env python -m picix_bot
   ```

也可在 Windows 运行 `start.bat`，或在 Linux/macOS 运行
`./start.sh bot`。

## 命令

| 命令 | 说明 |
|---|---|
| `/status` | 查看积分、全部有效额度、任务与优化计划 |
| `/plan` | 只生成积分最大化计划，不执行 |
| `/optimize` | 立即执行一次自动优化 |
| `/unlock` | 普通解锁一次 |
| `/force_unlock N` | 手动批量解锁N次 |
| `/tasks` | 查看与领取任务 |
| `/package` | 查看全部资源包 |
| `/shop` | 查看商品并手动购买 |
| `/history` | 查看积分流水 |
| `/reauth` | 获取动态登录指令并等待认证 |
| `/help` | 查看帮助 |

## 自动积分优化

默认 `PICIX_AUTO_OPTIMIZE=true`。每天到
`PICIX_AUTO_UNLOCK_HOUR:PICIX_AUTO_UNLOCK_MINUTE`，Bot 会：

- 读取当月合格消费，排除“最低消费不足部分扣减”；
- 优先使用已有且未过期的资源包；
- 完成每日解锁；
- 按30天任务的剩余时间自动补足无法靠日更完成的数量；
- 片单20次完成前优先从片单解锁；
- 额度不足时按需购包；
- 到滚动30天周期的兜底日仍未消费满450分时购包，避免积分白白被扣。

自动购买会真实扣除积分。购买前会核对商城商品ID、价格和次数；积分不
足、参数变化或资源包未确认到账时会停止并通知。

若只想观察：

```dotenv
PICIX_AUTO_PURCHASE=false
```

此时 `/plan` 和自动测算仍然可用，已有资源包也可继续使用，但 Bot 不会
买新包。

## 登录续期

认证失效时，Bot 会发送一行 `/login <code>`。把整行复制并发送给
`@vStreamingBot`；认证成功后 Bot 自动保存新 authorization，无需修改
Python 文件或重启。

会产生真实动作的命令仅允许已加入允许列表的用户。建议直接配置
`PICIX_ALLOWED_USER_IDS`；若留空，首次启动后由所有者立即发送
`/setuser` 完成初始化。`/reauth` 只允许明确列出的用户调用。

## 无显示器服务器

日常 Bot、API 解锁和动态登录不需要显示器。CloakBrowser 只用于必须
进行网页诊断或首次人工处理 Cloudflare 的场景；完成后 Bot 可继续在
无头服务器运行。

常见后台方式：

```bash
nohup ./start.sh bot > bot.log 2>&1 &
```

生产环境建议用 systemd，并限制秘密文件权限：

```bash
chmod 600 .env unlock_data/authorization.json
```

## 故障排查

- `/plan` 无法读取积分或任务：通常是 authorization 已失效，执行
  `/reauth`。
- 自动购买停止：查看通知中的商品ID、价格、次数或余额限制。
- 有包却显示0次：检查包是否已过期；程序会汇总全部有效包，不只看第一
  个。
- 解锁中途停止：检查资源包到账、可选影片和 API 日志。
