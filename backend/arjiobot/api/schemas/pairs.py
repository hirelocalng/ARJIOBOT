"""Pair API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class PairRequest(BaseModel):
    symbol: str
    enabled: bool = True


class PairImportRequest(BaseModel):
    symbols: list[str]
