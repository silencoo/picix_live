import requests
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auto_unlock_helper import BASE_URL, HEADERS


# 注意：这里不包含 cf_clearance cookie，只使用 authorization header
headers = HEADERS.copy()
if not headers.get("authorization"):
    raise SystemExit(
        "未找到 authorization。请先通过 Bot /reauth 完成认证，"
        "或设置 PICIX_AUTHORIZATION。"
    )

url = f"{BASE_URL}/Movies/listRecommend"
response = requests.get(url, headers=headers, timeout=20)

print(f"状态码: {response.status_code}")
print(f"\n=== 响应头分析 ===")
print(f"完整响应头:")
for key, value in response.headers.items():
    print(f"  {key}: {value}")

# 检查可能包含过期信息的响应头字段
print(f"\n=== Token 有效期相关字段 ===")
expiry_fields = ['expires', 'cache-control', 'x-expires-at', 'x-token-expires',
                 'authorization-expires', 'token-expires', 'expires-at']
found_expiry = False
for field in expiry_fields:
    if field in response.headers:
        print(f"  ✓ {field}: {response.headers[field]}")
        found_expiry = True

if not found_expiry:
    print("  未在响应头中找到明确的过期时间字段")

# 检查 Cache-Control
if 'cache-control' in response.headers:
    cache_control = response.headers['cache-control']
    print(f"\nCache-Control 分析: {cache_control}")
    if 'max-age' in cache_control:
        import re
        match = re.search(r'max-age=(\d+)', cache_control)
        if match:
            max_age = int(match.group(1))
            print(f"  max-age: {max_age} 秒 ({max_age/3600:.2f} 小时)")

print(f"\n=== 响应内容 ===")
try:
    import json
    data = response.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))

    # 检查响应内容中是否有过期信息
    if isinstance(data, dict):
        print(f"\n=== 响应内容中的过期信息 ===")
        expiry_keys = ['expires', 'expires_at', 'expiresIn', 'expires_in',
                      'token_expires', 'valid_until', 'ttl']
        for key in expiry_keys:
            if key in data:
                print(f"  ✓ {key}: {data[key]}")
                found_expiry = True
        if not any(k in data for k in expiry_keys):
            print("  响应内容中未找到过期时间字段")

except Exception as e:
    print(f"JSON解析错误: {e}")
    # 尝试使用UTF-8编码打印文本
    try:
        print(response.text)
    except UnicodeEncodeError:
        # 如果还是编码错误，写入文件
        with open("response_output.txt", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("响应内容已保存到 response_output.txt (UTF-8编码)")
