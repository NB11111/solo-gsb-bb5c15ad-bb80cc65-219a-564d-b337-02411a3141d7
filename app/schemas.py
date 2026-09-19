"""Request/response schemas for the review assignment API."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ManuscriptIn(BaseModel):
    manuscript_id: str = Field(..., min_length=1, max_length=128)
    authors: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    # overrides the request-level reviews_per_manuscript for this manuscript
    reviews_needed: Optional[int] = Field(default=None, ge=1, le=10_000)


class ReviewerIn(BaseModel):
    reviewer_id: str = Field(..., min_length=1, max_length=128)
    topics: list[str] = Field(default_factory=list)
    # manuscript ids this reviewer must not be assigned to; authors shared
    # with a blocked manuscript also trigger the conflict
    conflicts: list[str] = Field(default_factory=list)
    capacity: int = Field(..., ge=0, le=100_000)


class AssignRequest(BaseModel):
    manuscripts: list[ManuscriptIn] = Field(..., min_length=1)
    reviewers: list[ReviewerIn] = Field(..., min_length=1)
    # falls back to DEFAULT_REVIEWS_PER_MANUSCRIPT when omitted
    reviews_per_manuscript: Optional[int] = Field(default=None, ge=1, le=10_000)

    @model_validator(mode="after")
    def _validate(self):
        m_ids = [m.manuscript_id for m in self.manuscripts]
        r_ids = [r.reviewer_id for r in self.reviewers]
        if len(set(m_ids)) != len(m_ids):
            dupes = sorted({x for x in m_ids if m_ids.count(x) > 1})
            raise ValueError(f"duplicate manuscript_id: {', '.join(dupes)}")
        if len(set(r_ids)) != len(r_ids):
            dupes = sorted({x for x in r_ids if r_ids.count(x) > 1})
            raise ValueError(f"duplicate reviewer_id: {', '.join(dupes)}")
        known = set(m_ids)
        for r in self.reviewers:
            unknown = sorted(set(r.conflicts) - known)
            if unknown:
                raise ValueError(
                    f"reviewer {r.reviewer_id!r} conflicts with unknown "
                    f"manuscript_id(s): {', '.join(unknown)}"
                )
        return self


class AssignmentOut(BaseModel):
    manuscript_id: str
    reviewer_id: str


class UnmetOut(BaseModel):
    manuscript_id: str
    reviews_needed: int
    reviews_assigned: int
    shortfall: int
    eligible_reviewers: int
    reasons: list[str]


class WitnessOut(BaseModel):
    # minimum-cut (Hall-set) certificate proving infeasibility:
    # demand(manuscript_set) exceeds restricted_max_assignable
    manuscript_ids: list[str]
    neighbour_reviewer_ids: list[str]
    reviewer_ids_in_cut: list[str]
    demand_of_manuscript_set: int
    neighbour_capacity: int
    restricted_max_assignable: int
    gap: int
    shortfall: int


class BottleneckOut(BaseModel):
    reviewer_id: str
    capacity: int
    assigned: int


class TopicGapOut(BaseModel):
    topic: str
    demand: int
    matched: int
    gap: int
    reviewer_capacity: int
    eligible_reviewer_count: int
    manuscripts: list[str]


class FeasibleResponse(BaseModel):
    status: str = "feasible"
    assignment_id: str
    total_demand: int
    total_assigned: int
    assignments: list[AssignmentOut]


class InfeasibleResponse(BaseModel):
    status: str = "infeasible"
    stored: bool = False
    total_demand: int
    total_assigned: int
    shortfall: int
    unmet: list[UnmetOut]
    witness: WitnessOut
    bottleneck_reviewers: list[BottleneckOut]
    topic_gaps: list[TopicGapOut]
