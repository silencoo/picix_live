"""Inspect the recommendation endpoint without a Cloudflare cookie."""
from __future__ import annotations

import json

import requests

from picix_bot.api.client import BASE_URL, HEADERS, REQUEST_TIMEOUT_SECONDS


def main() -> int:
    headers = HEADERS.copy()
    if not headers.get("authorization"):
        print("未找到 authorization，请先通过 Bot /reauth 完成认证。")
        return 1

    response = requests.get(
        f"{BASE_URL}/Movies/listRecommend",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    print(f"状态码: {response.status_code}")
    print("响应头:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(response.text[:2000])
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
