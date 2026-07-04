"""Template for public-channel narration (KP language rule: §7.74).

Used for events that are spoken aloud / visible to all players — the
template wraps the summary with a scene header.
"""


def render_broadcast_narration(
    scene_name: str = "{scene_name}",
    event_summary: str = "{event_summary}",
) -> str:
    """Return narration text that announces an event publicly.

    Args:
        scene_name: The scene in which the announcement is made.
        event_summary: A short, player-visible summary of what happened.
    """
    return (
        f"[{scene_name}] {event_summary} —— 这一内容已公开传递，所有玩家均可听闻。"
    )
