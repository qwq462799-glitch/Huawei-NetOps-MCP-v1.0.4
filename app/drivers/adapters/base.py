from abc import ABC, abstractmethod


class SimulatorAdapter(ABC):
    name: str

    @abstractmethod
    def normalize(self, device: dict) -> dict:
        """Validate simulator profile and return normalized device settings."""
        raise NotImplementedError
