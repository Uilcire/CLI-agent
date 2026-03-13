"""Pydantic models for agent memory (personality, projects, sessions)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Personality(BaseModel):
    """Agent personality with mutable soul and immutable core values."""

    model_config = ConfigDict(validate_assignment=True)

    soul: str
    immutable_core: str

    def __setattr__(self, name: str, value: object) -> None:
        if name == "immutable_core" and "immutable_core" in self.__dict__:
            raise AttributeError("immutable_core cannot be modified after initialization")
        super().__setattr__(name, value)


class Project(BaseModel):
    """A tracked project with status, tags, capabilities, and sessions."""

    project_id: str
    description: str
    status: Literal["active", "paused", "complete"]
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)
    learnings: str = ""
    last_summarized_session: str | None = None
    cwd: str = ""


class SessionDigest(BaseModel):
    """Summary of a past session for a project."""

    session_id: str
    project_id: str
    timestamp: str  # ISO 8601
    summary: str
    capabilities: list[str] = Field(default_factory=list)
    learnings: str = ""


class ActiveSession(BaseModel):
    """Currently active session with messages."""

    session_id: str
    project_id: str | None = None
    messages: list[dict] = Field(default_factory=list)  # {"role": str, "content": str}
