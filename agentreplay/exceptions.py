class AgentReplayError(Exception):
    """Base exception for all agentreplay errors."""


class ConfigurationError(AgentReplayError):
    """Raised when the SDK is used before init() or with invalid config."""
