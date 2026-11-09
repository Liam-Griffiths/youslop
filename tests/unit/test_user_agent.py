"""T16.3: archive requests carry a User-Agent Wikimedia accepts."""
from app import brand, config


def test_default_has_product_and_site():
    assert config._user_agent("") == f"{brand.NAME}/1.0 (+https://{brand.SITE_URL})"


def test_contact_is_appended():
    assert config._user_agent(" me@example.com ").endswith("; me@example.com)")


def test_full_user_agent_is_kept():
    assert config._user_agent("Mine/2.0 (x)") == "Mine/2.0 (x)"
