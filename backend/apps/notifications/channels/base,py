from abc import ABC, abstractmethod


class BaseChannel(ABC):
    name: str

    @abstractmethod
    def send(self, notification) -> dict:
        """Returns {'success': bool, 'provider_id': str|None, 'error': str|None}"""
        raise NotImplementedError