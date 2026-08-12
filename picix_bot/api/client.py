"""Picix HTTP client, authentication persistence, and failure classification."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time

import requests

BASE_URL = "https://picix.us/api"
DATA_DIR = Path(__file__).resolve().parents[2] / "unlock_data"
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "api_log.log"
AUTHORIZATION_FILE = DATA_DIR / "authorization.json"
REQUEST_TIMEOUT_SECONDS = 20

AUTHORIZATION = os.getenv("PICIX_AUTHORIZATION", "").strip()
try:
    if AUTHORIZATION_FILE.exists():
        stored_auth = json.loads(AUTHORIZATION_FILE.read_text(encoding="utf-8")).get("authorization")
        if stored_auth:
            AUTHORIZATION = str(stored_auth).strip()
except Exception as error:
    print(f"加载持久化 authorization 失败，将使用环境变量配置: {error}")

logger = logging.getLogger("picix_api")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)

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
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}


def _api_failure(result, fallback="Picix API 暂时不可用"):
    """Return a user-facing error when an API response is not trustworthy."""
    if result is None:
        return {
            "available": False,
            "auth_failed": False,
            "retryable": True,
            "error": fallback,
        }
    if not isinstance(result, dict):
        return {
            "available": False,
            "auth_failed": False,
            "retryable": False,
            "error": "Picix API 返回了无法识别的数据格式",
        }
    if result.get("_auth_failed"):
        return {
            "available": False,
            "auth_failed": True,
            "retryable": False,
            "error": "Picix 登录已失效，请先重新认证",
        }
    if result.get("_request_failed"):
        return {
            "available": False,
            "auth_failed": False,
            "retryable": bool(result.get("_retryable")),
            "error": result.get("_error") or result.get("msg") or fallback,
        }
    if not result.get("success"):
        return {
            "available": False,
            "auth_failed": False,
            "retryable": False,
            "error": result.get("msg") or fallback,
        }
    return None


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
            response = requests.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        elif method.upper() == "POST":
            headers = HEADERS.copy()
            headers["content-type"] = "application/json"
            headers["origin"] = "https://picix.us"
            response = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
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
            print("⚠️ 认证失效: HTTP 401 Unauthorized")
            print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else response.text}")
            # 标记认证失效
            result = result if result else {}
            result["_auth_failed"] = True
            return result
        elif response.status_code == 403:
            # 认证被拒绝
            print("⚠️ 认证被拒绝: HTTP 403 Forbidden")
            print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else response.text}")
            result = result if result else {}
            result["_auth_failed"] = True
            return result
        else:
            print(f"API请求失败: HTTP {response.status_code}")
            print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else response.text}")
            if not isinstance(result, dict):
                result = {"data": result}
            result["_request_failed"] = True
            result["_http_status"] = response.status_code
            result["_retryable"] = bool(
                result.get("retryable")
                or response.status_code in {408, 425, 429, 500, 502, 503, 504, 522}
            )
            result["_error"] = (
                result.get("msg")
                or result.get("title")
                or f"Picix API 请求失败（HTTP {response.status_code}）"
            )
            return result
    except Exception as e:
        print(f"请求异常: {e}")
        logger.exception("REQUEST_ERROR | method=%s url=%s", method.upper(), url)
        return {
            "success": False,
            "_request_failed": True,
            "_retryable": True,
            "_error": f"Picix API 连接失败：{e}",
        }


def _get_list_api_state(endpoint, label):
    result = api_request("GET", endpoint)
    failure = _api_failure(result, f"暂时无法读取{label}")
    if failure:
        return {**failure, "items": []}
    items = result.get("data")
    if not isinstance(items, list):
        return {
            "available": False,
            "auth_failed": False,
            "retryable": False,
            "error": f"{label}接口返回格式已变化",
            "items": [],
        }
    return {
        "available": True,
        "auth_failed": False,
        "retryable": False,
        "error": "",
        "items": items,
    }


def get_auth_state():
    """Return authentication health without treating outages as logouts."""
    result = api_request("GET", "/Tasks/list")
    failure = _api_failure(result, "暂时无法检查 Picix 登录状态")
    if failure:
        return {**failure, "valid": False}
    return {
        "available": True,
        "auth_failed": False,
        "retryable": False,
        "error": "",
        "valid": True,
    }


def check_auth_valid():
    """Compatibility boolean check; prefer get_auth_state for UI decisions."""
    state = get_auth_state()
    return bool(state["available"] and state["valid"])
