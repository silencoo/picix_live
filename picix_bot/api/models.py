"""Shared structural types for API and domain state snapshots."""
from __future__ import annotations

from typing import Any, TypedDict


class ApiState(TypedDict):
    available: bool
    auth_failed: bool
    retryable: bool
    error: str


class ListState(ApiState):
    items: list[dict[str, Any]]


class AuthState(ApiState):
    valid: bool


class PackageState(ApiState):
    packages: list[dict[str, Any]]


class PackageSummary(ApiState):
    remaining: int
    active: list[dict[str, Any]]
    all: list[dict[str, Any]]


class CatalogState(ApiState):
    items: list[dict[str, Any]]
    endpoint: str | None
    params: dict[str, Any] | None
