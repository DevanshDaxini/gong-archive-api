from __future__ import annotations
from pydantic import BaseModel


class DateFilter(BaseModel):
    fromDateTime: str
    toDateTime: str


class ExtensiveRequest(BaseModel):
    filter: DateFilter


class CallIdFilter(BaseModel):
    callIds: list[str]


class TranscriptRequest(BaseModel):
    filter: CallIdFilter
