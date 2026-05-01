from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class EngineStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


@dataclass
class HealthStatus:
    status: EngineStatus
    message: str = ""


class InferenceEngine(ABC):
    @abstractmethod
    def detect(self) -> bool:
        """Return True if this engine can run on the current hardware."""

    @abstractmethod
    def start(self, config: dict) -> None:
        """Start the inference engine process."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the inference engine process."""

    @abstractmethod
    def health(self) -> HealthStatus:
        """Return current health status."""

    @abstractmethod
    def get_models(self) -> list[str]:
        """Return list of available model names."""
