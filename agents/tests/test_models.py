from artisan_agents.config import GEMINI_MODEL_ID


def test_model_id_is_pinned_not_latest_alias() -> None:
    assert GEMINI_MODEL_ID == "gemini-3.8-flash"
