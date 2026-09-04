"""is_public_https and Settings.publish_allow_http: the shared "publishable URL" rule."""

from __future__ import annotations

from diffus.shared.config import Settings, is_public_https


def make_settings(
    public_base_url: str = "",
    publish_allow_http: bool = False,
) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        ig_app_id="app-id",
        ig_app_secret="app-secret",
        ig_redirect_uri="https://example.com/cb",
        telegram_bot_token="bot-token",
        telegram_chat_ids="-100111",
        basic_auth_username="admin",
        basic_auth_password="secret",
        public_base_url=public_base_url,
        publish_allow_http=publish_allow_http,
    )


# -- is_public_https, the pure rule ------------------------------------------


def test_https_is_always_ok():
    assert is_public_https("https://example.com")
    assert is_public_https("https://example.com", allow_http=True)


def test_http_is_rejected_by_default():
    assert not is_public_https("http://localhost:8000")


def test_http_is_ok_only_when_allow_http_is_set():
    assert is_public_https("http://localhost:8000", allow_http=True)


def test_empty_base_url_is_never_ok():
    assert not is_public_https("")
    assert not is_public_https("", allow_http=True)


# -- Settings.public_https wires publish_allow_http through the same rule ----


def test_settings_public_https_true_for_https_regardless_of_allow_http():
    settings = make_settings(public_base_url="https://example.com", publish_allow_http=False)
    assert settings.public_https


def test_settings_public_https_false_for_http_when_allow_http_is_off_by_default():
    settings = make_settings(public_base_url="http://localhost:8000")
    assert settings.publish_allow_http is False
    assert not settings.public_https


def test_settings_public_https_true_for_http_when_publish_allow_http_is_set():
    settings = make_settings(public_base_url="http://localhost:8000", publish_allow_http=True)
    assert settings.public_https


# -- new host-override settings default to the real hosts --------------------


def test_new_host_settings_default_to_the_real_instagram_and_telegram_hosts():
    settings = make_settings()
    assert settings.instagram_graph_base == "https://graph.instagram.com"
    assert settings.instagram_api_base == "https://api.instagram.com"
    assert settings.instagram_authorize_url == "https://www.instagram.com/oauth/authorize"
    assert settings.telegram_api_base == "https://api.telegram.org"
