from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class Bookmark:
    """
    «Entity» Bookmark — links the current session to a saved ResaleFlat (UC-05, UC-14,
    FR 2.2.4). Stored in the Django session only (decision 10); no user table (NFR 4).
    """

    session_id: str
    flat_id: int
    timestamp: datetime

    def to_session(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_session(cls, data: dict) -> "Bookmark":
        return cls(
            session_id=data["session_id"],
            flat_id=int(data["flat_id"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
