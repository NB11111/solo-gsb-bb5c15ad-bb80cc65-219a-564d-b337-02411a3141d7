"""In-memory storage of *feasible* assignments only.

An infeasible request never creates a stored record (no partial results are
kept).  Records are keyed by a canonical hash of the request payload, so
repeating an identical request returns the same ``assignment_id`` and the
same assignment.
"""

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Optional

from .schemas import AssignRequest


def canonical_request_hash(req: AssignRequest, reviews_per_manuscript: int) -> str:
    """Stable 32-hex-char id independent of list order inside the payload."""
    payload = {
        "reviews_per_manuscript": reviews_per_manuscript,
        "manuscripts": sorted(
            (
                {
                    "manuscript_id": m.manuscript_id,
                    "authors": sorted(m.authors),
                    "topics": sorted(m.topics),
                    "reviews_needed": m.reviews_needed,
                }
                for m in req.manuscripts
            ),
            key=lambda x: x["manuscript_id"],
        ),
        "reviewers": sorted(
            (
                {
                    "reviewer_id": r.reviewer_id,
                    "topics": sorted(r.topics),
                    "conflicts": sorted(r.conflicts),
                    "capacity": r.capacity,
                }
                for r in req.reviewers
            ),
            key=lambda x: x["reviewer_id"],
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class StoredAssignment:
    def __init__(self, assignment_id: str, assignments: list,
                 total_demand: int, total_assigned: int):
        self.assignment_id = assignment_id
        self.assignments = assignments
        self.total_demand = total_demand
        self.total_assigned = total_assigned
        self.created_at = datetime.now(timezone.utc)


class AssignmentStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, StoredAssignment] = {}

    def put_if_absent(
        self,
        assignment_id: str,
        assignments: list,
        total_demand: int,
        total_assigned: int,
    ) -> StoredAssignment:
        with self._lock:
            existing = self._records.get(assignment_id)
            if existing is None:
                existing = StoredAssignment(
                    assignment_id, assignments, total_demand, total_assigned
                )
                self._records[assignment_id] = existing
            return existing

    def get(self, assignment_id: str) -> Optional[StoredAssignment]:
        with self._lock:
            return self._records.get(assignment_id)

    def count(self) -> int:
        with self._lock:
            return len(self._records)
