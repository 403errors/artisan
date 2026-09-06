from weblib import render


def test_bio_renders_text():
    html = render.render_profile_bio("Coffee enthusiast")
    assert "Coffee enthusiast" in html
    assert '<div class="bio">' in html


def test_comment_renders_text():
    html = render.render_comment("Nice post!")
    assert "Nice post!" in html


def test_bio_escapes_html():
    # Repro for the reported issue: markup in bios must be escaped, not injected.
    html = render.render_profile_bio("<script>alert(1)</script>")
    assert "<script>" not in html
