"""HTML rendering helpers for user-generated content."""


def render_profile_bio(bio: str) -> str:
    """Renders a user's profile bio into the profile page card."""
    return f'<div class="bio">{bio}</div>'


def render_comment(body: str) -> str:
    """Renders a comment into the discussion thread."""
    return f'<li class="comment">{body}</li>'
