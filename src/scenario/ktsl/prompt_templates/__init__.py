"""KP language rule prompt templates for KTSL protocol (paper §7.74).

Each module exposes a single render function that returns either:

* A template string with ``{param}`` placeholders (default arguments are
  themselves the placeholder names so the bare render call produces a
  ready-to-format template), or
* A fully-rendered string when callers pass concrete values.

The four KP situations covered are:

1. Redaction — a character is blocked from sensitive info.
2. Gray-zone — a character's knowledge boundary is ambiguous.
3. Broadcast — a public announcement visible to all players.
4. Private note — a message to a single player only.
"""
from .redaction import render_redaction_notice
from .grayzone import render_grayzone_guidance
from .broadcast import render_broadcast_narration
from .private_note import render_private_note

__all__ = [
    "render_redaction_notice",
    "render_grayzone_guidance",
    "render_broadcast_narration",
    "render_private_note",
]
