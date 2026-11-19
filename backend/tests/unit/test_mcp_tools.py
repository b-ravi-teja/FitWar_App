"""Unit tests for the FitWar MCP skeleton.

These tests are **pure-unit** — no database, no Redis, no network. They verify:

1. ``app.mcp.tools`` — tool registry and domain-logic correctness.
2. ``app.mcp.server.handle_request`` — JSON-RPC dispatch and wire-format.

All assertions use the same frozen XP constants from
``app.domain.game.xp_rules`` that the production code uses, so the tests
stay correct if the values are tuned between releases.
"""

from __future__ import annotations

import pytest

from app.domain.game.xp_rules import (
    BATTLE_WIN_XP,
    DAILY_COMPLETION_XP,
    MAX_STREAK_BONUS_DAYS,
    STREAK_BONUS_PER_DAY,
    XP_PER_LEVEL,
)
from app.mcp.server import MCP_PROTOCOL_VERSION, SERVER_INFO, handle_request
from app.mcp.tools import (
    calculate_battle_win_xp,
    calculate_xp_award,
    call_tool,
    get_level_info,
    get_xp_constants,
    list_tools,
    tool_names,
)


# ===========================================================================
# tool registry
# ===========================================================================


class TestToolRegistry:
    def test_expected_tools_registered(self):
        expected = {
            "get_xp_constants",
            "calculate_xp_award",
            "calculate_battle_win_xp",
            "get_level_info",
        }
        assert expected.issubset(tool_names())

    def test_list_tools_returns_name_and_description(self):
        manifest = list_tools()
        assert all("name" in t and "description" in t for t in manifest)

    def test_list_tools_descriptions_are_non_empty(self):
        for tool in list_tools():
            assert tool["description"], f"Tool {tool['name']!r} has an empty description"

    def test_call_tool_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown MCP tool"):
            call_tool("does_not_exist", {})

    def test_call_tool_bad_args_raises_type_error(self):
        with pytest.raises(TypeError):
            call_tool("calculate_xp_award", {"not_a_real_param": 99})


# ===========================================================================
# get_xp_constants
# ===========================================================================


class TestGetXpConstants:
    def test_returns_all_keys(self):
        result = get_xp_constants()
        assert set(result.keys()) == {
            "daily_completion_xp",
            "streak_bonus_per_day",
            "max_streak_bonus_days",
            "xp_per_level",
            "battle_win_xp",
        }

    def test_values_match_domain_constants(self):
        result = get_xp_constants()
        assert result["daily_completion_xp"] == DAILY_COMPLETION_XP
        assert result["streak_bonus_per_day"] == STREAK_BONUS_PER_DAY
        assert result["max_streak_bonus_days"] == MAX_STREAK_BONUS_DAYS
        assert result["xp_per_level"] == XP_PER_LEVEL
        assert result["battle_win_xp"] == BATTLE_WIN_XP

    def test_all_values_are_positive_integers(self):
        for key, value in get_xp_constants().items():
            assert isinstance(value, int) and value > 0, (
                f"Expected positive int for {key!r}, got {value!r}"
            )


# ===========================================================================
# calculate_xp_award
# ===========================================================================


class TestCalculateXpAward:
    def test_first_day_no_streak_bonus(self):
        result = calculate_xp_award(streak_after_completion=1)
        assert result["base"] == DAILY_COMPLETION_XP
        assert result["streak_bonus"] == 0
        assert result["total"] == DAILY_COMPLETION_XP

    def test_second_day_one_bonus_tick(self):
        result = calculate_xp_award(streak_after_completion=2)
        assert result["streak_bonus"] == STREAK_BONUS_PER_DAY
        assert result["total"] == DAILY_COMPLETION_XP + STREAK_BONUS_PER_DAY

    def test_streak_bonus_caps_at_max(self):
        # Streak beyond the cap should not earn more than the cap allows.
        at_cap = calculate_xp_award(streak_after_completion=MAX_STREAK_BONUS_DAYS + 1)
        beyond_cap = calculate_xp_award(streak_after_completion=MAX_STREAK_BONUS_DAYS + 10)
        assert at_cap["streak_bonus"] == beyond_cap["streak_bonus"]
        assert at_cap["streak_bonus"] == MAX_STREAK_BONUS_DAYS * STREAK_BONUS_PER_DAY

    def test_total_equals_base_plus_bonus(self):
        for streak in range(1, 10):
            result = calculate_xp_award(streak_after_completion=streak)
            assert result["total"] == result["base"] + result["streak_bonus"]

    def test_streak_after_completion_echoed(self):
        result = calculate_xp_award(streak_after_completion=3)
        assert result["streak_after_completion"] == 3

    def test_via_call_tool(self):
        result = call_tool("calculate_xp_award", {"streak_after_completion": 1})
        assert result["total"] == DAILY_COMPLETION_XP


# ===========================================================================
# calculate_battle_win_xp
# ===========================================================================


class TestCalculateBattleWinXp:
    def test_returns_correct_xp(self):
        result = calculate_battle_win_xp()
        assert result["battle_win_xp"] == BATTLE_WIN_XP

    def test_battle_win_xp_exceeds_single_day_completion(self):
        # ADR 0009: winning a head-to-head should read as a bigger deal.
        assert BATTLE_WIN_XP > DAILY_COMPLETION_XP


# ===========================================================================
# get_level_info
# ===========================================================================


class TestGetLevelInfo:
    def test_zero_xp_is_level_1(self):
        result = get_level_info(0)
        assert result["level"] == 1
        assert result["xp_into_level"] == 0
        assert result["xp_to_next_level"] == XP_PER_LEVEL

    def test_negative_xp_clamped_to_zero(self):
        result = get_level_info(-100)
        assert result["xp_total"] == 0
        assert result["level"] == 1

    def test_exactly_one_level_boundary(self):
        result = get_level_info(XP_PER_LEVEL)
        assert result["level"] == 2
        assert result["xp_into_level"] == 0
        assert result["xp_to_next_level"] == XP_PER_LEVEL

    def test_mid_level_progress(self):
        xp = XP_PER_LEVEL + XP_PER_LEVEL // 2
        result = get_level_info(xp)
        assert result["level"] == 2
        assert result["xp_into_level"] == XP_PER_LEVEL // 2
        assert result["xp_to_next_level"] == XP_PER_LEVEL - XP_PER_LEVEL // 2

    def test_xp_into_plus_xp_to_next_equals_xp_per_level(self):
        for xp in [0, 100, 499, 500, 501, 999, 1000, 2500]:
            result = get_level_info(xp)
            assert result["xp_into_level"] + result["xp_to_next_level"] == XP_PER_LEVEL, (
                f"Invariant broken for xp={xp}"
            )

    def test_via_call_tool(self):
        result = call_tool("get_level_info", {"xp_total": 0})
        assert result["level"] == 1


# ===========================================================================
# handle_request (MCP wire protocol)
# ===========================================================================


class TestHandleRequest:
    # --- initialize ---

    def test_initialize_returns_protocol_version(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp is not None
        assert resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

    def test_initialize_returns_server_info(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp is not None
        assert resp["result"]["serverInfo"] == SERVER_INFO

    def test_initialize_echoes_id(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 42, "method": "initialize", "params": {}})
        assert resp is not None
        assert resp["id"] == 42

    # --- initialized (notification) ---

    def test_initialized_notification_returns_none(self):
        resp = handle_request({"jsonrpc": "2.0", "method": "initialized"})
        assert resp is None

    # --- tools/list ---

    def test_tools_list_returns_tool_array(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert resp is not None
        assert "tools" in resp["result"]
        assert isinstance(resp["result"]["tools"], list)

    def test_tools_list_entries_have_required_fields(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert resp is not None
        for tool in resp["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    # --- tools/call ---

    def test_tools_call_get_xp_constants(self):
        resp = handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_xp_constants", "arguments": {}},
        })
        assert resp is not None
        assert resp["result"]["isError"] is False
        # content is a JSON string in the text field
        import json
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["daily_completion_xp"] == DAILY_COMPLETION_XP

    def test_tools_call_unknown_tool_returns_error(self):
        resp = handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        })
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS

    def test_tools_call_bad_args_returns_error(self):
        resp = handle_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "calculate_xp_award",
                "arguments": {"wrong_param": 1},
            },
        })
        assert resp is not None
        assert "error" in resp

    # --- prompts / resources stubs ---

    def test_prompts_list_returns_empty_list(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 6, "method": "prompts/list"})
        assert resp is not None
        assert resp["result"]["prompts"] == []

    def test_resources_list_returns_empty_list(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
        assert resp is not None
        assert resp["result"]["resources"] == []

    # --- unknown method ---

    def test_unknown_method_returns_method_not_found(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 8, "method": "bogus/method"})
        assert resp is not None
        assert resp["error"]["code"] == -32601

    def test_notification_with_unknown_method_returns_none(self):
        resp = handle_request({"jsonrpc": "2.0", "method": "bogus/notification"})
        assert resp is None

    # --- id passthrough ---

    def test_string_id_passthrough(self):
        resp = handle_request({
            "jsonrpc": "2.0",
            "id": "req-abc",
            "method": "tools/list",
        })
        assert resp is not None
        assert resp["id"] == "req-abc"
