class PodsError(Exception):
    def __init__(self, message: str, reason: str = "", suggestion: str = ""):
        self.message = message
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.reason:
            parts.append(f"  → {self.reason}")
        if self.suggestion:
            parts.append(f"  → {self.suggestion}")
        return "\n".join(parts)


class SetupError(PodsError):
    pass


class NetworkError(PodsError):
    pass


class InferenceError(PodsError):
    pass


class APIError(PodsError):
    pass


class StateError(PodsError):
    pass


class PlatformError(PodsError):
    pass
