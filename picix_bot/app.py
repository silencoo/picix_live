"""Picix 积分最大化 Telegram Bot。"""
import requests
import sys
import io
import os
import json
import time
import asyncio
import builtins
import functools
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# 设置标准输出为无缓冲/行缓冲模式（立即输出，解决 Windows 输出延迟问题）
# 即使直接运行模块也能即时输出
os.environ.setdefault('PYTHONUNBUFFERED', '1')
try:
    if hasattr(sys.stdout, 'reconfigure'):
        # write_through=True 强制每次写入立即刷新
        sys.stdout.reconfigure(write_through=True)
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(write_through=True)
except Exception:
    # 如果不支持 reconfigure，保持默认行为
    pass

# 兜底：让所有 print 默认 flush=True，避免输出被缓冲
print = functools.partial(builtins.print, flush=True)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue
)

# 集中加载运行配置；环境变量优先于项目根目录的 config.py。
from .settings import settings
from .optimizer import build_optimization_plan

# 导入原有助手的功能
from auto_unlock_helper import (
    AUTHORIZATION, BASE_URL, HEADERS, DATA_DIR,
    load_json_file, save_json_file, api_request,
    get_task_list, get_unlock_log, analyze_tasks,
    unlock_movie, get_movie_lists, get_movie_list_detail,
    get_recommend_movies, find_unlocked_movie_from_list,
    find_unlocked_movie_from_recommend, save_unlock_record,
    get_point_history, get_all_paid_movies, check_auth_valid,
    search_movies, get_movie_detail, get_paid_movies, accept_default_tasks,
    should_unlock_from_list, accept_task, get_purchasable_packages,
    get_package_list, request_login_code, check_login_code,
    update_authorization, get_package_info, get_package_summary,
    build_live_optimization_plan, execute_points_optimization,
    unlock_movies_batch
)

# 设置标准输出为UTF-8编码（仅用于命令行输出，不影响Telegram消息）
# 注意：Telegram机器人不需要重定向stdout，这里注释掉避免冲突
# if sys.platform == 'win32':
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BOT_TOKEN = settings.token
ALLOWED_USER_IDS = settings.allowed_user_ids
NOTIFICATION_THRESHOLD = settings.notification_threshold
CHECK_INTERVAL = settings.check_interval
AUTO_UNLOCK_HOUR = settings.auto_unlock_hour
AUTO_UNLOCK_MINUTE = settings.auto_unlock_minute

# 数据文件
CONFIG_FILE = DATA_DIR / "bot_config.json"
NOTIFICATION_LOG = DATA_DIR / "notification_log.json"
AUTH_NOTIFICATION_LOG = DATA_DIR / "auth_notification_log.json"
AUTH_BOT_USERNAME = "vStreamingBot"
AUTH_REAUTH_TIMEOUT_SECONDS = 10 * 60
AUTH_REAUTH_COOLDOWN_SECONDS = 10 * 60
AUTH_REAUTH_LOCK = asyncio.Lock()

def buy_package(good_id):
    """购买指定资源包"""
    if good_id is None:
        return False, "缺少商品ID"
    data = {"goodId": str(good_id)}
    result = api_request("POST", "/Malls/payGood", data=data)
    if result:
        if result.get("success"):
            return True, result.get("msg", "")
        if result.get("_auth_failed"):
            return False, "认证失效，请更新 authorization"
        return False, result.get("msg", "未知错误")
    return False, "请求失败"


def _optimizer_options():
    return {
        "timezone_name": settings.timezone,
        "minimum_spend": settings.minimum_monthly_spend,
        "package_price": settings.package_price,
        "package_quota": settings.package_quota,
        "spend_cycle_days": settings.spend_cycle_days,
        "spend_trigger_day": settings.spend_trigger_day,
        "points_reserve": settings.points_reserve,
        "max_auto_purchases": settings.max_auto_purchases,
        "max_auto_unlocks": settings.max_auto_unlocks,
    }


def _execution_options():
    return {
        **_optimizer_options(),
        "allow_purchase": settings.auto_purchase,
        "package_good_id": settings.package_good_id,
    }


def format_optimization_plan(plan):
    """将纯计划对象格式化为适合 Telegram 的说明。"""
    data = plan.to_dict() if hasattr(plan, "to_dict") else plan
    if not data:
        return "❌ 无法生成积分优化计划"

    points = data.get("current_points")
    points_text = "未知" if points is None else str(points)
    cycle_end = data.get("spend_cycle_end")
    cycle_end_text = (
        datetime.fromtimestamp(
            cycle_end,
            tz=ZoneInfo(settings.timezone),
        ).strftime("%Y-%m-%d %H:%M")
        if cycle_end
        else "未知"
    )
    lines = [
        "🧮 **积分最大化计划**",
        "",
        f"当前积分: {points_text} 分",
        (
            f"本周期合格消费: {data.get('monthly_spend', 0)}/"
            f"{data.get('minimum_spend', 450)} 分"
        ),
        (
            f"低消周期: 第 {data.get('spend_cycle_day', 1)}/"
            f"{settings.spend_cycle_days} 天，截止 {cycle_end_text}"
        ),
        f"低消缺口: {data.get('spend_shortfall', 0)} 分",
        f"可用资源包次数: {data.get('package_remaining', 0)}",
        "",
        "**任务测算**",
        (
            f"50次任务: 还差 {data.get('monthly_remaining', 0)}，"
            f"可靠日更机会 {data.get('monthly_daily_slots', 0)}"
        ),
        (
            f"片单20次: 还差 {data.get('list_remaining', 0)}，"
            f"可靠日更机会 {data.get('list_daily_slots', 0)}"
        ),
        "",
        "**本次动作**",
        f"每日解锁: {data.get('daily_unlocks', 0)} 次",
        f"截止期补量: {data.get('catch_up_unlocks', 0)} 次",
        f"购买轻量包: {data.get('packages_to_buy', 0)} 个",
    ]

    reasons = data.get("purchase_reasons") or ()
    if reasons:
        lines.append("购买原因: " + "；".join(reasons))
    blockers = data.get("blocked_reasons") or ()
    if blockers:
        lines.extend(["", "⚠️ **限制**"])
        lines.extend(f"• {reason}" for reason in blockers)

    if (
        data.get("spend_shortfall", 0) > 0
        and data.get("packages_to_buy", 0) == 0
    ):
        lines.extend(
            [
                "",
                (
                    f"正常会在周期第 {settings.spend_trigger_day} 天前复用已有额度；"
                    "达到兜底日仍未消费满450分时才购包。若上方有限制，则需先处理限制。"
                ),
            ]
        )
    return "\n".join(lines)


def format_optimization_report(report):
    plan = report.get("plan") or {}
    lines = ["🤖 **自动积分优化结果**", ""]
    if plan:
        lines.append(
            f"计划: 购包 {plan.get('packages_to_buy', 0)} 个，"
            f"解锁 {plan.get('unlocks_now', 0)} 次"
        )
    purchases = report.get("purchases") or []
    if purchases:
        successful = sum(1 for item in purchases if item.get("success"))
        lines.append(f"实际购包: {successful}/{len(purchases)} 个")
    unlock_result = report.get("unlock_result") or {}
    if unlock_result:
        lines.append(
            f"实际解锁: {len(unlock_result.get('successes', []))}/"
            f"{unlock_result.get('attempted', 0)} 次"
        )
        if unlock_result.get("failure"):
            lines.append(f"途中停止: {unlock_result['failure']}")
    if not purchases and not unlock_result:
        lines.append("当前无需执行额外动作")
    for message in report.get("messages") or []:
        lines.append(f"⚠️ {message}")
    return "\n".join(lines)


def format_status_message():
    """格式化状态消息"""
    # 获取任务状态
    tasks = analyze_tasks()
    if not tasks:
        return "❌ 无法获取任务状态"

    # 获取并汇总全部可用资源包
    package_summary = get_package_summary()
    package = (
        package_summary["active"][0]["raw"]
        if package_summary["active"]
        else None
    )

    # 获取最新积分
    point_history = get_point_history()
    current_points = None
    if point_history and len(point_history) > 0:
        # 第一条记录是最新的，包含当前总积分
        current_points = point_history[0].get("totalPoints")

    # 获取解锁记录
    log = get_unlock_log()
    current_month = datetime.now().strftime("%Y-%m")
    monthly_stats = log["monthly_stats"].get(current_month, {
        "total": 0,
        "from_list": 0,
        "list_ids": []
    })

    # 构建消息
    msg = "📊 **当前状态**\n\n"

    # 显示当前积分
    if current_points is not None:
        msg += f"💰 **当前积分**: {current_points} 分\n\n"

    # 资源包信息
    if package:
        remaining = package_summary["remaining"]
        expired_at = package.get("expiredAt", 0)
        msg += "📦 **资源包**\n"
        msg += f"可用包数量: {len(package_summary['active'])}\n"
        msg += f"总剩余次数: {remaining}\n"
        if expired_at:
            expired_date = datetime.fromtimestamp(expired_at)
            days_left = (expired_date - datetime.now()).days
            msg += f"最近一包过期: {expired_date.strftime('%Y-%m-%d %H:%M')}\n"
            msg += f"剩余天数: {days_left} 天\n\n"
        else:
            msg += "\n"
        if remaining <= NOTIFICATION_THRESHOLD:
            msg += f"⚠️ **警告**: 剩余次数不足，请及时购买资源包！\n\n"
    else:
        msg += "📦 **资源包**: 未找到\n\n"

    # 任务进度
    msg += "📋 **任务进度**\n"
    for unique, info in tasks.items():
        status_icon = "✅" if info["is_finish"] else "⏳"
        progress = info['current'] / info['target'] * 100 if info['target'] > 0 else 0
        msg += f"{status_icon} {info['name']}: {info['current']}/{info['target']} ({progress:.1f}%)\n"
        msg += f"   奖励: {info['point']}分\n"

    # 本月统计
    msg += f"\n📈 **本月统计** ({current_month})\n"
    msg += f"总解锁数: {monthly_stats['total']}/50\n"
    msg += f"片单解锁数: {monthly_stats['from_list']}/20\n"
    msg += f"已解锁电影总数: {len(log['unlocked_movies'])}\n"

    # 收益预估
    daily_task = tasks.get("D_UL_1")
    monthly_task = tasks.get("M_UL_50")
    list_task = tasks.get("M_UL_ML_20")

    earned = 0
    potential = 0

    if daily_task:
        if daily_task["is_finish"]:
            earned += daily_task["point"]
        else:
            potential += daily_task["point"]

    if monthly_task:
        if monthly_task["is_finish"]:
            earned += monthly_task["point"]
        else:
            potential += monthly_task["point"]

    if list_task:
        if list_task["is_finish"]:
            earned += list_task["point"]
        else:
            potential += list_task["point"]

    msg += f"\n💰 **收益预估**\n"
    msg += f"已获得: {earned} 分\n"
    msg += f"待获得: {potential} 分\n"
    msg += f"任务奖励上限: {earned + potential} 分\n"
    msg += "注: 月任务奖励仅在达到门槛后计入\n"

    plan = build_optimization_plan(
        history=point_history,
        packages=package_summary["all"],
        tasks=tasks,
        **_optimizer_options(),
    )
    msg += "\n" + format_optimization_plan(plan)

    return msg

def _truncate_text(text, max_len=40):
    if not text:
        return ""
    return text if len(text) <= max_len else f"{text[:max_len - 3]}..."

def _escape_markdown(text: str) -> str:
    if text is None:
        return ""
    return re.sub(r"([_*\[`])", r"\\\1", str(text))

def _extract_stream_link(detail):
    """从详情中提取直链（已解锁时可用）"""
    if not detail or not detail.get("canPlay"):
        return None
    folders = detail.get("list", [])
    for folder in folders:
        files = folder.get("files", [])
        for f in files:
            stream = f.get("stream")
            if stream:
                return stream
    return None

def _first_value(data, keys, default=None):
    """从字典中取第一个非空值"""
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data:
            value = data.get(key)
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            return value
    return default

def _normalize_status(value):
    if isinstance(value, bool):
        return "可用" if value else "不可用"
    if isinstance(value, str):
        if value.upper() == "Y":
            return "可用"
        if value.upper() == "N":
            return "不可用"
    return value

def _extract_package_fields(pkg):
    name = _first_value(pkg, ["name", "title", "goodsName", "goodName", "packageName"])
    desc = _first_value(pkg, ["desc", "description", "remark", "note"])
    good_id = _first_value(pkg, ["goodId", "goodsId", "id"])
    price = _first_value(pkg, ["price", "point", "points", "amount", "cost", "coin"])
    total = _first_value(pkg, ["total", "count", "times", "quantity", "num", "quota"])
    valid_days = _first_value(pkg, ["validDays", "valid_day", "validDaysCount", "validTime"])
    status = _normalize_status(_first_value(pkg, ["status", "state", "isEnable", "enabled"]))
    return {
        "name": name,
        "desc": desc,
        "good_id": good_id,
        "price": price,
        "total": total,
        "valid_days": valid_days,
        "status": status
    }

def _build_shop_message(packages):
    lines = ["🛍️ **可购买商品**", "点击购买按钮后会再次确认。", ""]
    buttons = []
    category_map = {
        "package": "资源包",
        "inviteCode": "邀请码",
        "redeemCode": "兑换码"
    }

    if not packages:
        lines.append("❌ 未找到可购买商品")
        return "\n".join(lines).rstrip(), None

    for idx, pkg in enumerate(packages, 1):
        fields = _extract_package_fields(pkg)
        name = fields["name"] or "商品"
        good_id = fields["good_id"]
        header = f"{idx}. **{name}**"
        if good_id is not None:
            header += f" (ID: {good_id})"
        lines.append(header)
        if fields["desc"]:
            lines.append(f"• 说明: {fields['desc']}")
        if fields["price"] is not None:
            lines.append(f"• 价格/积分: {fields['price']}")
        if fields["total"] is not None:
            lines.append(f"• 次数: {fields['total']}")
        if fields["valid_days"] is not None:
            lines.append(f"• 有效期: {fields['valid_days']} 天")
        category = None
        if isinstance(pkg, dict):
            category = pkg.get("_category")
        if category:
            category_label = category_map.get(category, category)
            lines.append(f"• 分类: {category_label}")
        if fields["status"] is not None:
            lines.append(f"• 状态: {fields['status']}")
        lines.append("")

        if good_id is not None:
            short_name = _truncate_text(name, 8)
            buttons.append([
                InlineKeyboardButton(f"购买 {short_name}", callback_data=f"shopbuy:{good_id}")
            ])

    message = "\n".join(lines).rstrip()
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    return message, keyboard

def _find_package_by_good_id(packages, good_id):
    good_id_str = str(good_id)
    for pkg in packages or []:
        fields = _extract_package_fields(pkg)
        if fields["good_id"] is None:
            continue
        if str(fields["good_id"]) == good_id_str:
            return pkg
    return None

def _build_shop_confirm_message(good_id, pkg=None):
    lines = ["⚠️ **确认购买**"]
    if pkg:
        fields = _extract_package_fields(pkg)
        name = fields["name"] or "商品"
        lines.append(f"商品: **{name}**")
        lines.append(f"ID: `{good_id}`")
        if fields["price"] is not None:
            lines.append(f"价格/积分: {fields['price']}")
        if fields["total"] is not None:
            lines.append(f"次数: {fields['total']}")
        if fields["valid_days"] is not None:
            lines.append(f"有效期: {fields['valid_days']} 天")
    else:
        lines.append(f"商品ID: `{good_id}`")
    lines.append("确认后将立即扣除积分/次数，是否继续？")
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 确认购买", callback_data=f"shopconfirm:{good_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"shopcancel:{good_id}")
        ]
    ])
    return "\n".join(lines), keyboard

def _build_tasks_message(tasks):
    """构建任务列表消息与按钮"""
    lines = ["📋 **任务列表**", "点击按钮领取未领取的任务。", ""]
    buttons = []

    for idx, task in enumerate(tasks, 1):
        unique = task.get("unique", "")
        name = task.get("name", "任务")
        desc = task.get("desc", "")
        target = task.get("target", 0)
        point = task.get("point", 0)
        process = task.get("process") or {}

        accepted = bool(process)
        is_finish = process.get("isFinish") == "Y" if process else False
        current = process.get("process", 0)
        process_target = process.get("target", target)

        if is_finish:
            status = "✅ 已完成"
        elif accepted:
            status = "📝 已领取"
        else:
            status = "⬜ 未领取"

        lines.append(f"{idx}. **{name}** (`{unique}`)")
        if desc:
            lines.append(f"   {desc}")
        if accepted and process_target:
            lines.append(f"   进度: {current}/{process_target}")
        elif not accepted and target:
            lines.append(f"   目标: {target}")
        if point is not None:
            lines.append(f"   奖励: {point}分")
        lines.append(f"   状态: {status}")
        lines.append("")

        if not accepted and unique:
            short_name = _truncate_text(name, 10)
            buttons.append([
                InlineKeyboardButton(f"领取 {short_name}", callback_data=f"accept:{unique}")
            ])

    if not buttons:
        lines.append("✅ 当前没有可领取的任务")

    message = "\n".join(lines).rstrip()
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    return message, keyboard

def _pick_next_movie(all_unlocked_movies, paid_movies, prefer_list=True):
    """选择一个可解锁电影，优先片单，找不到则使用推荐"""
    if prefer_list:
        page = 1
        max_pages = 10
        while page <= max_pages:
            movie_lists = get_movie_lists(page=page, sort="favorite_count")
            if not movie_lists:
                break
            for ml in movie_lists:
                list_id = ml.get("id")
                movie_id = find_unlocked_movie_from_list(list_id, all_unlocked_movies, paid_movies)
                if movie_id:
                    return movie_id, True, list_id
            page += 1

    movie_id = find_unlocked_movie_from_recommend(all_unlocked_movies, paid_movies)
    if movie_id:
        return movie_id, False, None
    return None, False, None

async def _execute_force_unlock(message, count):
    """执行强制批量解锁"""
    await message.reply_text(f"⏳ 正在强制解锁 {count} 部影片...")
    try:
        result = await asyncio.to_thread(unlock_movies_batch, count)
        successes = result["successes"]
        failure_msg = result.get("failure")

        if successes:
            lines = [f"✅ 强制解锁完成：成功 {len(successes)}/{count}"]
            show_count = min(10, len(successes))
            for idx, item in enumerate(successes[:show_count], 1):
                movie_id = item["movie_id"]
                source = (
                    f"片单{item.get('list_id')}"
                    if item.get("from_list")
                    else "推荐"
                )
                lines.append(f"{idx}. {movie_id} ({source})")
            if len(successes) > show_count:
                lines.append(f"... 还有 {len(successes) - show_count} 部未展示")
            await message.reply_text("\n".join(lines))

        if failure_msg:
            await message.reply_text(f"❌ 途中失败: {failure_msg}")
    except Exception as e:
        await message.reply_text(f"❌ 强制解锁失败: {str(e)}")

def _build_movie_caption(movie, detail=None):
    title = movie.get("title") if movie else ""
    movie_id = movie.get("id") if movie else ""
    release_date = movie.get("releaseDate") if movie else ""
    cover = movie.get("cover") if movie else ""
    if detail:
        title = detail.get("title", title)
        movie_id = detail.get("id", movie_id)
        release_date = detail.get("releaseDate", release_date)
        cover = detail.get("cover", cover)
    caption = f"{title}\nID: {movie_id}"
    if release_date:
        caption += f"\n上映: {release_date}"
    return caption, cover

async def _reply_with_cover(message, cover_url, caption, reply_markup=None):
    if cover_url:
        try:
            await message.reply_photo(photo=cover_url, caption=caption, reply_markup=reply_markup)
            return
        except Exception:
            pass
    await message.reply_text(caption, reply_markup=reply_markup)

def check_permission(func):
    """权限检查装饰器"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not check_user_permission(user_id):
            if update.message:
                await update.message.reply_text(
                    "❌ 您没有权限使用此机器人。\n"
                    "请联系管理员或使用 /setuser 命令添加您的用户ID。"
                )
            return
        return await func(update, context)
    return wrapper

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "用户"
    safe_username = _escape_markdown(username)

    welcome_msg = (
        f"👋 欢迎 {safe_username} 使用 Picix 积分最大化助手！\n\n"
        "📖 **可用命令：**\n"
        "`/status` - 查看当前状态\n"
        "`/unlock` - 执行每日解锁\n"
        "`/force_unlock` - 强制批量解锁\n"
        "`/tasks` - 查看任务列表/领取任务\n"
        "`/package` - 查看资源包信息\n"
        "`/shop` - 查看可购买商品\n"
        "`/search` - 搜索电影\n"
        "`/mylist` - 查看已购电影\n"
        "`/mysearch` - 搜索已购电影\n"
        "`/history` - 查看积分历史\n"
        "`/plan` - 查看积分最大化计划\n"
        "`/optimize` - 立即执行积分优化\n"
        "`/reauth` - 重新获取 Picix 登录指令\n"
        "`/help` - 显示帮助信息\n"
        "`/setuser` - 添加用户到允许列表\n\n"
        "💡 **策略说明：**\n"
        "复用未过期额度，并按任务截止期自动补量\n"
        "额度不足时按需购包；周期消费不足450分时购包替代罚扣\n\n"
        f"🆔 您的用户ID: `{user_id}`"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

@check_permission
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /status 命令"""
    await update.message.reply_text("⏳ 正在获取状态...")
    try:
        msg = format_status_message()
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ 获取状态失败: {str(e)}")

@check_permission
async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /tasks 命令 - 查看任务列表并领取"""
    await update.message.reply_text("⏳ 正在获取任务列表...")
    try:
        tasks = get_task_list()
        if not tasks:
            await update.message.reply_text("❌ 未获取到任务列表")
            return
        msg, keyboard = _build_tasks_message(tasks)
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        await update.message.reply_text(f"❌ 获取任务列表失败: {str(e)}")

@check_permission
async def package_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /package 命令"""
    await update.message.reply_text("⏳ 正在获取资源包信息...")
    try:
        packages = get_package_list()
        package = packages[0] if packages else None

        if not package:
            await update.message.reply_text("❌ 未找到资源包信息")
            return

        remaining = package.get("total", 0) - package.get("used", 0)
        expired_at = package.get("expiredAt", 0)

        msg = "📦 **资源包详情**\n\n"
        msg += "🔹 **当前使用包(第1个)**\n"
        msg += f"总次数: {package.get('total', 0)}\n"
        msg += f"已使用: {package.get('used', 0)}\n"
        msg += f"剩余次数: {remaining}\n"

        if expired_at:
            expired_date = datetime.fromtimestamp(expired_at)
            days_left = (expired_date - datetime.now()).days
            msg += f"过期时间: {expired_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
            msg += f"剩余天数: {days_left} 天\n"

        # 添加警告
        if remaining <= NOTIFICATION_THRESHOLD:
            msg += f"\n⚠️ **警告**: 剩余次数不足 {NOTIFICATION_THRESHOLD} 次，请及时购买资源包！"

        msg += "\n\n📦 **全部资源包明细**\n"
        for idx, pkg in enumerate(packages, 1):
            if not isinstance(pkg, dict):
                msg += f"{idx}. {pkg}\n"
                continue

            name = _first_value(pkg, ["name", "title", "goodsName", "goodName", "packageName"])
            pkg_id = _first_value(pkg, ["id", "goodId", "goodsId", "packageId"])
            total = _first_value(pkg, ["total", "count", "times", "quantity", "num", "quota"])
            used = _first_value(pkg, ["used", "usedCount", "usedTimes", "usedNum"])
            exp_at = _first_value(pkg, ["expiredAt", "expireAt", "expired_at", "expireTime", "expiredTime"])

            safe_name = _escape_markdown(name) if name else "资源包"
            header = f"{idx}. **{safe_name}**"
            msg += header + "\n"

            if pkg_id is not None:
                msg += f"   ID: `{pkg_id}`\n"
            if total is not None:
                msg += f"   总次数: {total}\n"
            if used is not None:
                msg += f"   已使用: {used}\n"
            if total is not None and used is not None:
                msg += f"   剩余次数: {total - used}\n"
            if exp_at:
                try:
                    exp_date = datetime.fromtimestamp(exp_at)
                    days_left = (exp_date - datetime.now()).days
                    msg += f"   过期时间: {exp_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    msg += f"   剩余天数: {days_left} 天\n"
                except Exception:
                    msg += f"   过期时间: {exp_at}\n"
            msg += "\n"

        await update.message.reply_text(msg.rstrip(), parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ 获取资源包信息失败: {str(e)}")

@check_permission
async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /shop 命令 - 查看可购买商品"""
    await update.message.reply_text("⏳ 正在获取可购买商品...")
    try:
        packages, _, _ = get_purchasable_packages()
        msg, keyboard = _build_shop_message(packages)
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        await update.message.reply_text(f"❌ 获取商品列表失败: {str(e)}")

@check_permission
async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /unlock 命令"""
    await update.message.reply_text("⏳ 正在执行解锁任务...")
    try:
        # 领取常用任务（避免未领取导致进度异常）
        accept_results = accept_default_tasks()
        failed_accepts = [
            u for u, info in accept_results.items()
            if info.get("status") == "failed"
        ]
        if failed_accepts:
            await update.message.reply_text(
                f"⚠️ 任务领取失败: {', '.join(failed_accepts)}\n"
                "将继续尝试解锁，如有异常请检查任务页。"
            )

        # 检查资源包
        package = get_package_info()
        if package:
            remaining = package.get("total", 0) - package.get("used", 0)
            if remaining <= 0:
                await update.message.reply_text("❌ 资源包已用完，请先购买资源包！")
                return

        # 分析任务状态
        tasks = analyze_tasks()
        if not tasks:
            await update.message.reply_text("❌ 无法获取任务状态")
            return

        # 检查每日任务是否已完成（仅提示，不阻止继续解锁）
        daily_task = tasks.get("D_UL_1")
        daily_task_completed = daily_task and daily_task["is_finish"]

        if daily_task_completed:
            # 检查月常任务是否还需要解锁
            monthly_task = tasks.get("M_UL_50")
            if monthly_task and not monthly_task["is_finish"]:
                # 每日任务已完成，但月常任务未完成，允许继续解锁
                await update.message.reply_text(
                    "✅ 今日每日任务已完成\n"
                    "📋 但月常任务未完成，继续解锁以完成月常任务..."
                )
            else:
                # 所有任务都完成了
                await update.message.reply_text("✅ 今日每日任务已完成，所有任务已完成！")
                return

        # 获取解锁记录
        log = get_unlock_log()
        unlocked_movies = set(log["unlocked_movies"])

        # 获取服务器端的已解锁电影列表（避免重复解锁）
        await update.message.reply_text("⏳ 正在获取服务器端的已解锁电影列表...")
        from auto_unlock_helper import get_all_paid_movies
        paid_movies = get_all_paid_movies()

        # 合并本地和服务器端的已解锁列表
        all_unlocked_movies = unlocked_movies | paid_movies

        # 获取月度统计
        current_month = datetime.now().strftime("%Y-%m")
        monthly_stats = log["monthly_stats"].get(current_month, {
            "total": 0,
            "from_list": 0,
            "list_ids": []
        })

        # 每日解锁策略：片单任务完成后不再从片单获取
        movie_id = None
        from_list = False
        list_id = None
        use_list = should_unlock_from_list(tasks)

        if use_list:
            # 从片单列表中查找未解锁的电影（遍历所有片单，直到找到未解锁的）
            page = 1
            max_pages = 10  # 最多检查10页，避免无限循环
            while not movie_id and page <= max_pages:
                movie_lists = get_movie_lists(page=page, sort="favorite_count")
                if not movie_lists:  # 没有更多片单了
                    break

                for ml in movie_lists:
                    list_id = ml.get("id")
                    movie_id = find_unlocked_movie_from_list(list_id, all_unlocked_movies, paid_movies)
                    if movie_id:
                        from_list = True
                        break

                if movie_id:
                    break
                page += 1
        else:
            await update.message.reply_text("✅ 片单任务已完成，改从推荐列表解锁...")

        # 如果所有片单都找完了还没找到，再从推荐列表选择（作为最后备选）
        if not movie_id:
            movie_id = find_unlocked_movie_from_recommend(all_unlocked_movies, paid_movies)

        if not movie_id:
            await update.message.reply_text("❌ 未找到可解锁的电影")
            return

        # 执行解锁
        source = f"片单{list_id}" if from_list else "推荐"
        await update.message.reply_text(f"🔓 正在解锁电影 ID: {movie_id} (来源: {source})...")

        success, error_msg = unlock_movie(movie_id, list_id=list_id if from_list else None)

        if success:
            save_unlock_record(movie_id, from_list, list_id)
            time.sleep(1)  # 等待服务器更新

            # 更新任务状态
            tasks = analyze_tasks()
            if tasks:
                msg = "✅ **解锁成功！**\n\n**更新后的任务进度：**\n"
                for unique, info in tasks.items():
                    status_icon = "✅" if info["is_finish"] else "⏳"
                    msg += f"{status_icon} {info['name']}: {info['current']}/{info['target']}\n"
                await update.message.reply_text(msg, parse_mode='Markdown')
            else:
                await update.message.reply_text("✅ 解锁成功！")
        else:
            # 显示详细的错误信息
            error_detail = error_msg if error_msg else "未知错误"
            msg = f"❌ **解锁失败**\n\n{error_detail}\n\n**请检查：**\n• 资源包是否还有剩余次数\n• 网络连接是否正常\n• 电影ID是否有效"
            await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ 执行解锁失败: {str(e)}")

@check_permission
async def force_unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /force_unlock 命令 - 强制批量解锁"""
    count = 1
    if context.args:
        try:
            count = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ 参数错误，请使用 /force_unlock 3")
            return

    if count <= 0:
        await update.message.reply_text("❌ 参数必须是正整数")
        return

    if count > 1:
        msg = f"⚠️ 将强制解锁 {count} 部影片，可能会消耗 {count} 次资源包次数，是否继续？"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 确认", callback_data=f"forceunlock:{count}"),
                InlineKeyboardButton("❌ 取消", callback_data="forceunlock_cancel")
            ]
        ])
        await update.message.reply_text(msg, reply_markup=keyboard)
        return

    await _execute_force_unlock(update.message, count)

@check_permission
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /search 命令 - 搜索电影"""
    if not context.args:
        await update.message.reply_text("❌ 请提供搜索关键词，例如：/search SONE-333")
        return
    args = context.args
    page = 0
    if len(args) >= 2 and args[-1].isdigit():
        page = int(args[-1])
        keyword = " ".join(args[:-1])
    else:
        keyword = " ".join(args)

    await update.message.reply_text(f"🔎 正在搜索：{keyword} (第 {page} 页)...")
    results = search_movies(keyword, page=page)
    if not results:
        await update.message.reply_text("❌ 未找到相关电影")
        return

    paid_movies = get_all_paid_movies()
    if len(results) == 1:
        movie = results[0]
        movie_id = movie.get("id")
        caption, cover = _build_movie_caption(movie)
        buttons = []
        if movie_id in paid_movies:
            buttons.append([InlineKeyboardButton("直链", callback_data=f"play:{movie_id}")])
        else:
            buttons.append([InlineKeyboardButton("购买", callback_data=f"buy:{movie_id}")])
        buttons.append([InlineKeyboardButton("详情", callback_data=f"info:{movie_id}")])
        await _reply_with_cover(update.message, cover, caption, InlineKeyboardMarkup(buttons))
        return

    msg_lines = [f"🔎 搜索结果：{keyword} (第 {page} 页)"]
    buttons = []
    for idx, movie in enumerate(results, 1):
        title = _truncate_text(movie.get("title", ""))
        movie_id = movie.get("id")
        msg_lines.append(f"{idx}. {title} (ID: {movie_id})")
        if movie_id in paid_movies:
            buttons.append([
                InlineKeyboardButton(f"#{idx} 直链", callback_data=f"play:{movie_id}"),
                InlineKeyboardButton("详情", callback_data=f"info:{movie_id}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(f"#{idx} 购买", callback_data=f"buy:{movie_id}"),
                InlineKeyboardButton("详情", callback_data=f"info:{movie_id}")
            ])
    await update.message.reply_text("\n".join(msg_lines), reply_markup=InlineKeyboardMarkup(buttons))

@check_permission
async def mylist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /mylist 命令 - 已购电影列表"""
    page = 1
    if context.args and context.args[0].isdigit():
        page = int(context.args[0])
    await update.message.reply_text(f"📚 正在获取已购电影 (第 {page} 页)...")
    movies = get_paid_movies(page=page)
    if not movies:
        await update.message.reply_text("❌ 未找到已购电影")
        return

    msg_lines = [f"📚 已购电影 (第 {page} 页)"]
    buttons = []
    for idx, movie in enumerate(movies, 1):
        title = _truncate_text(movie.get("title", ""))
        movie_id = movie.get("id")
        msg_lines.append(f"{idx}. {title} (ID: {movie_id})")
        buttons.append([
            InlineKeyboardButton(f"#{idx} 详情", callback_data=f"info:{movie_id}"),
            InlineKeyboardButton("直链", callback_data=f"play:{movie_id}")
        ])
    await update.message.reply_text("\n".join(msg_lines), reply_markup=InlineKeyboardMarkup(buttons))

@check_permission
async def mysearch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /mysearch 命令 - 已购电影中搜索"""
    if not context.args:
        await update.message.reply_text("❌ 请提供搜索关键词，例如：/mysearch SONE")
        return
    keyword = " ".join(context.args).lower()
    await update.message.reply_text(f"🔎 正在已购电影中搜索：{keyword} ...")

    results = []
    max_pages = 5
    for page in range(1, max_pages + 1):
        movies = get_paid_movies(page=page)
        if not movies:
            break
        for movie in movies:
            title = movie.get("title", "")
            if keyword in title.lower():
                results.append(movie)
        if len(movies) < 20:
            break

    if not results:
        await update.message.reply_text("❌ 未找到已购电影")
        return

    if len(results) == 1:
        movie = results[0]
        movie_id = movie.get("id")
        caption, cover = _build_movie_caption(movie)
        buttons = [
            [InlineKeyboardButton("直链", callback_data=f"play:{movie_id}")],
            [InlineKeyboardButton("详情", callback_data=f"info:{movie_id}")]
        ]
        await _reply_with_cover(update.message, cover, caption, InlineKeyboardMarkup(buttons))
        return

    msg_lines = [f"🔎 已购搜索结果：{keyword}"]
    buttons = []
    for idx, movie in enumerate(results, 1):
        title = _truncate_text(movie.get("title", ""))
        movie_id = movie.get("id")
        msg_lines.append(f"{idx}. {title} (ID: {movie_id})")
        buttons.append([
            InlineKeyboardButton(f"#{idx} 详情", callback_data=f"info:{movie_id}"),
            InlineKeyboardButton("直链", callback_data=f"play:{movie_id}")
        ])
    await update.message.reply_text("\n".join(msg_lines), reply_markup=InlineKeyboardMarkup(buttons))

async def handle_movie_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调（购买/详情/直链/商店/批量解锁）"""
    query = update.callback_query
    if not query:
        return

    user_id = query.from_user.id
    if not check_user_permission(user_id):
        await query.answer("无权限", show_alert=True)
        await query.message.reply_text("❌ 您没有权限使用此机器人。")
        return

    data = query.data or ""
    if data.startswith("accept:"):
        unique = data.split(":", 1)[1]
        success, msg = accept_task(unique)
        if success:
            await query.answer("领取成功")
        else:
            await query.answer("领取失败", show_alert=True)

        tasks = get_task_list()
        if tasks:
            text, keyboard = _build_tasks_message(tasks)
            try:
                await query.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
            except Exception:
                await query.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
        else:
            await query.message.reply_text("❌ 无法获取任务列表")

        if not success and msg:
            await query.message.reply_text(f"❌ 领取任务失败: {msg}")
        return

    if data.startswith("shopbuy:"):
        await query.answer()
        good_id = data.split(":", 1)[1]
        packages, _, _ = get_purchasable_packages()
        pkg = _find_package_by_good_id(packages, good_id)
        text, keyboard = _build_shop_confirm_message(good_id, pkg)
        await query.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
        return

    if data.startswith("shopconfirm:"):
        await query.answer()
        good_id = data.split(":", 1)[1]
        success, msg = buy_package(good_id)
        if success:
            detail_msg = f"✅ 购买成功: {msg}" if msg else "✅ 购买成功"
            await query.message.reply_text(detail_msg)
        else:
            await query.message.reply_text(f"❌ 购买失败: {msg or '未知错误'}")
        return

    if data.startswith("shopcancel:"):
        await query.answer("已取消")
        await query.message.reply_text("✅ 已取消购买")
        return

    if data.startswith("forceunlock:"):
        await query.answer()
        try:
            count = int(data.split(":", 1)[1])
        except ValueError:
            await query.message.reply_text("❌ 无效的解锁数量")
            return
        await _execute_force_unlock(query.message, count)
        return

    if data == "forceunlock_cancel":
        await query.answer("已取消")
        await query.message.reply_text("✅ 已取消批量解锁")
        return

    await query.answer()

    try:
        action, movie_id_str = data.split(":", 1)
        movie_id = int(movie_id_str)
    except ValueError:
        await query.message.reply_text("❌ 无效操作")
        return

    if action == "buy":
        success, error_msg = unlock_movie(movie_id, list_id=None)
        if not success:
            await query.message.reply_text(f"❌ 购买失败: {error_msg or '未知错误'}")
            return
        detail = get_movie_detail(movie_id)
        caption, cover = _build_movie_caption({"id": movie_id}, detail)
        stream = _extract_stream_link(detail)
        buttons = []
        if stream:
            buttons.append([InlineKeyboardButton("直链", callback_data=f"play:{movie_id}")])
        await _reply_with_cover(query.message, cover, f"✅ 购买成功\n{caption}", InlineKeyboardMarkup(buttons) if buttons else None)
        if stream:
            await query.message.reply_text(f"直链: {stream}")
        return

    if action == "info":
        detail = get_movie_detail(movie_id)
        if not detail:
            await query.message.reply_text("❌ 获取详情失败")
            return
        caption, cover = _build_movie_caption({"id": movie_id}, detail)
        stream = _extract_stream_link(detail)
        buttons = []
        if stream:
            buttons.append([InlineKeyboardButton("直链", callback_data=f"play:{movie_id}")])
        else:
            buttons.append([InlineKeyboardButton("购买", callback_data=f"buy:{movie_id}")])
        await _reply_with_cover(query.message, cover, caption, InlineKeyboardMarkup(buttons))
        return

    if action == "play":
        detail = get_movie_detail(movie_id)
        stream = _extract_stream_link(detail)
        if not stream:
            await query.message.reply_text("❌ 未解锁，无法获取直链")
            return
        await query.message.reply_text(f"直链: {stream}")
        return

    await query.message.reply_text("❌ 未知操作")

@check_permission
async def point_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /history 或 /points 命令 - 显示积分历史"""
    await update.message.reply_text("⏳ 正在获取积分历史...")
    try:
        history = get_point_history()

        if not history:
            await update.message.reply_text("❌ 未找到积分历史记录")
            return

        # 获取当前积分（第一条记录）
        current_points = history[0].get("totalPoints", 0) if history else 0

        # 构建消息
        msg = f"💰 **积分历史**\n\n"
        msg += f"当前积分: **{current_points}** 分\n\n"
        msg += "**最近记录：**\n"

        # 显示最近10条记录
        for i, record in enumerate(history[:10], 1):
            timestamp = record.get("timestamp", 0)
            record_type = record.get("type", "")
            value = record.get("value", 0)
            desc = record.get("desc", "")
            total_points = record.get("totalPoints", 0)

            # 格式化时间
            if timestamp:
                record_time = datetime.fromtimestamp(timestamp)
                time_str = record_time.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = "未知时间"

            # 类型图标
            type_icon = "➕" if record_type == "INC" else "➖"
            type_text = "增加" if record_type == "INC" else "减少"

            msg += f"{i}. {type_icon} {type_text} {value} 分\n"
            msg += f"   {desc}\n"
            msg += f"   余额: {total_points} 分 | {time_str}\n\n"

        if len(history) > 10:
            msg += f"... 共 {len(history)} 条记录（仅显示最近10条）"

        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ 获取积分历史失败: {str(e)}")


@check_permission
async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示计划，不执行购买或解锁。"""
    await update.message.reply_text("⏳ 正在计算积分最大化计划...")
    try:
        plan = await asyncio.to_thread(
            build_live_optimization_plan,
            **_optimizer_options(),
        )
        await update.message.reply_text(
            format_optimization_plan(plan),
            parse_mode="Markdown",
        )
    except Exception as error:
        await update.message.reply_text(f"❌ 生成计划失败: {error}")


@check_permission
async def optimize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """立即执行一次与定时任务相同的积分优化流程。"""
    await update.message.reply_text("⏳ 正在执行积分最大化方案...")
    try:
        report = await asyncio.to_thread(
            execute_points_optimization,
            **_execution_options(),
        )
        await update.message.reply_text(
            format_optimization_report(report),
            parse_mode="Markdown",
        )
    except Exception as error:
        await update.message.reply_text(f"❌ 自动优化失败: {error}")


@check_permission
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    help_msg = (
        "📖 **命令列表**\n\n"
        "`/start` - 开始使用机器人\n"
        "`/status` - 查看当前状态（任务进度、统计、收益）\n"
        "`/unlock` - 执行每日解锁任务\n"
        "`/force_unlock` - 强制批量解锁\n"
        "`/tasks` - 查看任务列表/领取任务\n"
        "`/package` - 查看资源包详情\n"
        "`/shop` - 查看可购买商品\n"
        "`/search` - 搜索电影\n"
        "`/mylist` - 查看已购电影\n"
        "`/mysearch` - 搜索已购电影\n"
        "`/history` - 查看积分历史记录\n"
        "`/plan` - 查看计划但不执行\n"
        "`/optimize` - 立即执行积分最大化方案\n"
        "`/reauth` - 重新获取 Picix 登录指令\n"
        "`/setuser` - 添加用户到允许列表\n"
        "`/help` - 显示此帮助信息\n\n"
        "💡 **使用提示**\n"
        "• 自动优化开启时无需手动计算购包数量\n"
        "• 定期使用 `/status` 查看进度\n"
        "• `/force_unlock` 3 可批量解锁（数量>1需确认）\n"
        "• 当剩余次数不足时会自动通知\n\n"
        "📊 **策略说明**\n"
        "优先复用有效额度，无法靠日更完成任务时自动补量\n"
        "滚动周期消费不足450分时，在兜底日前按需购买轻量包"
    )
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def auto_points_optimizer(context: ContextTypes.DEFAULT_TYPE):
    """定时执行积分最大化计划，并只在有动作或异常时通知。"""
    try:
        report = await asyncio.to_thread(
            execute_points_optimization,
            **_execution_options(),
        )
        purchases = report.get("purchases") or []
        unlock_result = report.get("unlock_result") or {}
        has_action = bool(purchases or unlock_result.get("successes"))
        has_warning = bool(report.get("messages") or unlock_result.get("failure"))
        if not has_action and not has_warning:
            print("自动积分优化：当前无需动作")
            return

        config = load_json_file(CONFIG_FILE, {})
        user_ids = config.get("user_ids", ALLOWED_USER_IDS)
        message = format_optimization_report(report)
        for user_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="Markdown",
                )
            except Exception as error:
                print(f"发送自动优化通知失败 (用户 {user_id}): {error}")
    except Exception as error:
        print(f"自动积分优化异常: {error}")


async def auto_daily_unlock(context: ContextTypes.DEFAULT_TYPE):
    """自动执行每日解锁任务"""
    try:
        # 领取常用任务（避免未领取导致进度异常）
        accept_results = accept_default_tasks()
        failed_accepts = [
            u for u, info in accept_results.items()
            if info.get("status") == "failed"
        ]
        if failed_accepts:
            print(f"自动解锁：任务领取失败 {', '.join(failed_accepts)}")

        # 分析任务状态
        tasks = analyze_tasks()
        if not tasks:
            print("自动解锁：无法获取任务状态")
            return

        # 检查每日任务是否已完成
        daily_task = tasks.get("D_UL_1")
        if not daily_task:
            print("自动解锁：未找到每日任务")
            return

        if daily_task["is_finish"]:
            print("自动解锁：今日每日任务已完成，无需解锁")
            return

        # 检查资源包
        package = get_package_info()
        if package:
            remaining = package.get("total", 0) - package.get("used", 0)
            if remaining <= 0:
                print("自动解锁：资源包已用完，无法执行")
                # 发送通知
                config = load_json_file(CONFIG_FILE, {})
                user_ids = config.get("user_ids", ALLOWED_USER_IDS)
                if user_ids:
                    msg = "⚠️ **自动解锁失败**\n\n资源包已用完，请先购买资源包！"
                    for user_id in user_ids:
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=msg,
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            print(f"发送通知失败 (用户 {user_id}): {e}")
                return

        # 执行解锁逻辑（复用 unlock 函数的逻辑）
        log = get_unlock_log()
        unlocked_movies = set(log["unlocked_movies"])

        # 获取服务器端的已解锁电影列表（避免重复解锁）
        print("自动解锁：正在获取服务器端的已解锁电影列表...")
        paid_movies = get_all_paid_movies()
        print(f"自动解锁：服务器端已解锁电影数: {len(paid_movies)}")

        # 合并本地和服务器端的已解锁列表
        all_unlocked_movies = unlocked_movies | paid_movies
        print(f"自动解锁：总计已解锁电影数: {len(all_unlocked_movies)}")

        current_month = datetime.now().strftime("%Y-%m")
        monthly_stats = log["monthly_stats"].get(current_month, {
            "total": 0,
            "from_list": 0,
            "list_ids": []
        })

        # 片单任务完成后不再从片单获取
        movie_id = None
        from_list = False
        list_id = None
        use_list = should_unlock_from_list(tasks)

        if use_list:
            page = 1
            max_pages = 10
            while not movie_id and page <= max_pages:
                movie_lists = get_movie_lists(page=page, sort="favorite_count")
                if not movie_lists:
                    break

                for ml in movie_lists:
                    list_id = ml.get("id")
                    movie_id = find_unlocked_movie_from_list(list_id, all_unlocked_movies, paid_movies)
                    if movie_id:
                        from_list = True
                        break

                if movie_id:
                    break
                page += 1
        else:
            print("自动解锁：片单任务已完成，跳过片单解锁")

        # 如果片单中没找到，从推荐列表选择
        if not movie_id:
            movie_id = find_unlocked_movie_from_recommend(all_unlocked_movies, paid_movies)

        if not movie_id:
            print("自动解锁：未找到可解锁的电影")
            return

        # 执行解锁
        if from_list and list_id:
            print(f"自动解锁：正在解锁电影 ID: {movie_id} (来自片单: {list_id})")
            success, error_msg = unlock_movie(movie_id, list_id=list_id)
        else:
            print(f"自动解锁：正在解锁电影 ID: {movie_id} (来自推荐列表)")
            success, error_msg = unlock_movie(movie_id, list_id=None)

        if success:
            save_unlock_record(movie_id, from_list, list_id)
            print(f"自动解锁：成功解锁电影 {movie_id}")

            # 发送成功通知
            config = load_json_file(CONFIG_FILE, {})
            user_ids = config.get("user_ids", ALLOWED_USER_IDS)
            if user_ids:
                source = f"片单{list_id}" if from_list else "推荐"
                msg = f"✅ **自动解锁成功**\n\n已解锁电影 ID: {movie_id}\n来源: {source}"

                # 更新任务状态
                time.sleep(1)
                tasks = analyze_tasks()
                if tasks:
                    msg += "\n\n**当前任务进度：**\n"
                    for unique, info in tasks.items():
                        status_icon = "✅" if info["is_finish"] else "⏳"
                        msg += f"{status_icon} {info['name']}: {info['current']}/{info['target']}\n"

                for user_id in user_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=msg,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        print(f"发送通知失败 (用户 {user_id}): {e}")
        else:
            print(f"自动解锁：解锁失败")
            if error_msg:
                print(f"错误详情: {error_msg}")

            # 发送失败通知
            config = load_json_file(CONFIG_FILE, {})
            user_ids = config.get("user_ids", ALLOWED_USER_IDS)
            if user_ids:
                error_detail = error_msg if error_msg else "未知错误"
                msg = f"❌ **自动解锁失败**\n\n{error_detail}\n\n请稍后手动执行 /unlock"
                for user_id in user_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=msg,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        print(f"发送通知失败 (用户 {user_id}): {e}")
    except Exception as e:
        print(f"自动解锁异常: {e}")

async def keep_alive_request(context: ContextTypes.DEFAULT_TYPE):
    """保活请求：定期获取片单列表，保持连接活跃"""
    try:
        # 获取片单列表（简单的保活请求）
        movie_lists = get_movie_lists(page=1, sort="favorite_count")
        if movie_lists:
            print(f"保活请求成功：获取到 {len(movie_lists)} 个片单")
        else:
            print("保活请求：未获取到片单数据")
    except Exception as e:
        print(f"保活请求异常: {e}")


async def _send_auth_message(context, user_ids, text, reply_markup=None):
    """向认证通知目标发送消息，单个用户失败不影响其他用户。"""
    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        except Exception as error:
            print(f"发送认证消息失败 (用户 {user_id}): {error}")


async def run_reauth_flow(context, user_ids, force=False):
    """发送动态登录指令并等待 Picix 返回新的 authorization。"""
    if AUTH_REAUTH_LOCK.locked():
        return False, "已有认证流程正在等待用户操作"

    auth_log = load_json_file(AUTH_NOTIFICATION_LOG, {})
    now = int(time.time())
    last_attempt = auth_log.get("last_attempt", {})
    last_timestamp = int(last_attempt.get("timestamp", 0) or 0)
    if not force and now - last_timestamp < AUTH_REAUTH_COOLDOWN_SECONDS:
        return False, "认证通知仍在冷却时间内"

    async with AUTH_REAUTH_LOCK:
        auth_log["last_attempt"] = {
            "timestamp": now,
            "status": "requesting_code",
        }
        save_json_file(AUTH_NOTIFICATION_LOG, auth_log)

        code, error = await asyncio.to_thread(request_login_code)
        if not code:
            msg = (
                "🚨 **Picix 认证已失效**\n\n"
                f"暂时无法生成 Telegram 登录指令：{_escape_markdown(error or '未知错误')}\n"
                "请稍后发送 `/reauth` 重试。"
            )
            await _send_auth_message(context, user_ids, msg)
            auth_log["last_attempt"]["status"] = "code_failed"
            save_json_file(AUTH_NOTIFICATION_LOG, auth_log)
            return False, error or "无法获取登录码"

        login_command = f"/login {code}"
        auth_bot_url = f"https://t.me/{AUTH_BOT_USERNAME}?start=login_{code}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"打开 @{AUTH_BOT_USERNAME}",
                url=auth_bot_url,
            )
        ]])
        msg = (
            "🚨 **Picix 认证已失效**\n\n"
            f"请复制下面一整行，发送给 **@{AUTH_BOT_USERNAME}**：\n\n"
            f"`{login_command}`\n\n"
            "也可以点击下方按钮直接打开官方认证 Bot。\n"
            "完成认证后，本机器人会自动保存新 authorization，无需修改源码或重启。\n\n"
            "⚠️ 登录码只用于本次认证，请勿转发给其他人。"
        )
        await _send_auth_message(context, user_ids, msg, reply_markup=keyboard)

        auth_log["last_attempt"] = {
            "timestamp": now,
            "status": "waiting",
        }
        save_json_file(AUTH_NOTIFICATION_LOG, auth_log)

        deadline = time.monotonic() + AUTH_REAUTH_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            token, poll_error = await asyncio.to_thread(check_login_code, code)
            if token:
                saved = await asyncio.to_thread(update_authorization, token)
                restored = saved and await asyncio.to_thread(check_auth_valid)
                if restored:
                    success_msg = (
                        "✅ **Picix 认证已恢复**\n\n"
                        "新的 authorization 已自动保存并立即生效，"
                        "自动解锁与定时任务已恢复。"
                    )
                    await _send_auth_message(context, user_ids, success_msg)
                    auth_log["last_attempt"] = {
                        "timestamp": int(time.time()),
                        "status": "success",
                    }
                    auth_log["last_success"] = {
                        "timestamp": int(time.time()),
                    }
                    save_json_file(AUTH_NOTIFICATION_LOG, auth_log)
                    return True, ""

                failure_msg = (
                    "⚠️ 已收到新的 authorization，但有效性检查未通过。\n"
                    "请稍后发送 `/reauth` 重新尝试。"
                )
                await _send_auth_message(context, user_ids, failure_msg)
                auth_log["last_attempt"]["status"] = "validation_failed"
                save_json_file(AUTH_NOTIFICATION_LOG, auth_log)
                return False, "新 authorization 验证失败"

            await asyncio.sleep(2)

        timeout_msg = (
            "⌛ **Picix 登录等待超时**\n\n"
            "本次登录码可能已过期；需要时发送 `/reauth` 获取新指令。"
        )
        await _send_auth_message(context, user_ids, timeout_msg)
        auth_log["last_attempt"]["status"] = "timeout"
        save_json_file(AUTH_NOTIFICATION_LOG, auth_log)
        return False, "等待登录超时"


@check_permission
async def reauth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """手动生成新的 Picix Telegram 登录指令。"""
    config = load_json_file(CONFIG_FILE, {})
    configured_user_ids = config.get("user_ids", ALLOWED_USER_IDS)
    if not configured_user_ids or update.effective_user.id not in configured_user_ids:
        await update.message.reply_text(
            "❌ `/reauth` 只允许已明确加入允许列表的用户使用。",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("⏳ 正在生成 Picix 登录指令...")
    ok, message = await run_reauth_flow(
        context,
        [update.effective_user.id],
        force=True,
    )
    if not ok and message == "已有认证流程正在等待用户操作":
        await update.message.reply_text(f"ℹ️ {message}")


async def check_auth_and_notify(context: ContextTypes.DEFAULT_TYPE):
    """定时检查认证状态；失效时启动 Telegram 动态登录流程。"""
    try:
        is_valid = await asyncio.to_thread(check_auth_valid)

        if not is_valid:
            config = load_json_file(CONFIG_FILE, {})
            user_ids = config.get("user_ids", ALLOWED_USER_IDS)

            if user_ids:
                ok, message = await run_reauth_flow(context, user_ids)
                if not ok:
                    print(f"认证续期流程未完成: {message}")
            else:
                print("认证失效：未找到用户列表，无法发送通知")
        else:
            print("认证检查：认证有效")
    except Exception as e:
        print(f"认证检查异常: {e}")
        import traceback
        print(traceback.format_exc())

async def check_package_and_notify(context: ContextTypes.DEFAULT_TYPE):
    """定时检查资源包并发送通知"""
    summary = get_package_summary()
    remaining = summary["remaining"]

    # 检查是否需要通知
    if remaining <= NOTIFICATION_THRESHOLD:
        # 检查是否已经通知过（避免重复通知）
        notification_log = load_json_file(NOTIFICATION_LOG, {})
        last_notification = notification_log.get("last_notification", {})

        today = datetime.now().strftime("%Y-%m-%d")
        last_date = last_notification.get("date")
        last_remaining = last_notification.get("remaining")

        # 如果今天已经通知过，且剩余次数没有变化，则不重复通知
        if last_date == today and last_remaining == remaining:
            return

        # 发送通知
        msg = f"⚠️ **资源包提醒**\n\n"
        msg += f"全部有效包总剩余: {remaining} 次\n"
        msg += (
            f"剩余次数不足 {NOTIFICATION_THRESHOLD} 次；"
            "自动优化器会在需要解锁时按计划购包。\n\n"
        )

        expired_at = (
            summary["active"][0].get("expired_at")
            if summary["active"]
            else None
        )
        if expired_at:
            expired_date = datetime.fromtimestamp(expired_at)
            days_left = (expired_date - datetime.now()).days
            msg += f"过期时间: {expired_date.strftime('%Y-%m-%d %H:%M')}\n"
            msg += f"剩余天数: {days_left} 天"

        # 获取所有允许的用户ID
        config = load_json_file(CONFIG_FILE, {})
        user_ids = config.get("user_ids", ALLOWED_USER_IDS)

        if not user_ids:
            # 如果没有配置用户ID，记录日志但不发送
            print(f"需要通知但未配置用户ID: {msg}")
            return

        for user_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"发送通知失败 (用户 {user_id}): {e}")

        # 记录通知日志
        notification_log["last_notification"] = {
            "date": today,
            "remaining": remaining,
            "timestamp": int(time.time())
        }
        save_json_file(NOTIFICATION_LOG, notification_log)

def load_config():
    """加载配置"""
    config = load_json_file(CONFIG_FILE, {})
    return config

def save_config(config):
    """保存配置"""
    save_json_file(CONFIG_FILE, config)

async def set_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """首次初始化允许用户；已有列表时禁止陌生人自助加入。"""
    user_id = update.effective_user.id
    config = load_config()

    if "user_ids" not in config:
        config["user_ids"] = []

    configured_ids = config["user_ids"]
    bootstrap_ids = ALLOWED_USER_IDS or configured_ids
    if bootstrap_ids and user_id not in bootstrap_ids:
        await update.message.reply_text("❌ 允许列表已初始化，您无权自行加入。")
        return

    if user_id not in config["user_ids"]:
        config["user_ids"].append(user_id)
        save_config(config)
        await update.message.reply_text(f"✅ 已添加用户 ID: {user_id}")
    else:
        await update.message.reply_text(f"ℹ️ 用户 ID: {user_id} 已在列表中")

def check_user_permission(user_id):
    """检查用户权限"""
    config = load_config()
    user_ids = config.get("user_ids") or list(ALLOWED_USER_IDS)
    if not user_ids:
        return False
    return user_id in user_ids

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """错误处理"""
    print(f"Update {update} caused error {context.error}")
    if update and update.message:
        try:
            await update.message.reply_text("❌ 发生错误，请稍后重试")
        except:
            pass

def main():
    """主函数"""
    if not settings.is_configured:
        print("❌ 请先配置 BOT_TOKEN！")
        print("1. 在 Telegram 中找到 @BotFather")
        print("2. 发送 /newbot 创建新机器人")
        print("3. 将 Token 写入 config.py，或设置 PICIX_BOT_TOKEN 环境变量")
        return

    # 创建应用
    application = Application.builder().token(BOT_TOKEN).build()

    # 设置 Bot 命令菜单（在应用启动后执行）
    async def post_init(app: Application) -> None:
        """应用初始化后执行"""
        commands = [
            BotCommand("start", "开始使用机器人"),
            BotCommand("status", "查看当前状态"),
            BotCommand("unlock", "执行每日解锁"),
            BotCommand("force_unlock", "强制批量解锁"),
            BotCommand("tasks", "查看任务列表/领取任务"),
            BotCommand("package", "查看资源包信息"),
            BotCommand("shop", "查看可购买商品"),
            BotCommand("search", "搜索电影"),
            BotCommand("mylist", "查看已购电影"),
            BotCommand("mysearch", "搜索已购电影"),
            BotCommand("history", "查看积分历史"),
            BotCommand("plan", "查看积分最大化计划"),
            BotCommand("optimize", "立即执行积分优化"),
            BotCommand("reauth", "重新获取 Picix 登录指令"),
            BotCommand("help", "显示帮助信息"),
            BotCommand("setuser", "添加用户到允许列表")
        ]
        await app.bot.set_my_commands(commands)
        print("✅ Bot 命令菜单已设置")

    application.post_init = post_init

    # 添加命令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("unlock", unlock))
    application.add_handler(CommandHandler("force_unlock", force_unlock_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("package", package_info))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("mylist", mylist_command))
    application.add_handler(CommandHandler("mysearch", mysearch_command))
    application.add_handler(CommandHandler("history", point_history_command))
    application.add_handler(CommandHandler("points", point_history_command))  # 别名
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("optimize", optimize_command))
    application.add_handler(CommandHandler("reauth", reauth_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setuser", set_user))
    application.add_handler(CallbackQueryHandler(handle_movie_action))

    # 添加错误处理
    application.add_error_handler(error_handler)

    # 设置定时任务
    job_queue = application.job_queue
    if job_queue:
        # 每30分钟发送一次保活请求（获取片单）
        job_queue.run_repeating(
            keep_alive_request,
            interval=1800,  # 每30分钟（1800秒）执行一次
            first=60  # 1分钟后开始第一次执行
        )
        print("💓 保活任务已设置：每30分钟执行一次")

        # 每小时检查一次资源包
        job_queue.run_repeating(
            check_package_and_notify,
            interval=CHECK_INTERVAL,
            first=120  # 2分钟后开始第一次检查（避免与保活任务冲突）
        )

        # 每小时检查一次认证状态
        job_queue.run_repeating(
            check_auth_and_notify,
            interval=CHECK_INTERVAL,
            first=180  # 3分钟后开始第一次检查
        )
        print(f"🔐 认证检查任务已设置：每 {CHECK_INTERVAL} 秒检查一次")

        # 每天定时检查低消、任务期限和资源包，并执行最优动作。
        if AUTO_UNLOCK_HOUR is not None:
            # 计算到指定时间的秒数
            now = datetime.now()
            target_time = now.replace(hour=AUTO_UNLOCK_HOUR, minute=AUTO_UNLOCK_MINUTE, second=0, microsecond=0)
            if now >= target_time:
                # 如果已经过了今天的目标时间，设置为明天
                target_time += timedelta(days=1)

            seconds_until_target = (target_time - now).total_seconds()

            scheduled_callback = (
                auto_points_optimizer
                if settings.auto_optimize
                else auto_daily_unlock
            )
            job_queue.run_repeating(
                scheduled_callback,
                interval=86400,  # 每24小时执行一次
                first=int(seconds_until_target)  # 在目标时间首次执行
            )

            mode = "积分优化" if settings.auto_optimize else "每日解锁"
            print(f"⏰ 自动{mode}任务已设置：每天 {target_time.strftime('%H:%M')} 执行")
        else:
            # 如果未设置时间，每小时检查一次（更频繁，确保不会漏掉）
            scheduled_callback = (
                auto_points_optimizer
                if settings.auto_optimize
                else auto_daily_unlock
            )
            job_queue.run_repeating(
                scheduled_callback,
                interval=3600,  # 每小时检查一次
                first=300  # 5分钟后开始第一次检查
            )
            mode = "积分优化" if settings.auto_optimize else "每日解锁"
            print(f"⏰ 自动{mode}任务已设置：每小时检查一次")

    print("🤖 机器人已启动！")
    print("使用 /start 命令开始使用")

    # 启动机器人
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
