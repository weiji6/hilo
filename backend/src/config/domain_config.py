"""Declarative domain adaptations shared by retrieval and agent prompts."""

import re
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class QueryRewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1)
    replacements: list[str] = Field(min_length=1)
    when_contains: list[str] = Field(default_factory=list)

    @field_validator("pattern")
    @classmethod
    def valid_pattern(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"Invalid query rewrite pattern: {error}") from error
        return value


class DomainProfile(BaseModel):
    """Optional domain behavior; the default is domain neutral."""

    model_config = ConfigDict(extra="forbid")

    name: str = "general"
    instructions: str = ""
    query_aliases: dict[str, list[str]] = Field(default_factory=dict)
    query_suffixes: list[str] = Field(default_factory=list)
    query_facets: dict[str, list[str]] = Field(default_factory=dict)
    rewrite_rules: list[QueryRewrite] = Field(default_factory=list)

    @field_validator("query_aliases", "query_facets")
    @classmethod
    def nonempty_terms(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if any(not key.strip() or any(not term.strip() for term in terms) for key, terms in value.items()):
            raise ValueError("Domain query terms must not be empty")
        return value

    @classmethod
    def from_config(cls, value: dict[str, Any] | None, *, config_dir: Path) -> Self:
        data = dict(value or {})
        profile_path = data.pop("profile", None)
        if profile_path:
            path = Path(profile_path)
            if not path.is_absolute():
                path = config_dir / path
            with path.open(encoding="utf-8") as stream:
                profile_data = yaml.safe_load(stream) or {}
            if not isinstance(profile_data, dict):
                raise ValueError(f"Domain profile must be a YAML mapping: {path}")
            data = {**profile_data, **data}
        return cls.model_validate(data)


_domain_profile = DomainProfile()


def get_domain_profile() -> DomainProfile:
    return _domain_profile


def set_domain_profile(profile: DomainProfile | None = None) -> None:
    global _domain_profile
    _domain_profile = profile if profile is not None else DomainProfile()


def render_domain_instructions() -> str:
    """Append trusted administrator instructions to lead and child agents."""
    instructions = get_domain_profile().instructions.strip()
    return f"\n<domain_instructions>\n{instructions}\n</domain_instructions>\n" if instructions else ""
