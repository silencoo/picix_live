"""
配置示例文件
复制此文件为 config.py 并修改配置
注意：不要将 config.py 提交到版本控制系统

也可以使用以下环境变量，它们的优先级高于本文件：
- PICIX_BOT_TOKEN
- PICIX_AUTHORIZATION（可选；Bot 自动续期后无需手动设置）
- PICIX_ALLOWED_USER_IDS（多个 ID 用英文逗号分隔）
- PICIX_NOTIFICATION_THRESHOLD
- PICIX_CHECK_INTERVAL
- PICIX_AUTO_UNLOCK_HOUR
- PICIX_AUTO_UNLOCK_MINUTE
"""

# Bot Token 等秘密请写入 .env，不要写进 Python 文件。

# 用户权限配置
ALLOWED_USER_IDS = []  # 空列表表示所有人可用
# 或者填入允许的用户ID列表，例如：
# ALLOWED_USER_IDS = [123456789, 987654321]

# 通知阈值
NOTIFICATION_THRESHOLD = 10  # 剩余次数低于此值时通知用户

# 检查间隔（秒）
CHECK_INTERVAL = 3600  # 每小时检查一次（3600秒）

# 每日自动解锁时间
AUTO_UNLOCK_HOUR = 9
AUTO_UNLOCK_MINUTE = 0
