import pytest

from etl_platform import validators


def test_validator_rejects_hardcoded_password():
    with pytest.raises(validators.ValidationError, match="Hardcoded secrets"):
        validators.validate_no_hardcoded_secrets({
            "user": "${DB_USER}",
            "password": "plain-text-password",
        })


def test_validator_accepts_env_based_credentials():
    assert validators.validate_no_hardcoded_secrets({
        "user": "${DB_USER}",
        "password": "${DB_PASSWORD}",
        "sources": [
            {
                "type": "rest",
                "headers": {"Authorization": "Bearer ${API_TOKEN}"},
            }
        ],
    }) is None


def test_api_source_validates_auth_shape():
    with pytest.raises(validators.ValidationError, match="bearer auth requires"):
        validators.validate_api_source({
            "name": "bad_api",
            "type": "rest",
            "url": "https://api.example.com/items",
            "auth": {"type": "bearer"},
        })


def test_api_source_accepts_bearer_token_env():
    assert validators.validate_api_source({
        "name": "good_api",
        "type": "rest",
        "url": "https://api.example.com/items",
        "auth": {"type": "bearer", "token_env": "API_TOKEN"},
    }) is None
