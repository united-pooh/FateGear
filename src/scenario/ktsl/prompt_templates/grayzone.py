"""Template for ambiguous gray-zone decisions (KP language rule: §7.74).

Fires when a character's action sits at the boundary between "knows" and
"doesn't know" — the narration should prompt the player to justify their
character's knowledge path rather than arbitrarily granting or denying.
"""


def render_grayzone_guidance(
    scene_name: str = "{scene_name}",
    character_name: str = "{character_name}",
) -> str:
    """Return narration text that asks the player to clarify gray-zone knowledge.

    Args:
        scene_name: The scene where the ambiguous action took place.
        character_name: The character whose knowledge boundary is unclear.
    """
    return (
        f"[灰区警告 · {scene_name}] {character_name} 的行动游走在「已知」与「未知」的边界上。"
        f"请玩家在继续之前说明该角色是通过何种途径获知这一信息的。"
    )
