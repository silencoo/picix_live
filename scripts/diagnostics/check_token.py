"""Check the current Picix authorization without printing the credential."""
from __future__ import annotations

from datetime import datetime

from picix_bot.api.client import get_auth_state


def main() -> int:
    print("=== Picix 登录状态 ===")
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    state = get_auth_state()
    if state["available"]:
        print("✓ authorization 当前有效")
    elif state["auth_failed"]:
        print("✗ authorization 已失效")
    else:
        print(f"⚠️ 暂时无法检查 authorization：{state['error']}")
    print("凭据内容未输出。Picix 接口没有提供明确的过期时间字段。")
    return 0 if state["available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
