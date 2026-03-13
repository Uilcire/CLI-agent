"""Configuration for memory subsystem."""

import os
from dataclasses import dataclass


@dataclass
class MemoryConfig:
    summarization_threshold: int = 5
    context_token_budget: int = 4000
    learnings_max_tokens: int = 1500
    data_dir: str = os.path.expanduser("./agent-memory")
    digest_timeout_seconds: float = 30.0
