import requests
from datetime import datetime

from auto_unlock_helper import BASE_URL, HEADERS


url = f"{BASE_URL}/Movies/listRecommend"
headers = HEADERS.copy()
if not headers.get("authorization"):
    raise SystemExit(
        "未找到 authorization。请先通过 Bot /reauth 完成认证，"
        "或设置 PICIX_AUTHORIZATION。"
    )

print("=== Token 有效期分析 ===\n")

# 测试当前 token 是否有效
print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("测试 Token: 已从安全配置加载（内容不输出）\n")

response = requests.get(url, headers=headers, timeout=20)

print(f"状态码: {response.status_code}")

if response.status_code == 200:
    try:
        data = response.json()
        if data.get('success'):
            print("✓ Token 当前有效")
        else:
            print(f"✗ Token 可能无效: {data.get('msg', '未知错误')}")
    except:
        print("✓ Token 当前有效（响应格式异常但状态码200）")
elif response.status_code == 401:
    print("✗ Token 已过期或无效 (401 Unauthorized)")
    try:
        print(f"错误信息: {response.text}")
    except:
        pass
elif response.status_code == 403:
    print("✗ Token 被拒绝 (403 Forbidden)")
else:
    print(f"✗ 请求失败: {response.status_code}")

print("\n=== 分析结果 ===")
print("从响应头分析:")
print("  - 响应头中未找到明确的过期时间字段")
print("  - 响应内容中未找到过期时间信息")
print("\n可能的情况:")
print("  1. Token 可能是长期有效的（直到被主动撤销）")
print("  2. Token 有效期信息可能在其他接口返回（如登录接口）")
print("  3. Token 可能基于会话，在用户登出或服务器端撤销时失效")
print("  4. Token 可能没有明确的过期时间，而是通过其他机制管理（如使用频率限制）")
print("\n建议:")
print("  - 可以尝试调用登录/认证相关接口查看 token 信息")
print("  - 或者持续监控该 token，观察何时失效")
print("  - 查看浏览器开发者工具中的网络请求，看是否有 token 刷新机制")
