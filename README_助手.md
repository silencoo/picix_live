# Picix 积分最大化助手

## 规则与目标

当前已记录的积分流水表明，平台按约30天滚动周期要求合格消费至少450分：

- 购买资源包与直接购买影片会计入消费；
- 未达到450分时，平台扣除 `450 - 本周期合格消费`；
- “最低消费450 - 不足部分扣减”本身不算新的消费。

30天任务奖励为：每日解锁15分、解锁50部640分、从片单解锁20部
100分。月任务奖励只有达到门槛后才获得，不能按进度折算。

## 自动策略

优化器读取实时积分、积分流水、全部有效资源包和任务截止时间，然后：

1. 优先使用快过期的已有额度，不固定每月购买两个包；
2. 每天完成一次解锁；
3. 片单任务未完成时优先从片单选片；
4. 若任务剩余数量无法靠截止日前每天一次完成，立即执行补量；
5. 额度不足时才购买轻量包，购买前核对商品ID、450分价格和30次额度；
6. 周期第25天仍未消费满450分时，购买一包替代结算时的低消扣减；
7. 积分不足、商品参数变化或资源包未确认到账时停止，不盲目扣分。

一个新30天周期通常先完成每日1次并补约20次；之后继续每天1次。
第二包只会在第一包额度真正不足时购买。跨周期剩余次数会继续使用，
所以长期成本低于“每周期固定两包”。

## 使用

```bash
# 查看状态
uv run --locked --env-file .env picix status

# 只计算计划，不产生购买或解锁
uv run --locked --env-file .env picix plan

# 执行计划；PICIX_AUTO_PURCHASE=true 时可能真实扣分购包
uv run --locked --env-file .env picix optimize

# 只执行一次普通解锁
uv run --locked --env-file .env picix unlock
```

Telegram 中对应 `/status`、`/plan`、`/optimize` 和 `/unlock`。Bot 默认
在配置时间每天执行一次完整优化。

## 关键配置

```dotenv
PICIX_AUTO_OPTIMIZE=true
PICIX_AUTO_PURCHASE=true
PICIX_MINIMUM_MONTHLY_SPEND=450
PICIX_PACKAGE_GOOD_ID=1
PICIX_PACKAGE_PRICE=450
PICIX_PACKAGE_QUOTA=30
PICIX_SPEND_CYCLE_DAYS=30
PICIX_SPEND_TRIGGER_DAY=25
PICIX_POINTS_RESERVE=0
PICIX_MAX_AUTO_PURCHASES=2
PICIX_MAX_AUTO_UNLOCKS=50
```

如果希望先观察计划，把 `PICIX_AUTO_PURCHASE=false`；自动解锁仍会使用
已经确认存在的资源包次数，但不会购买新包。

## 本地数据

- `unlock_data/authorization.json`：登录续期结果；
- `unlock_data/unlock_log.json`：本地解锁记录；
- `unlock_data/api_log.log`：API诊断日志。

整个 `unlock_data/` 已被 Git 忽略。不要把 `.env`、authorization 或 Bot
Token 放入源码。
