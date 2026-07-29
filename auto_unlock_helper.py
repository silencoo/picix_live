"""Picix 自动解锁与积分优化助手。"""
import requests
import sys
import io
import json
import logging
import os
from logging.handlers import RotatingFileHandler
import time
from datetime import datetime, timedelta
from pathlib import Path

from picix_bot.optimizer import build_optimization_plan, summarize_packages

# 设置标准输出为UTF-8编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 配置：源码不保存凭证。环境变量用于部署，自动续期结果保存在本地状态文件。
AUTHORIZATION = os.getenv("PICIX_AUTHORIZATION", "").strip()
BASE_URL = "https://picix.us/api"
DATA_DIR = Path(__file__).parent / "unlock_data"
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "api_log.log"
AUTHORIZATION_FILE = DATA_DIR / "authorization.json"

# 优先使用自动续期后持久化的 authorization。
try:
    if AUTHORIZATION_FILE.exists():
        with open(AUTHORIZATION_FILE, "r", encoding="utf-8") as auth_file:
            stored_auth = json.load(auth_file).get("authorization")
        if stored_auth:
            AUTHORIZATION = str(stored_auth).strip()
except Exception as auth_load_error:
    print(f"加载持久化 authorization 失败，将使用源码配置: {auth_load_error}")

# 日志配置：记录所有请求与响应
logger = logging.getLogger("picix_api")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# 数据文件
UNLOCK_LOG_FILE = DATA_DIR / "unlock_log.json"
STATUS_FILE = DATA_DIR / "status.json"

# 通用请求头
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "authorization": AUTHORIZATION,
    "dnt": "1",
    "priority": "u=1, i",
    "referer": "https://picix.us/Subscribe/Movie",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-arch": '"x86"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version": '"146.0.7680.178"',
    "sec-ch-ua-full-version-list": '"Chromium";v="146.0.7680.178", "Not-A.Brand";v="24.0.0.0", "Google Chrome";v="146.0.7680.178"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"19.0.0"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
}

def load_json_file(filepath, default=None):
    """加载JSON文件"""
    if default is None:
        default = {}
    try:
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"加载文件失败 {filepath}: {e}")
    return default

def save_json_file(filepath, data):
    """保存JSON文件"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存文件失败 {filepath}: {e}")
        return False


def update_authorization(token):
    """更新运行时 authorization 并持久化，后续重启自动加载。"""
    global AUTHORIZATION

    normalized = str(token or "").strip()
    if not normalized or any(char.isspace() for char in normalized):
        return False

    AUTHORIZATION = normalized
    HEADERS["authorization"] = normalized
    return save_json_file(
        AUTHORIZATION_FILE,
        {
            "authorization": normalized,
            "updated_at": int(time.time()),
        },
    )


def _login_request_headers():
    """登录码接口不应携带已经失效的 authorization。"""
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": HEADERS.get("accept-language", "zh-CN,zh;q=0.9"),
        "referer": "https://picix.us/Users/Login?uri=%2FDashs",
        "user-agent": HEADERS.get("user-agent", "Mozilla/5.0"),
    }


def request_login_code():
    """请求一次新的 Picix Telegram 登录码。"""
    try:
        response = requests.get(
            f"{BASE_URL}/Users/getLoginCode",
            headers=_login_request_headers(),
            timeout=20,
        )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        code = data.get("code") if isinstance(data, dict) else None
        if response.status_code == 200 and payload.get("success") and code:
            return str(code), ""
        return None, payload.get("msg", f"HTTP {response.status_code}")
    except Exception as error:
        return None, str(error)


def check_login_code(code):
    """检查用户是否已在 @vStreamingBot 完成认证；成功时返回新 token。"""
    try:
        headers = _login_request_headers()
        headers["content-type"] = "application/json"
        headers["origin"] = "https://picix.us"
        response = requests.post(
            f"{BASE_URL}/Users/checkLoginCode",
            headers=headers,
            json={"code": str(code)},
            timeout=20,
        )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        token = data.get("token") if isinstance(data, dict) else None
        if response.status_code == 200 and payload.get("success") and token:
            return str(token), ""
        # 未认证时接口可能返回 success=false；这是正常轮询状态。
        return None, payload.get("msg", "")
    except Exception as error:
        return None, str(error)


def api_request(method, endpoint, data=None, params=None):
    """发送API请求"""
    url = f"{BASE_URL}{endpoint}"
    try:
        try:
            logger.info(
                "REQUEST | method=%s url=%s params=%s data=%s",
                method.upper(),
                url,
                json.dumps(params, ensure_ascii=False) if params is not None else None,
                json.dumps(data, ensure_ascii=False) if data is not None else None
            )
        except Exception as log_error:
            print(f"日志记录请求失败: {log_error}")

        if method.upper() == "GET":
            response = requests.get(url, headers=HEADERS, params=params)
        elif method.upper() == "POST":
            headers = HEADERS.copy()
            headers["content-type"] = "application/json"
            headers["origin"] = "https://picix.us"
            response = requests.post(url, headers=headers, json=data)
        else:
            return None

        try:
            logger.info(
                "RESPONSE | method=%s url=%s status=%s body=%s",
                method.upper(),
                url,
                response.status_code,
                response.text
            )
        except Exception as log_error:
            print(f"日志记录响应失败: {log_error}")

        # 尝试解析JSON响应
        try:
            result = response.json()
        except ValueError:
            # 如果不是JSON，返回原始文本
            print(f"警告: API返回非JSON响应: {response.text[:200]}")
            return None

        if response.status_code == 200:
            return result
        elif response.status_code == 401:
            # 认证失效
            print(f"⚠️ 认证失效: HTTP 401 Unauthorized")
            print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else response.text}")
            # 标记认证失效
            result = result if result else {}
            result["_auth_failed"] = True
            return result
        elif response.status_code == 403:
            # 认证被拒绝
            print(f"⚠️ 认证被拒绝: HTTP 403 Forbidden")
            print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else response.text}")
            result = result if result else {}
            result["_auth_failed"] = True
            return result
        else:
            print(f"API请求失败: HTTP {response.status_code}")
            print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else response.text}")
            return result  # 即使状态码不是200，也返回解析后的结果，让调用者处理
    except Exception as e:
        print(f"请求异常: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return None

def get_task_list():
    """获取任务列表"""
    result = api_request("GET", "/Tasks/list")
    if result and result.get("success"):
        return result.get("data", [])
    return []

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

def get_movie_lists(page=1, sort="favorite_count"):
    """获取片单列表"""
    params = {"page": page, "sort": sort}
    result = api_request("GET", "/Movies/listMovieList", params=params)
    if result and result.get("success"):
        return result.get("data", [])
    return []

def get_movie_list_detail(list_id):
    """获取片单详情"""
    params = {"listId": list_id}
    result = api_request("GET", "/Movies/getMovieList", params=params)
    if result and result.get("success"):
        return result.get("data", {})
    return {}

def unlock_movie(movie_id, list_id=None):
    """解锁电影
    Args:
        movie_id: 电影ID
        list_id: 片单ID，如果从片单解锁则传递片单ID，如果从推荐列表解锁则传递None或0
    """
    # 确保 movieId 是整数类型
    try:
        movie_id = int(movie_id) if movie_id else None
    except (ValueError, TypeError):
        print(f"错误: 无法将 movie_id 转换为整数: {movie_id}")
        return False

    if not movie_id:
        print(f"错误: 无效的 movie_id: {movie_id}")
        return False

    # 构建请求数据
    data = {
        "movieId": movie_id
    }

    # 如果提供了片单ID，则添加到请求中
    # 根据 curl 示例，fromMovieList 应该是字符串格式的片单ID
    if list_id:
        try:
            list_id_int = int(list_id) if list_id else None
            if list_id_int:
                data["fromMovieList"] = str(list_id_int)  # 使用字符串格式（与 curl 示例一致）
        except (ValueError, TypeError):
            print(f"警告: 无法将 list_id 转换为整数: {list_id}，将不传递 fromMovieList 参数")

    # 调试信息：打印实际发送的 payload
    print(f"调试: 解锁请求 payload: {json.dumps(data, ensure_ascii=False)}")
    if list_id:
        print(f"调试: 从片单解锁，片单ID: {list_id}")
    else:
        print(f"调试: 从推荐列表解锁")

    result = api_request("POST", "/Movies/unlock", data=data)
    if result:
        if result.get("success"):
            print(f"调试: 解锁成功，响应: {result.get('msg', '无消息')}")
            return (True, None)
        else:
            error_msg = result.get('msg', '未知错误')
            error_detail = json.dumps(result, ensure_ascii=False, indent=2)
            print(f"调试: 解锁失败，API返回: {error_msg}")
            print(f"调试: 完整响应: {error_detail}")
            return (False, f"API错误: {error_msg}\n\n完整响应:\n{error_detail}")
    else:
        error_msg = "API请求返回 None（可能是网络错误或服务器错误）"
        print(f"调试: 解锁失败，{error_msg}")
        return (False, error_msg)

def get_recommend_movies():
    """获取推荐电影列表"""
    result = api_request("GET", "/Movies/listRecommend")
    if result and result.get("success"):
        return result.get("data", [])
    return []

def search_movies(keyword, page=0):
    """搜索电影"""
    params = {"keyword": keyword, "page": page}
    result = api_request("GET", "/Movies/search", params=params)
    if result and result.get("success"):
        return result.get("data", [])
    return []

def get_movie_detail(movie_id):
    """获取电影详情（已解锁可返回播放链接）"""
    params = {"movieId": movie_id}
    result = api_request("GET", "/Movies/detail", params=params)
    if result and result.get("success"):
        return result.get("data", {})
    return {}

def get_point_history():
    """获取积分历史记录"""
    result = api_request("GET", "/Users/listPointHistory")
    if result and result.get("success"):
        return result.get("data", [])
    return []

def get_paid_movies(page=1):
    """获取已购买/已解锁的电影列表（从服务器端）"""
    params = {"page": page, "type": "movies"}
    result = api_request("GET", "/Users/listPaidResouces", params=params)
    if result and result.get("success"):
        return result.get("data", [])
    return []

def get_all_paid_movies():
    """获取所有已购买/已解锁的电影ID集合（从服务器端）"""
    paid_movie_ids = set()
    page = 1
    max_pages = 10  # 最多检查10页，避免无限循环

    while page <= max_pages:
        movies = get_paid_movies(page=page)
        if not movies:  # 没有更多电影了
            break

        for movie in movies:
            movie_id = movie.get("id")
            if movie_id:
                paid_movie_ids.add(movie_id)

        # 如果返回的电影数量少于预期，可能已经到最后一页了
        if len(movies) < 20:  # 假设每页20个（可以根据实际情况调整）
            break

        page += 1

    return paid_movie_ids

def check_auth_valid():
    """检查认证是否有效"""
    # 使用一个简单的API来检查认证状态
    result = api_request("GET", "/Tasks/list")
    if result:
        # 检查是否有认证失败标记
        if result.get("_auth_failed"):
            return False
        # 如果返回成功，说明认证有效
        if result.get("success"):
            return True
        # 如果返回失败但不是认证问题，也认为认证有效
        return True
    return False

def get_package_info():
    """获取最早到期的可用资源包，兼容旧调用方。"""
    packages = get_package_list()
    _, active = summarize_packages(packages, now=datetime.now().astimezone())
    if active:
        return active[0]["raw"]
    return None

def get_package_list():
    """获取个人资源包列表"""
    result = api_request("GET", "/Packages/listMine")
    if result and result.get("success"):
        packages = result.get("data", [])
        if isinstance(packages, list):
            return packages
    return []


def get_package_summary():
    """汇总所有未过期资源包，避免只读取第一包导致误购。"""
    packages = get_package_list()
    remaining, active = summarize_packages(
        packages,
        now=datetime.now().astimezone(),
    )
    return {
        "remaining": remaining,
        "active": active,
        "all": packages,
    }

def _first_value(data, keys, default=None):
    """从字典中取第一个非空值"""
    for key in keys:
        if key in data:
            value = data.get(key)
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            return value
    return default

def _extract_package_items(data):
    """从接口 data 中抽取资源包列表"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 处理分类列表（如 package / inviteCode / redeemCode）
        grouped_items = []
        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item = dict(item)
                        item.setdefault("_category", key)
                    grouped_items.append(item)
        if grouped_items:
            return grouped_items
        for key in ("list", "items", "rows", "data", "goods", "packages"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        # 如果 data 本身就是一个资源包对象
        if any(k in data for k in ("goodId", "goodsId", "id", "name", "title")):
            return [data]
    return []

def get_purchasable_packages():
    """获取可购买资源包列表"""
    endpoints = [
        ("/Malls/listGoods", None),
        ("/Malls/listGoods", {"type": "package"}),
        ("/Malls/listGoods", {"type": "packages"}),
        ("/Packages/list", None),
        ("/Packages/listAll", None),
    ]
    for endpoint, params in endpoints:
        result = api_request("GET", endpoint, params=params)
        if not result:
            continue
        if result.get("success"):
            data = result.get("data")
            items = _extract_package_items(data)
            if items or data == []:
                return items, endpoint, params
    return [], None, None

def show_purchasable_packages():
    """显示可购买资源包"""
    print("=" * 60)
    print("可购买资源包")
    print("=" * 60)

    packages, endpoint, params = get_purchasable_packages()

    if endpoint:
        if params:
            print(f"接口: {endpoint} | 参数: {json.dumps(params, ensure_ascii=False)}")
        else:
            print(f"接口: {endpoint}")

    if not packages:
        print("未找到可购买资源包（接口可能已变化或账号权限不足）")
        return

    for idx, pkg in enumerate(packages, 1):
        name = _first_value(pkg, ["name", "title", "goodsName", "goodName", "packageName"])
        desc = _first_value(pkg, ["desc", "description", "remark", "note"])
        good_id = _first_value(pkg, ["goodId", "goodsId", "id"])
        price = _first_value(pkg, ["price", "point", "points", "amount", "cost", "coin"])
        total = _first_value(pkg, ["total", "count", "times", "quantity", "num", "quota"])
        status = _first_value(pkg, ["status", "state", "isEnable", "enabled"])

        header = f"{idx}. {name}" if name else f"{idx}. 资源包"
        if good_id is not None:
            header += f" (ID: {good_id})"
        print(f"\n{header}")

        if desc:
            print(f"  说明: {desc}")
        if price is not None:
            print(f"  价格/积分: {price}")
        if total is not None:
            print(f"  次数: {total}")
        if status is not None:
            print(f"  状态: {status}")

def find_purchasable_package(good_id):
    """查找指定商品，并返回可用于购买前校验的标准字段。"""
    packages, endpoint, params = get_purchasable_packages()
    expected_id = str(good_id)
    for package in packages:
        actual_id = _first_value(package, ["goodId", "goodsId", "id"])
        if actual_id is None or str(actual_id) != expected_id:
            continue
        return {
            "good_id": str(actual_id),
            "price": _first_value(
                package, ["price", "point", "points", "amount", "cost", "coin"]
            ),
            "quota": _first_value(
                package, ["total", "count", "times", "quantity", "num", "quota"]
            ),
            "name": _first_value(
                package,
                ["name", "title", "goodsName", "goodName", "packageName"],
            ),
            "endpoint": endpoint,
            "params": params,
            "raw": package,
        }
    return None


def validate_purchasable_package(good_id, expected_price, expected_quota):
    """购买前核对商品 ID、价格和次数，防止接口变化造成误扣。"""
    package = find_purchasable_package(good_id)
    if not package:
        return False, "商城中未找到配置的轻量包，已禁止自动购买", None

    price = package.get("price")
    quota = package.get("quota")
    if price is None or quota is None:
        return (
            False,
            "商城未返回可校验的价格或次数，已禁止自动购买",
            package,
        )
    try:
        if int(price) != int(expected_price):
            return (
                False,
                f"轻量包价格已变化（接口 {price}，配置 {expected_price}）",
                package,
            )
        if int(quota) != int(expected_quota):
            return (
                False,
                f"轻量包次数已变化（接口 {quota}，配置 {expected_quota}）",
                package,
            )
    except (TypeError, ValueError):
        return False, "商城返回的价格或次数无法识别", package
    return True, "", package


def buy_lightweight_package(good_id="1"):
    """购买轻量包。调用前应先执行商品参数校验。"""
    print("正在购买轻量包...")
    data = {"goodId": str(good_id)}
    result = api_request("POST", "/Malls/payGood", data=data)
    if result:
        if result.get("success"):
            print(f"✓ 购买成功: {result.get('msg', '无消息')}")
            return True, result.get("msg")
        else:
            error_msg = result.get('msg', '未知错误')
            print(f"✗ 购买失败: {error_msg}")
            return False, error_msg
    return False, "请求失败"

def ensure_package_and_unlock():
    """确保有资源包可用并执行解锁"""
    print("=" * 60)
    print(f"自动购买并解锁 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 检查资源包状态
    package = get_package_info()
    need_buy = False

    if package:
        total = package.get("total", 0)
        used = package.get("used", 0)
        remaining = total - used
        print(f"当前资源包: 总计 {total} / 已用 {used} / 剩余 {remaining}")

        if remaining <= 0:
            print("⚠️ 资源包已用完，需要购买")
            need_buy = True
        else:
            print("✓ 资源包充足，无需购买")
    else:
        print("⚠️ 未找到资源包信息，尝试购买")
        need_buy = True

    # 2. 如果需要，执行购买
    if need_buy:
        success, msg = buy_lightweight_package()
        if not success:
            print(f"❌ 无法购买资源包，终止流程: {msg}")
            return False

        # 购买成功后，稍作等待并重新检查（可选）
        time.sleep(2)
        package = get_package_info()
        if package:
            print(f"购买后状态: 剩余 {package.get('total', 0) - package.get('used', 0)}")

    # 3. 执行每日解锁
    return daily_unlock()


def analyze_tasks():
    """分析任务状态"""
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

def get_unlock_log():
    """获取解锁记录"""
    return load_json_file(UNLOCK_LOG_FILE, {
        "unlocked_movies": [],
        "daily_unlocks": {},
        "monthly_stats": {}
    })

def save_unlock_record(movie_id, from_list, list_id=None):
    """保存解锁记录"""
    log = get_unlock_log()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = datetime.now().strftime("%Y-%m")

    # 记录已解锁的电影
    if movie_id not in log["unlocked_movies"]:
        log["unlocked_movies"].append(movie_id)

    # 记录每日解锁
    if today not in log["daily_unlocks"]:
        log["daily_unlocks"][today] = []
    log["daily_unlocks"][today].append({
        "movie_id": movie_id,
        "from_list": from_list,
        "list_id": list_id,
        "timestamp": int(time.time())
    })

    # 记录月度统计
    if current_month not in log["monthly_stats"]:
        log["monthly_stats"][current_month] = {
            "total": 0,
            "from_list": 0,
            "list_ids": set()
        }

    stats = log["monthly_stats"][current_month]
    stats["total"] += 1
    if from_list:
        stats["from_list"] += 1
        if list_id:
            if isinstance(stats["list_ids"], list):
                stats["list_ids"] = set(stats["list_ids"])
            stats["list_ids"].add(list_id)

    # 转换set为list以便JSON序列化
    if isinstance(stats["list_ids"], set):
        stats["list_ids"] = list(stats["list_ids"])

    save_json_file(UNLOCK_LOG_FILE, log)
    return log

def find_unlocked_movie_from_list(list_id, unlocked_movies, paid_movies=None):
    """从片单中找到一个未解锁的电影
    Args:
        list_id: 片单ID
        unlocked_movies: 本地记录的已解锁电影集合
        paid_movies: 服务器端的已购买电影集合（可选，如果为None则自动获取）
    """
    if paid_movies is None:
        paid_movies = get_all_paid_movies()

    detail = get_movie_list_detail(list_id)
    if not detail:
        return None

    movie_list = detail.get("list", [])
    for movie in movie_list:
        movie_id = movie.get("id")
        # 同时检查本地记录和服务器端的已解锁列表
        if movie_id and movie_id not in unlocked_movies and movie_id not in paid_movies:
            return movie_id
    return None

def find_unlocked_movie_from_recommend(unlocked_movies, paid_movies=None):
    """从推荐列表中找到未解锁的电影
    Args:
        unlocked_movies: 本地记录的已解锁电影集合
        paid_movies: 服务器端的已购买电影集合（可选，如果为None则自动获取）
    """
    if paid_movies is None:
        paid_movies = get_all_paid_movies()

    recommend = get_recommend_movies()
    for movie in recommend:
        movie_id = movie.get("id")
        # 同时检查本地记录和服务器端的已解锁列表
        if movie_id and movie_id not in unlocked_movies and movie_id not in paid_movies:
            return movie_id
    return None


def pick_next_movie(all_unlocked_movies, paid_movies, prefer_list=True):
    """选择一个未解锁影片；片单任务未完成时优先从片单选择。"""
    if prefer_list:
        page = 1
        while page <= 10:
            movie_lists = get_movie_lists(page=page, sort="favorite_count")
            if not movie_lists:
                break
            for movie_list in movie_lists:
                list_id = movie_list.get("id")
                movie_id = find_unlocked_movie_from_list(
                    list_id,
                    all_unlocked_movies,
                    paid_movies,
                )
                if movie_id:
                    return movie_id, True, list_id
            page += 1

    movie_id = find_unlocked_movie_from_recommend(
        all_unlocked_movies,
        paid_movies,
    )
    if movie_id:
        return movie_id, False, None
    return None, False, None


def unlock_movies_batch(count, *, prefer_list=True):
    """批量解锁并返回结构化结果，供手动命令和自动优化共用。"""
    requested = max(0, int(count))
    summary = get_package_summary()
    available = summary["remaining"]
    target = min(requested, available)
    result = {
        "requested": requested,
        "attempted": target,
        "successes": [],
        "failure": None,
        "available_before": available,
    }
    if target <= 0:
        result["failure"] = "没有可用的资源包次数"
        return result

    tasks = analyze_tasks() or {}
    list_task = tasks.get("M_UL_ML_20") or {}
    list_remaining = max(
        0,
        int(list_task.get("target") or 0) - int(list_task.get("current") or 0),
    )
    if list_task.get("is_finish"):
        list_remaining = 0

    log = get_unlock_log()
    unlocked_movies = set(log["unlocked_movies"])
    paid_movies = get_all_paid_movies()
    all_unlocked_movies = unlocked_movies | paid_movies

    for _ in range(target):
        use_list = prefer_list and list_remaining > 0
        movie_id, from_list, list_id = pick_next_movie(
            all_unlocked_movies,
            paid_movies,
            use_list,
        )
        if not movie_id:
            result["failure"] = "未找到可解锁的电影"
            break

        success, error_msg = unlock_movie(
            movie_id,
            list_id=list_id if from_list else None,
        )
        if not success:
            result["failure"] = error_msg or "未知错误"
            break

        save_unlock_record(movie_id, from_list, list_id)
        all_unlocked_movies.add(movie_id)
        paid_movies.add(movie_id)
        if from_list:
            list_remaining = max(0, list_remaining - 1)
        result["successes"].append(
            {
                "movie_id": movie_id,
                "from_list": from_list,
                "list_id": list_id,
            }
        )
        time.sleep(0.8)

    return result


def build_live_optimization_plan(**options):
    """读取实时状态并生成积分优化计划。"""
    return build_optimization_plan(
        history=get_point_history(),
        packages=get_package_list(),
        tasks=analyze_tasks() or {},
        **options,
    )


def execute_points_optimization(
    *,
    allow_purchase=True,
    timezone_name="Asia/Shanghai",
    minimum_spend=450,
    package_good_id="1",
    package_price=450,
    package_quota=30,
    spend_trigger_day=25,
    points_reserve=0,
    max_auto_purchases=2,
    max_auto_unlocks=50,
    spend_cycle_days=30,
):
    """执行一次按余额、低消和任务期限生成的积分最大化计划。"""
    options = {
        "timezone_name": timezone_name,
        "minimum_spend": minimum_spend,
        "package_price": package_price,
        "package_quota": package_quota,
        "spend_trigger_day": spend_trigger_day,
        "points_reserve": points_reserve,
        "max_auto_purchases": max_auto_purchases,
        "max_auto_unlocks": max_auto_unlocks,
        "spend_cycle_days": spend_cycle_days,
    }
    report = {
        "success": False,
        "plan": None,
        "purchases": [],
        "unlock_result": None,
        "messages": [],
    }

    accept_results = accept_default_tasks()
    failed_accepts = [
        unique
        for unique, info in accept_results.items()
        if info.get("status") == "failed"
    ]
    if failed_accepts:
        report["messages"].append(
            f"以下任务领取失败：{', '.join(failed_accepts)}"
        )

    tasks = analyze_tasks()
    history = get_point_history()
    if not tasks or not history:
        report["messages"].append("无法读取任务或积分状态，请检查登录状态")
        return report

    plan = build_optimization_plan(
        history=history,
        packages=get_package_list(),
        tasks=tasks,
        **options,
    )
    report["plan"] = plan.to_dict()
    report["messages"].extend(plan.blocked_reasons)

    if plan.packages_to_buy and not allow_purchase:
        report["messages"].append(
            f"计划需要购买 {plan.packages_to_buy} 个轻量包，但自动购买已关闭"
        )
    elif plan.packages_to_buy:
        valid, reason, package = validate_purchasable_package(
            package_good_id,
            package_price,
            package_quota,
        )
        if not valid:
            report["messages"].append(reason)
            return report

        package_name = package.get("name") or f"商品 {package_good_id}"
        for _ in range(plan.packages_to_buy):
            success, message = buy_lightweight_package(package_good_id)
            report["purchases"].append(
                {
                    "success": success,
                    "message": message,
                    "good_id": str(package_good_id),
                    "name": package_name,
                    "price": package_price,
                }
            )
            if not success:
                report["messages"].append(f"购买失败：{message}")
                break
            time.sleep(1)

    # 必须从资源包接口确认额度已到账，避免无包时退化为20分直购影片。
    verified_quota = get_package_summary()["remaining"]
    unlock_count = min(plan.unlocks_now, verified_quota)
    if plan.unlocks_now > unlock_count:
        report["messages"].append(
            f"计划解锁 {plan.unlocks_now} 部，但已确认额度仅 {verified_quota} 次"
        )

    if unlock_count:
        report["unlock_result"] = unlock_movies_batch(
            unlock_count,
            prefer_list=plan.list_remaining > 0,
        )

    successful_purchases = sum(
        1 for purchase in report["purchases"] if purchase["success"]
    )
    successful_unlocks = len(
        (report["unlock_result"] or {}).get("successes", [])
    )
    report["success"] = (
        not report["messages"]
        or successful_purchases > 0
        or successful_unlocks > 0
        or (plan.unlocks_now == 0 and plan.packages_to_buy == 0)
    )
    return report


def daily_unlock():
    """执行每日解锁任务"""
    print("=" * 60)
    print(f"每日解锁任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 领取常用任务（避免未领取导致进度异常）
    accept_results = accept_default_tasks()
    for unique, info in accept_results.items():
        if info["status"] == "skipped":
            print(f"✓ 任务已存在 {unique}: {info['msg']}")
        elif info["success"]:
            print(f"✓ 已领取任务 {unique}: {info['msg']}")
        else:
            if info["msg"]:
                print(f"⚠️ 任务 {unique} 领取失败: {info['msg']}")

    # 分析任务状态
    tasks = analyze_tasks()
    if not tasks:
        print("无法获取任务状态，退出")
        return False

    # 显示任务进度
    print("\n当前任务进度:")
    for unique, info in tasks.items():
        status = "✓ 已完成" if info["is_finish"] else "进行中"
        print(f"  {info['name']}: {info['current']}/{info['target']} ({status}) - {info['point']}分")

    # 检查每日任务是否已完成
    daily_task = tasks.get("D_UL_1")
    if daily_task and daily_task["is_finish"]:
        print("\n✓ 今日每日任务已完成，无需解锁")
        return True

    # 获取解锁记录
    log = get_unlock_log()
    unlocked_movies = set(log["unlocked_movies"])

    # 获取服务器端的已解锁电影列表（避免重复解锁）
    print("\n正在获取服务器端的已解锁电影列表...")
    paid_movies = get_all_paid_movies()
    print(f"  服务器端已解锁电影数: {len(paid_movies)}")

    # 合并本地和服务器端的已解锁列表
    all_unlocked_movies = unlocked_movies | paid_movies
    print(f"  总计已解锁电影数: {len(all_unlocked_movies)} (本地: {len(unlocked_movies)}, 服务器: {len(paid_movies)})")

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
        # 遍历所有片单，直到找到未解锁的电影
        page = 1
        max_pages = 10  # 最多检查10页，避免无限循环
        print(f"\n正在从片单中查找未解锁的电影... (当前片单解锁: {monthly_stats['from_list']}/20)")

        while not movie_id and page <= max_pages:
            movie_lists = get_movie_lists(page=page, sort="favorite_count")
            if not movie_lists:  # 没有更多片单了
                break

            for ml in movie_lists:
                list_id = ml.get("id")
                movie_id = find_unlocked_movie_from_list(list_id, all_unlocked_movies, paid_movies)
                if movie_id:
                    from_list = True
                    print(f"  找到片单: {ml.get('title')} (ID: {list_id})")
                    break

            if movie_id:
                break
            page += 1
    else:
        print("\n片单任务已完成，跳过片单解锁，改从推荐列表获取...")

    # 如果没找到，从推荐列表选择
    if not movie_id:
        print(f"\n从推荐列表中查找未解锁的电影...")
        movie_id = find_unlocked_movie_from_recommend(all_unlocked_movies, paid_movies)
        if movie_id:
            print(f"  找到推荐电影: {movie_id}")

    if not movie_id:
        print("\n✗ 未找到可解锁的电影")
        return False

    # 执行解锁
    if from_list and list_id:
        print(f"\n正在解锁电影 ID: {movie_id} (来自片单: {list_id})")
        success, error_msg = unlock_movie(movie_id, list_id=list_id)
    else:
        print(f"\n正在解锁电影 ID: {movie_id} (来自推荐列表)")
        success, error_msg = unlock_movie(movie_id, list_id=None)

    if success:
        print("✓ 解锁成功！")
        save_unlock_record(movie_id, from_list, list_id)

        # 更新任务状态
        time.sleep(1)  # 等待服务器更新
        tasks = analyze_tasks()
        if tasks:
            print("\n更新后的任务进度:")
            for unique, info in tasks.items():
                status = "✓ 已完成" if info["is_finish"] else "进行中"
                print(f"  {info['name']}: {info['current']}/{info['target']} ({status})")

        return True
    else:
        print("✗ 解锁失败")
        if error_msg:
            print(f"错误详情: {error_msg}")
        return False

def show_status():
    """显示当前状态"""
    print("=" * 60)
    print("当前状态")
    print("=" * 60)

    # 任务状态
    tasks = analyze_tasks()
    if tasks:
        print("\n任务进度:")
        for unique, info in tasks.items():
            status = "✓ 已完成" if info["is_finish"] else "进行中"
            progress = info['current'] / info['target'] * 100 if info['target'] > 0 else 0
            print(f"  {info['name']}: {info['current']}/{info['target']} ({progress:.1f}%) - {status}")
            if info['point']:
                print(f"    奖励: {info['point']}分")

    # 解锁记录
    log = get_unlock_log()
    current_month = datetime.now().strftime("%Y-%m")
    monthly_stats = log["monthly_stats"].get(current_month, {
        "total": 0,
        "from_list": 0,
        "list_ids": []
    })

    print(f"\n本月统计 ({current_month}):")
    print(f"  总解锁数: {monthly_stats['total']}/50")
    print(f"  片单解锁数: {monthly_stats['from_list']}/20")
    print(f"  已解锁电影总数: {len(log['unlocked_movies'])}")

    # 计算预计收益
    if tasks:
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

        print(f"\n收益预估:")
        print(f"  已获得: {earned} 分")
        print(f"  待获得: {potential} 分")
        print(f"  任务奖励上限: {earned + potential} 分")
        print("  月任务奖励仅在达到门槛后计入")

    # 今日解锁
    today = datetime.now().strftime("%Y-%m-%d")
    today_unlocks = log["daily_unlocks"].get(today, [])
    print(f"\n今日解锁 ({today}): {len(today_unlocks)} 个")
    if today_unlocks:
        for unlock in today_unlocks[-5:]:  # 显示最近5个
            source = f"片单{unlock.get('list_id')}" if unlock.get('from_list') else "推荐"
            print(f"  - 电影ID: {unlock['movie_id']} (来源: {source})")

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Picix 积分最大化自动化助手")
    parser.add_argument(
        "action",
        choices=["unlock", "status", "plan", "optimize", "auto_buy", "packages"],
        help=(
            "操作: unlock=每日解锁, status=查看状态, plan=仅生成优化计划, "
            "optimize=执行积分优化, packages=查看商品"
        ),
    )
    args = parser.parse_args()

    if args.action == "unlock":
        daily_unlock()
    elif args.action == "status":
        show_status()
    elif args.action in {"plan", "optimize"}:
        from picix_bot.settings import settings

        options = {
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
        if args.action == "plan":
            plan = build_live_optimization_plan(**options)
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        else:
            report = execute_points_optimization(
                **options,
                allow_purchase=settings.auto_purchase,
                package_good_id=settings.package_good_id,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.action == "auto_buy":
        ensure_package_and_unlock()
    elif args.action == "packages":
        show_purchasable_packages()

if __name__ == "__main__":
    main()
