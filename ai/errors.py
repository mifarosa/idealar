class AIError(Exception):
    """Base class for every failure of the AI layer."""


class AINotConfiguredError(AIError):
    pass


class AIRateLimitError(AIError):
    pass


class AIProviderError(AIError):
    """Network failure, timeout or HTTP error from a provider."""


class AIResponseError(AIError):
    """The provider answered, but not with usable JSON of the expected shape."""


class AllProvidersFailed(AIError):
    def __init__(self, failures: list[tuple[str, AIError]]):
        self.failures = failures
        details = "; ".join(f"{name}: {error}" for name, error in failures)
        super().__init__(f"All AI providers failed ({details})")
