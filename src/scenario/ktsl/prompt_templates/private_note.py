"""Template for private KP notes to an individual player (§7.74).

Used when the notebook entry must be visible to one player only — for
instance, info pieces gated behind a perception check.
"""


def render_private_note(
    character_name: str = "{character_name}",
    detail: str = "{detail}",
) -> str:
    """Return a private note addressed to a single character.

    Args:
        character_name: The recipient character's name.
        detail: The hidden detail revealed to this character.
    """
    return (
        f"[对 {character_name} 的私下提示]：{detail}"
    )
