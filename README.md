# Picix 自动化助手

Picix 命令行助手与 Telegram Bot。项目统一使用
[uv](https://docs.astral.sh/uv/) 管理 Python、依赖和锁文件。

## 项目结构

```text
picix_live/
├── picix_bot/
│   ├── api/                 # HTTP、认证与只读 endpoint
│   ├── services/            # 商城、资源包、任务、解锁与自动化
│   ├── cli.py               # `picix` 统一命令入口
│   ├── __main__.py          # 兼容 `python -m picix_bot`
│   ├── app.py               # Telegram 命令、任务与通知
│   ├── optimizer.py         # 纯积分规划器（不访问网络）
│   └── settings.py          # 配置加载与环境变量覆盖
├── auto_unlock_helper.py    # 旧导入路径兼容层
├── tools/
│   ├── cloakbrowser_cdp.py
│   ├── chrome_devtools_cloak.ps1
│   └── cloak_runtime/       # CloakBrowser 独立 uv 子项目与锁文件
├── pyproject.toml           # 项目与依赖声明
├── uv.lock                  # 跨平台精确依赖锁
├── config_example.py        # 本地配置示例
├── start.bat               # Windows 交互控制台与统一入口
├── bot.bat                 # 快速启动 Bot
├── unlock.bat              # 快速执行每日解锁
├── status.bat              # 快速查看状态
├── start.sh                # Linux/macOS 交互控制台与统一入口
├── bot.sh                  # Linux/macOS 快速启动 Bot
├── unlock.sh               # Linux/macOS 快速执行每日解锁
├── status.sh               # Linux/macOS 快速查看状态
└── unlock_data/             # 本地状态、日志和续期 token（已忽略）
```

## 首次运行

1. 安装 uv：

   ```powershell
   winget install --id=astral-sh.uv -e
   ```

2. 创建本地秘密配置：

   ```powershell
   Copy-Item .env.example .env
   ```

3. 在 `.env` 中填写 `PICIX_BOT_TOKEN` 和允许使用机器人的用户 ID。
   如需 Python 格式的非敏感配置，可另外复制
   `config_example.py` 为 `config.py`。

4. 同步锁定依赖：

   ```powershell
   uv sync --locked
   ```

5. 启动 Bot：

   ```powershell
   uv run --locked --env-file .env picix bot
   ```

   Windows 推荐直接双击 `start.bat`，在交互菜单中选择操作。

   也可以使用参数或短入口：

   ```bat
   start.bat bot
   start.bat status
   start.bat unlock
   start.bat plan
   start.bat optimize
   start.bat token
   start.bat sync
   ```

   Linux/macOS 首次使用先赋予执行权限，然后运行：

   ```bash
   chmod +x start.sh bot.sh status.sh unlock.sh
   ./start.sh
   ```

   Shell 入口支持同样的参数：

   ```bash
   ./start.sh bot
   ./start.sh status
   ./start.sh unlock
   ./start.sh plan
   ./start.sh optimize
   ./start.sh token
   ./start.sh sync
   ```

## 常用命令

```powershell
# Telegram Bot
uv run --locked --env-file .env picix bot

# 查看 Picix 状态
uv run --locked --env-file .env picix status

# 执行每日解锁
uv run --locked --env-file .env picix unlock

# 仅查看计划 / 立即执行计划
uv run --locked --env-file .env picix plan
uv run --locked --env-file .env picix optimize

# 校验锁文件没有落后于 pyproject.toml
uv lock --check
```

Windows 下的 `bot.bat`、`status.bat` 和 `unlock.bat` 都转发给
`start.bat`，uv 与 `.env` 加载逻辑只维护一份。

Linux/macOS 下的 `bot.sh`、`status.sh` 和 `unlock.sh` 同样全部转发给
`start.sh`。

Bot 支持 `/status`、`/plan`、`/optimize`、`/unlock`、`/force_unlock`、
`/tasks`、`/package`、`/shop`、`/search`、`/mylist`、`/mysearch`、
`/history` 和 `/reauth`。

## 积分最大化策略

历史流水显示平台按约30天滚动周期要求至少消费450分，资源包和影片购买
计入消费；若不足，在周期结算时扣除差额。优化器不会固定购买两个包，而是：

1. 汇总所有未过期资源包并优先消耗；
2. 每天完成一次每日解锁，片单20次未完成时优先从片单选择；
3. 根据30天任务的实时截止时间计算可靠的剩余日更机会，无法靠日更
   完成的数量立即补齐；
4. 只有当前额度不够时才按需购买450分/30次的轻量包；
5. 若到周期兜底日仍未消费满450分，购买一个轻量包替代无收益的低消
   扣减；
6. 购买前校验商品ID、价格和次数，积分不足或商城字段变化时停止。

这样会保留跨周期剩余额度，避免“每周期固定两包”产生的浪费。

## 配置

秘密值放在 `.env` 或服务器环境变量中；`config.py` 只建议保存非敏感
配置。环境变量优先：

| 环境变量 | 说明 |
|---|---|
| `PICIX_BOT_TOKEN` | BotFather 提供的 Telegram Bot Token |
| `PICIX_AUTHORIZATION` | 可选；通常由 `/reauth` 自动续期并持久化 |
| `PICIX_ALLOWED_USER_IDS` | 允许的用户 ID，多个值用英文逗号分隔 |
| `PICIX_NOTIFICATION_THRESHOLD` | 资源包剩余次数通知阈值 |
| `PICIX_CHECK_INTERVAL` | 认证和资源包检查间隔，单位为秒 |
| `PICIX_AUTO_UNLOCK_HOUR` | 每日自动解锁小时；设为 `none` 时每小时检查 |
| `PICIX_AUTO_UNLOCK_MINUTE` | 每日自动解锁分钟 |
| `PICIX_AUTO_OPTIMIZE` | 是否让定时任务执行完整优化，默认 `true` |
| `PICIX_AUTO_PURCHASE` | 是否允许真实扣分自动购包，默认 `true` |
| `PICIX_TIMEZONE` | 低消周期与时间显示时区，默认 `Asia/Shanghai` |
| `PICIX_MINIMUM_MONTHLY_SPEND` | 每月最低消费，默认450 |
| `PICIX_PACKAGE_GOOD_ID` | 轻量包商城商品ID，默认1 |
| `PICIX_PACKAGE_PRICE` | 购买前校验价格，默认450 |
| `PICIX_PACKAGE_QUOTA` | 购买前校验次数，默认30 |
| `PICIX_SPEND_CYCLE_DAYS` | 低消滚动周期天数，默认30 |
| `PICIX_SPEND_TRIGGER_DAY` | 周期内兜底购包日，默认第25天 |
| `PICIX_POINTS_RESERVE` | 自动购买后至少保留的积分 |
| `PICIX_MAX_AUTO_PURCHASES` | 单次任务最多自动购包数，默认2 |
| `PICIX_MAX_AUTO_UNLOCKS` | 单次任务最多自动解锁数，默认50 |

`.env`、`config.py`、`unlock_data/` 和虚拟环境都不会进入版本控制。

## uv 环境

- Bot 使用项目默认环境 `.venv`。
- CloakBrowser 使用独立环境 `.venv-cloak`，由
  `tools/chrome_devtools_cloak.ps1` 按 `tools/cloak_runtime/uv.lock`
  自动同步。
- 不再维护 `requirements.txt`，依赖只修改 `pyproject.toml`，随后运行
  `uv lock`。
- `uv.lock` 应当保留并提交，部署和启动使用 `--locked` 防止依赖漂移。

## 登录自动续期

认证失效后，Bot 会获取动态 `/login <code>` 指令并发送给授权用户。
用户把整行指令发送给 `@vStreamingBot` 后，Bot 会轮询结果并自动保存新
authorization，无需编辑源码或重启。

详细说明见：

- [Telegram Bot 使用说明](TG机器人使用说明.md)
- [登录续期与 CloakBrowser 注意事项](登录续期与CloakBrowser注意事项.md)
- [命令行助手说明](README_助手.md)

## 安全注意事项

- 不要提交 `.env`、`config.py`、`unlock_data/`、Bot Token 或 authorization。
- `/reauth` 只应开放给明确配置的用户。
- 生产环境使用 `uv run --locked`，升级依赖时再显式运行 `uv lock`。
- 多用户 Linux 服务器应执行
  `chmod 600 .env unlock_data/authorization.json`，限制其他本地用户读取。
