from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time

class Status(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELED = "canceled"

@dataclass
class QueueItem:
    id: Optional[int]
    url: str
    title: Optional[str] = None
    status: Status = Status.QUEUED
    filepath: Optional[str] = None
    added_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    total_bytes: Optional[int] = None
    downloaded_bytes: Optional[int] = None
    speed: Optional[float] = None
    eta: Optional[int] = None
    errmsg: Optional[str] = None
    format: Optional[str] = "best"
    position: int = 0
    thumb_path: Optional[str] = None
    uploader: Optional[str] = None
    duration: Optional[int] = None
