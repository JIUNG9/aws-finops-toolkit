"""Abstract base for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    provider: str
    tokens_used: int
    confidence: Optional[float] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "",
                       max_tokens: int = 2000, temperature: float = 0.3) -> LLMResponse:
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        ...


# LLM registry
_PROVIDERS: dict[str, type[LLMProvider]] = {}


def register_llm(name: str, cls: type[LLMProvider]) -> None:
    _PROVIDERS[name] = cls


def get_llm_provider(name: str, **kwargs) -> LLMProvider:
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown LLM provider: {name}. Available: {list(_PROVIDERS.keys())}")
    return _PROVIDERS[name](**kwargs)


def list_llm_providers() -> list[str]:
    return list(_PROVIDERS.keys())
