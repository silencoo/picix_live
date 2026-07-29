"""Runtime settings for the Picix Telegram Bot.

Environment variables take precedence over the legacy ``config.py`` file so
deployments can inject secrets without modifying source files.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from types import ModuleType


def _load_user_config() -> ModuleType | None:
    try:
        return importlib.import_module("config")
    except ModuleNotFoundError as error:
        if error.name == "config":
            return None
        raise


def _config_value(config: ModuleType | None, name: str, default):
    if config is None:
        return default
    return getattr(config, name, default)


def _parse_user_ids(raw_value) -> tuple[int, ...]:
    if raw_value in (None, ""):
        return ()
    if isinstance(raw_value, str):
        values = raw_value.split(",")
    else:
        values = raw_value

    user_ids: list[int] = []
    for value in values:
        text = str(value).strip()
        if text:
            user_ids.append(int(text))
    return tuple(user_ids)


def _read_int(name: str, config: ModuleType | None, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        raw_value = _config_value(config, name.removeprefix("PICIX_"), default)
    return int(raw_value)


@dataclass(frozen=True, slots=True)
class BotSettings:
    token: str
    allowed_user_ids: tuple[int, ...]
    notification_threshold: int
    check_interval: int
    auto_unlock_hour: int | None
    auto_unlock_minute: int

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.token != "YOUR_BOT_TOKEN")


def load_settings() -> BotSettings:
    config = _load_user_config()

    token = os.getenv(
        "PICIX_BOT_TOKEN",
        str(_config_value(config, "BOT_TOKEN", "YOUR_BOT_TOKEN")),
    ).strip()

    raw_user_ids = os.getenv("PICIX_ALLOWED_USER_IDS")
    if raw_user_ids is None:
        raw_user_ids = _config_value(config, "ALLOWED_USER_IDS", ())

    raw_hour = os.getenv("PICIX_AUTO_UNLOCK_HOUR")
    if raw_hour is None:
        raw_hour = _config_value(config, "AUTO_UNLOCK_HOUR", 9)
    auto_unlock_hour = None if raw_hour in (None, "", "none", "None") else int(raw_hour)

    return BotSettings(
        token=token,
        allowed_user_ids=_parse_user_ids(raw_user_ids),
        notification_threshold=_read_int(
            "PICIX_NOTIFICATION_THRESHOLD",
            config,
            10,
        ),
        check_interval=_read_int(
            "PICIX_CHECK_INTERVAL",
            config,
            3600,
        ),
        auto_unlock_hour=auto_unlock_hour,
        auto_unlock_minute=_read_int(
            "PICIX_AUTO_UNLOCK_MINUTE",
            config,
            0,
        ),
    )


settings = load_settings()
