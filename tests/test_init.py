import pytest

import agentreplay
from agentreplay import _state
from agentreplay.exceptions import ConfigurationError

ENV_VARS = (
    "AGENTREPLAY_API_KEY",
    "AGENTREPLAY_PROJECT_ID",
    "AGENTREPLAY_ENDPOINT",
    "AGENTREPLAY_ENVIRONMENT",
    "AGENTREPLAY_AGENT_VERSION",
    "AGENTREPLAY_FRAMEWORK",
)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    _state.reset()
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    _state.reset()


def test_init_with_explicit_args():
    config = agentreplay.init(api_key="key123", project_id="proj1")

    assert config.api_key == "key123"
    assert config.project_id == "proj1"
    assert config.endpoint == "https://ingest.agentreplay.dev"
    assert config.environment == "development"
    assert config.enabled is True
    assert agentreplay.is_initialized() is True
    assert agentreplay.get_config() is config


def test_init_reads_env_vars(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_API_KEY", "env-key")
    monkeypatch.setenv("AGENTREPLAY_PROJECT_ID", "env-proj")
    monkeypatch.setenv("AGENTREPLAY_ENDPOINT", "https://custom.example.com")
    monkeypatch.setenv("AGENTREPLAY_ENVIRONMENT", "production")

    config = agentreplay.init()

    assert config.api_key == "env-key"
    assert config.project_id == "env-proj"
    assert config.endpoint == "https://custom.example.com"
    assert config.environment == "production"


def test_explicit_args_override_env(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_API_KEY", "env-key")
    monkeypatch.setenv("AGENTREPLAY_PROJECT_ID", "env-proj")

    config = agentreplay.init(api_key="explicit-key", project_id="proj1")

    assert config.api_key == "explicit-key"
    assert config.project_id == "proj1"


def test_missing_credentials_raises():
    with pytest.raises(ConfigurationError):
        agentreplay.init()


def test_disabled_mode_skips_validation():
    config = agentreplay.init(enabled=False)

    assert config.enabled is False
    assert config.api_key is None
    assert agentreplay.is_initialized() is True


def test_get_config_before_init_raises():
    with pytest.raises(ConfigurationError):
        agentreplay.get_config()


def test_is_initialized_before_init_is_false():
    assert agentreplay.is_initialized() is False


def test_redact_callback_stored():
    def redact_fn(payload):
        return payload

    config = agentreplay.init(api_key="k", project_id="p", redact=redact_fn)

    assert config.redact is redact_fn


def test_reinit_replaces_global_config():
    agentreplay.init(api_key="key1", project_id="proj1")
    config2 = agentreplay.init(api_key="key2", project_id="proj2")

    assert agentreplay.get_config() is config2
    assert agentreplay.get_config().api_key == "key2"


def test_init_with_explicit_agent_version_and_framework(monkeypatch):
    # Explicit args win even if git detection would return something else.
    monkeypatch.setattr(agentreplay, "_detect_git_sha", lambda: "deadbeef")

    config = agentreplay.init(
        api_key="key", project_id="proj", agent_version="v1.2.3", framework="langgraph"
    )

    assert config.agent_version == "v1.2.3"
    assert config.framework == "langgraph"


def test_init_reads_agent_version_and_framework_env_vars(monkeypatch):
    monkeypatch.setattr(agentreplay, "_detect_git_sha", lambda: "deadbeef")
    monkeypatch.setenv("AGENTREPLAY_AGENT_VERSION", "env-version")
    monkeypatch.setenv("AGENTREPLAY_FRAMEWORK", "crewai")

    config = agentreplay.init(api_key="key", project_id="proj")

    assert config.agent_version == "env-version"
    assert config.framework == "crewai"


def test_agent_version_defaults_to_git_sha_when_unset(monkeypatch):
    monkeypatch.setattr(agentreplay, "_detect_git_sha", lambda: "abc1234")

    config = agentreplay.init(api_key="key", project_id="proj")

    assert config.agent_version == "abc1234"


def test_agent_version_none_when_git_sha_unavailable(monkeypatch):
    monkeypatch.setattr(agentreplay, "_detect_git_sha", lambda: None)

    config = agentreplay.init(api_key="key", project_id="proj")

    assert config.agent_version is None
    assert config.framework is None


def test_detect_git_sha_returns_none_on_subprocess_error(monkeypatch):
    import subprocess

    def _raise(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", _raise)

    assert agentreplay._detect_git_sha() is None


def test_detect_git_sha_returns_none_on_nonzero_exit(monkeypatch):
    import subprocess

    class _Result:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())

    assert agentreplay._detect_git_sha() is None


def test_detect_git_sha_returns_stripped_stdout(monkeypatch):
    import subprocess

    class _Result:
        returncode = 0
        stdout = "abc1234\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())

    assert agentreplay._detect_git_sha() == "abc1234"
