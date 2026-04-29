from src.config import get_bot_token, get_openai_config


def test_get_bot_token_raises_when_missing() -> None:
    try:
        get_bot_token({})
    except RuntimeError as exc:
        assert "bot_token" in str(exc)
    else:
        raise AssertionError("Expected get_bot_token to raise when token is missing")


def test_get_openai_config_merges_provider_and_model_extra_body() -> None:
    config = {
        "providers": {
            "openai": {
                "base_url": "https://api.example.com/v1",
                "api_key": "abc",
                "extra_body": {"temperature": 0.2},
                "extra_headers": {"x-test": "1"},
                "extra_query": {"q": "v"},
            }
        },
        "models": {"openai/gpt-test": {"max_tokens": 100}},
    }

    _, openai_config = get_openai_config(config, "openai/gpt-test")

    assert openai_config["model"] == "gpt-test"
    assert openai_config["extra_headers"] == {"x-test": "1"}
    assert openai_config["extra_query"] == {"q": "v"}
    assert openai_config["extra_body"] == {"temperature": 0.2, "max_tokens": 100}

