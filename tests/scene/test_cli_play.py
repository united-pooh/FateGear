from __future__ import annotations

from scenario.cli.play import _is_help_query, _is_location_query


def test_cli_table_talk_recognizes_location_queries() -> None:
    assert _is_location_query("我在哪里") is True
    assert _is_location_query(" 我 在 哪儿 ") is True


def test_cli_table_talk_recognizes_help_queries() -> None:
    assert _is_help_query("？") is True
    assert _is_help_query("何意味") is True
    assert _is_help_query("这是什么意思") is True
