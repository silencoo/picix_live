"""Launch a persistent CloakBrowser instance for Chrome DevTools MCP."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

from cloakbrowser import launch_persistent_context


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "unlock_data"
PROFILE_VERSION = 2
PROFILE_DIR = DATA_DIR / f"cloakbrowser_profile_v{PROFILE_VERSION}"
SEED_FILE = PROFILE_DIR / "fingerprint_seed.txt"
READY_FILE = DATA_DIR / "cloakbrowser_cdp_ready.json"
WARMUP_URL = "https://picix.us/"


def load_or_create_fingerprint_seed() -> int:
    """Keep one browser identity across restarts of the persistent profile."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        seed = int(SEED_FILE.read_text(encoding="utf-8").strip())
        if 10_000 <= seed <= 99_999:
            return seed
    except (FileNotFoundError, OSError, ValueError):
        pass

    seed = secrets.randbelow(90_000) + 10_000
    SEED_FILE.write_text(str(seed), encoding="utf-8")
    return seed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start persistent CloakBrowser with a local CDP endpoint."
    )
    parser.add_argument("--port", type=int, default=9242)
    return parser.parse_args()


def write_ready_state(*, ready: bool, detail: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ready": ready,
        "profile_version": PROFILE_VERSION,
        "profile": str(PROFILE_DIR),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        **detail,
    }
    READY_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def warm_up_picix(context, timeout_seconds: int = 90) -> dict:
    """Let CloakBrowser itself clear Cloudflare before an external CDP client acts."""
    page = context.pages[0] if context.pages else context.new_page()
    response = page.goto(
        WARMUP_URL,
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    deadline = time.monotonic() + timeout_seconds
    movement_index = 0
    movements = [(220, 180), (480, 260), (760, 420), (540, 560)]

    while time.monotonic() < deadline:
        title = page.title()
        url = page.url
        body = page.locator("body").inner_text(timeout=10_000)
        challenge_visible = (
            "Performing security verification" in body
            or "Just a moment" in title
        )

        if not challenge_visible and (
            "用户登录" in body
            or "使用 Telegram 登录" in body
            or "/Dashs" in url
        ):
            login_match = re.search(r"/login\s+(\d+)", body)
            login_code = login_match.group(1) if login_match else None
            return {
                "cloudflare_passed": True,
                "status": response.status if response else None,
                "title": title,
                "url": url,
                "login_command": f"/login {login_code}" if login_code else None,
                "auth_bot": "@vStreamingBot",
                "auth_bot_url": (
                    f"https://t.me/vStreamingBot?start=login_{login_code}"
                    if login_code
                    else None
                ),
            }

        x, y = movements[movement_index % len(movements)]
        movement_index += 1
        page.mouse.move(x, y)
        time.sleep(2)

    return {
        "cloudflare_passed": False,
        "status": response.status if response else None,
        "title": page.title(),
        "url": page.url,
        "error": "Cloudflare warm-up timed out",
    }


def main() -> None:
    args = parse_args()
    seed = load_or_create_fingerprint_seed()
    READY_FILE.unlink(missing_ok=True)

    context = launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        humanize=True,
        args=[
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={args.port}",
            f"--fingerprint={seed}",
        ],
    )

    try:
        warmup_result = warm_up_picix(context)
    except Exception as exc:
        warmup_result = {
            "cloudflare_passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    write_ready_state(
        ready=True,
        detail={
            "cdp_url": f"http://127.0.0.1:{args.port}",
            **warmup_result,
        },
    )
    print(json.dumps(warmup_result, ensure_ascii=False), flush=True)

    try:
        while True:
            # Accessing pages also detects a browser window closed by the user.
            context.pages
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception:
        # The browser has already exited or the CDP connection was closed.
        pass
    finally:
        try:
            context.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
