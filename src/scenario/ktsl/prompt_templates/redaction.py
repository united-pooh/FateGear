"""Template for redacted-information narration (KP language rule: §7.74).

Used when a high-sensitivity info piece is deliberately withheld from a
character — the narration must acknowledge the gap without revealing
the hidden content.
"""


def render_redaction_notice(
    character_name: str = "{character_name}",
    info_id: str = "{info_id}",
) -> str:
    """Return narration text when a high-sensitivity info is redacted for a character.

    Args:
        character_name: Display name of the blocked character.
        info_id: Identifier of the redacted info piece (for KP tracking only).

    Returns:
        A templated narration string.  Callers are expected to ``.format()``
        against the result before injecting into a prompt, or leave the
        placeholders intact for downstream substitution.
    """
    return (
        f"{character_name} 尝试回忆起 {info_id} 相关的内容，"
        f"但记忆却一片模糊——某种力量阻断了这条线索。"
    )
