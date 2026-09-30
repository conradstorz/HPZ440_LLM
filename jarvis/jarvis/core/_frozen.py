"""Immutable mapping helper for the NKO. Copied from GTE src/gte/models/_frozen.py."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


def _freeze_mapping(v: Any) -> MappingProxyType:
    if isinstance(v, MappingProxyType):
        return v
    if isinstance(v, Mapping):
        return MappingProxyType(dict(v))
    raise TypeError("expected a mapping")


FrozenDict = Annotated[
    MappingProxyType,
    BeforeValidator(_freeze_mapping),
    PlainSerializer(lambda v: dict(v), return_type=dict, when_used="json"),
]
