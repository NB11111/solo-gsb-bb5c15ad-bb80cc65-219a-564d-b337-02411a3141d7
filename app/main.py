"""FastAPI application: global (maximum-flow) anonymous review assignment."""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from . import config
from .matcher import (
    ManuscriptInput,
    ReviewerInput,
    solve,
)
from .schemas import (
    AssignmentOut,
    AssignRequest,
    FeasibleResponse,
    InfeasibleResponse,
    WitnessOut,
    BottleneckOut,
    TopicGapOut,
    UnmetOut,
)
from .store import AssignmentStore, canonical_request_hash

app = FastAPI(
    title="Anonymous Review Assignment API",
    description=(
        "Assigns reviewers to manuscripts with a single global maximum-flow "
        "computation (never per-manuscript greedy). Enforces topic coverage, "
        "conflicts of interest and reviewer capacities; infeasible requests "
        "are rejected with a diagnostic certificate and are never stored."
    ),
    version="1.0.0",
)
store = AssignmentStore()


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": config.SERVICE_NAME,
        "docs": "/docs",
        "health": "/health",
        "assign": "POST /assign",
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "stored_assignments": store.count()}


@app.post(
    "/assign",
    response_model=FeasibleResponse,
    responses={409: {"model": InfeasibleResponse}, 422: {"description": "invalid request"}},
    tags=["assignment"],
    summary="Compute a feasible global reviewer assignment",
)
def assign(req: AssignRequest):
    if len(req.manuscripts) > config.MAX_MANUSCRIPTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"too many manuscripts: {len(req.manuscripts)} "
                f"> MAX_MANUSCRIPTS={config.MAX_MANUSCRIPTS}"
            ),
        )
    if len(req.reviewers) > config.MAX_REVIEWERS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"too many reviewers: {len(req.reviewers)} "
                f"> MAX_REVIEWERS={config.MAX_REVIEWERS}"
            ),
        )

    effective_per_manuscript = (
        req.reviews_per_manuscript
        if req.reviews_per_manuscript is not None
        else config.DEFAULT_REVIEWS_PER_MANUSCRIPT
    )
    assignment_id = canonical_request_hash(req, effective_per_manuscript)

    # Sorting by id is the single source of deterministic tie-breaking.
    manuscripts = sorted(req.manuscripts, key=lambda m: m.manuscript_id)
    reviewers = sorted(req.reviewers, key=lambda r: r.reviewer_id)

    m_inputs = [
        ManuscriptInput(
            manuscript_id=m.manuscript_id,
            authors=tuple(m.authors),
            topics=frozenset(m.topics),
            reviews_needed=(
                m.reviews_needed
                if m.reviews_needed is not None
                else effective_per_manuscript
            ),
        )
        for m in manuscripts
    ]
    r_inputs = [
        ReviewerInput(
            reviewer_id=r.reviewer_id,
            topics=frozenset(r.topics),
            conflicts=frozenset(r.conflicts),
            capacity=r.capacity,
        )
        for r in reviewers
    ]

    result = solve(m_inputs, r_inputs)

    if result.feasible:
        assignments = sorted(
            result.assignments,
            key=lambda a: (a.manuscript_id, a.reviewer_id),
        )
        record = store.put_if_absent(
            assignment_id,
            assignments,
            result.total_demand,
            result.total_assigned,
        )
        return FeasibleResponse(
            assignment_id=record.assignment_id,
            total_demand=result.total_demand,
            total_assigned=result.total_assigned,
            assignments=[
                AssignmentOut(manuscript_id=a.manuscript_id, reviewer_id=a.reviewer_id)
                for a in record.assignments
            ],
        )

    # Infeasible: report the certificate and do NOT store anything.
    body = InfeasibleResponse(
        stored=False,
        total_demand=result.total_demand,
        total_assigned=result.total_assigned,
        shortfall=result.total_demand - result.total_assigned,
        unmet=[
            UnmetOut(
                manuscript_id=u.manuscript_id,
                reviews_needed=u.reviews_needed,
                reviews_assigned=u.reviews_assigned,
                shortfall=u.shortfall,
                eligible_reviewers=u.eligible_reviewers,
                reasons=list(u.reasons),
            )
            for u in result.unmet
        ],
        witness=WitnessOut(**result.witness),
        bottleneck_reviewers=[
            BottleneckOut(
                reviewer_id=b.reviewer_id,
                capacity=b.capacity,
                assigned=b.assigned,
            )
            for b in result.bottleneck_reviewers
        ],
        topic_gaps=[
            TopicGapOut(
                topic=t.topic,
                demand=t.demand,
                matched=t.matched,
                gap=t.gap,
                reviewer_capacity=t.reviewer_capacity,
                eligible_reviewer_count=t.eligible_reviewer_count,
                manuscripts=list(t.manuscripts),
            )
            for t in result.topic_gaps
        ],
    )
    return JSONResponse(status_code=409, content=body.model_dump())


@app.get("/assignments", tags=["assignment"], summary="List stored feasible assignments")
def list_assignments() -> dict:
    return {"count": store.count()}


@app.get(
    "/assignments/{assignment_id}",
    tags=["assignment"],
    summary="Fetch a previously computed feasible assignment",
)
def get_assignment(assignment_id: str):
    record = store.get(assignment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="assignment not found")
    return FeasibleResponse(
        assignment_id=record.assignment_id,
        total_demand=record.total_demand,
        total_assigned=record.total_assigned,
        assignments=[
            AssignmentOut(manuscript_id=a.manuscript_id, reviewer_id=a.reviewer_id)
            for a in record.assignments
        ],
    )
