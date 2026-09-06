"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

from weblib import render


def test_bio_escapes_script_tags():
    html = render.render_profile_bio("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_comment_escapes_script_tags():
    # The sibling sink has the same defect class and must be fixed too.
    html = render.render_comment("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_comment_escapes_event_handler_injection():
    html = render.render_comment('"><img src=x onerror=alert(1)>')
    assert "<img" not in html


def test_normal_text_still_renders():
    assert "Coffee enthusiast" in render.render_profile_bio("Coffee enthusiast")
    assert "Nice post!" in render.render_comment("Nice post!")
