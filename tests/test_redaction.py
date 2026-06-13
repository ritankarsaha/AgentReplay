from agentreplay.redaction import DEFAULT_PII_FIELD_NAMES, REDACTED_VALUE, redact_fields, redact_pii


def test_redact_pii_masks_default_fields_case_insensitive():
    payload = {
        "Email": "alice@example.com",
        "password": "hunter2",
        "model": "gpt-4o-mini",
    }

    redacted = redact_pii(payload)

    assert redacted["Email"] == REDACTED_VALUE
    assert redacted["password"] == REDACTED_VALUE
    assert redacted["model"] == "gpt-4o-mini"


def test_redact_pii_is_recursive_through_dicts_and_lists():
    payload = {
        "messages": [
            {"role": "user", "content": "hi", "metadata": {"email": "bob@example.com"}},
            {"role": "assistant", "content": "hello"},
        ]
    }

    redacted = redact_pii(payload)

    assert redacted["messages"][0]["metadata"]["email"] == REDACTED_VALUE
    assert redacted["messages"][0]["content"] == "hi"
    assert redacted["messages"][1]["content"] == "hello"


def test_redact_pii_does_not_mutate_input():
    payload = {"email": "alice@example.com"}
    redact_pii(payload)
    assert payload["email"] == "alice@example.com"


def test_redact_fields_custom_field_names_and_replacement():
    custom = redact_fields(["custom_secret"], replacement="***")
    payload = {"custom_secret": "shh", "email": "alice@example.com"}

    redacted = custom(payload)

    assert redacted["custom_secret"] == "***"
    # Not in the custom field set, so left alone.
    assert redacted["email"] == "alice@example.com"


def test_default_pii_field_names_cover_common_secrets():
    for name in ("email", "password", "api_key", "ssn", "credit_card"):
        assert name in DEFAULT_PII_FIELD_NAMES
