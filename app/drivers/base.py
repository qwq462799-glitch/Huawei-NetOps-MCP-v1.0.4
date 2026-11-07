from abc import ABC, abstractmethod

class NetworkDriver(ABC):
    @abstractmethod
    def execute(self, device: dict, command: str) -> str:
        """执行单条命令并返回设备原始输出。"""
        raise NotImplementedError
