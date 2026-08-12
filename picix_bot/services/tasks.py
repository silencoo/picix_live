"""Task retrieval, acceptance, and normalized progress."""
from __future__ import annotations

from picix_bot.api.client import _get_list_api_state, api_request


def get_task_state():
    return _get_list_api_state("/Tasks/list", "任务")


def get_task_list():
    """获取任务列表；兼容旧调用方，关键决策应改用 get_task_state。"""
    state = get_task_state()
    return state["items"] if state["available"] else []


def accept_task(unique):
    """领取任务"""
    data = {"unique": unique}
    result = api_request("POST", "/Tasks/accept", data=data)
    if result and result.get("success"):
        return True, result.get("msg", "")
    if result:
        return False, result.get("msg", "")
    return False, "请求失败"


def accept_default_tasks():
    """确保常用任务已领取"""
    task_uniques = ["D_UL_1", "M_UL_50", "M_UL_ML_20"]
    results = {}
    # 先读取当前任务列表，避免重复领取
    current_tasks = get_task_list()
    # 建立映射: unique -> task object
    current_tasks_map = {t.get("unique"): t for t in current_tasks if t.get("unique")}

    for unique in task_uniques:
        should_accept = True

        if unique in current_tasks_map:
            task = current_tasks_map[unique]
            # 检查是否有进度信息 (通常已领取的任务会有 process 字段)
            # 如果 process 存在且不为空，则认为已领取
            process = task.get("process")
            if process:
                results[unique] = {"success": True, "msg": "已存在(有进度)", "status": "skipped"}
                should_accept = False
            else:
                print(f"调试: 任务 {unique} 在列表中但无进度信息，尝试重新领取...")

        if should_accept:
            ok, msg = accept_task(unique)
            results[unique] = {"success": ok, "msg": msg, "status": "accepted" if ok else "failed"}

    return results


def analyze_tasks(tasks=None):
    """分析任务状态"""
    if tasks is None:
        tasks = get_task_list()
    if not tasks:
        print("无法获取任务列表")
        return None

    task_info = {}
    for task in tasks:
        unique = task.get("unique")
        process = task.get("process", {})
        task_info[unique] = {
            "name": task.get("name"),
            "desc": task.get("desc"),
            "target": task.get("target"),
            "point": task.get("point"),
            "current": process.get("process", 0),
            "is_finish": process.get("isFinish") == "Y",
            "end_at": process.get("endAt")
        }

    return task_info


def should_unlock_from_list(tasks):
    """判断是否需要继续从片单解锁（片单任务完成则跳过）"""
    if not tasks:
        return True
    list_task = tasks.get("M_UL_ML_20")
    if list_task and list_task.get("is_finish"):
        return False
    return True
