"""MCP tool definitions for FitWar.

Each function decorated with ``@mcp_tool`` becomes an MCP tool: the decorator
records the function's name, docstring, and JSON-schema-annotated signature so
the protocol layer can advertise them to any connected AI client.

All tools are **pure-domain** — they receive plain Python values and return
plain dicts. They never import FastAPI, SQLAlchemy, or Redis, so they can be
exercised in unit tests without any infrastructure.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from app.domain.game.xp_rules import (
    BATTLE_WIN_XP,
    DAILY_COMPLETION_XP,
    MAX_STREAK_BONUS_DAYS,
    STREAK_BONUS_PER_DAY,
    XP_PER_LEVEL,
    battle_win_xp,
    completion_xp,
    level_for_xp,
    streak_bonus_xp,
    xp_into_level,
    xp_to_next_level,
)

F = TypeVar("F", bound=Callable[..., Any])

# Registry populated by @mcp_tool
_REGISTRY: dict[str, Callable[..., Any]] = {}


def mcp_tool(fn: F) -> F:
    """Register *fn* as an MCP tool and return it unchanged."""
    _REGISTRY[fn.__name__] = fn
    return fn


def get_tool(name: str) -> Callable[..., Any] | None:
    """Return a registered tool by name, or ``None`` if unknown."""
    return _REGISTRY.get(name)


def list_tools() -> list[dict[str, str]]:
    """Return a lightweight manifest of every registered tool."""
    return [
        {"name": name, "description": (fn.__doc__ or "").strip().splitlines()[0]}
        for name, fn in _REGISTRY.items()
    ]


# ---------------------------------------------------------------------------
# XP / levelling tools
# ---------------------------------------------------------------------------


@mcp_tool
def get_xp_constants() -> dict[str, int]:
    """Return the XP economy constants active in this deployment.

    Useful for rendering progress bars and "next level" hints in AI-generated
    summaries without hard-coding amounts that may change between releases.
    """
    return {
        "daily_completion_xp": DAILY_COMPLETION_XP,
        "streak_bonus_per_day": STREAK_BONUS_PER_DAY,
        "max_streak_bonus_days": MAX_STREAK_BONUS_DAYS,
        "xp_per_level": XP_PER_LEVEL,
        "battle_win_xp": BATTLE_WIN_XP,
    }


@mcp_tool
def calculate_xp_award(streak_after_completion: int) -> dict[str, int]:
    """Calculate the XP earned for completing a challenge day.

    Args:
        streak_after_completion: The participant's consecutive-day streak
            *after* today's completion is counted (1 on the first day).

    Returns a breakdown: base award, streak bonus, and total.
    """
    base = completion_xp()
    bonus = streak_bonus_xp(streak_after_completion)
    return {
        "base": base,
        "streak_bonus": bonus,
        "total": base + bonus,
        "streak_after_completion": streak_after_completion,
    }


@mcp_tool
def calculate_battle_win_xp() -> dict[str, int]:
    """Return the XP awarded for winning a 1v1 battle."""
    return {"battle_win_xp": battle_win_xp()}


@mcp_tool
def get_level_info(xp_total: int) -> dict[str, int]:
    """Derive level and progress bar values from a cumulative XP total.

    Args:
        xp_total: The participant's all-time XP (non-negative integer).

    Returns current level (1-based), XP earned inside that level, and XP
    still needed to reach the next level.
    """
    return {
        "xp_total": max(xp_total, 0),
        "level": level_for_xp(xp_total),
        "xp_into_level": xp_into_level(xp_total),
        "xp_to_next_level": xp_to_next_level(xp_total),
        "xp_per_level": XP_PER_LEVEL,
    }


# ---------------------------------------------------------------------------
# Tool dispatcher (used by the server transport layer)
# ---------------------------------------------------------------------------


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Call a registered tool by name, forwarding *arguments* as kwargs.

    Raises:
        KeyError: if *name* is not a registered tool.
        TypeError: if *arguments* don't match the tool's signature.
    """
    fn = _REGISTRY.get(name)
    if fn is None:
        raise KeyError(f"Unknown MCP tool: {name!r}")
    return fn(**arguments)


# Keep a frozen snapshot so callers that iterate the registry get a stable
# view even if future code adds tools after import time.
@functools.cache
def tool_names() -> frozenset[str]:
    """Return the names of all registered tools as a frozen set."""
    return frozenset(_REGISTRY)
