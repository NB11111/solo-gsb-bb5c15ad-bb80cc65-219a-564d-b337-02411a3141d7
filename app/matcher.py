"""Global review assignment via maximum flow, plus infeasibility diagnosis.

Network model (integer units of review assignments):

    source -> manuscript   capacity = reviews needed for that manuscript
    manuscript -> reviewer capacity = 1, present iff the reviewer is *eligible*
    reviewer -> sink       capacity = reviewer's assignment capacity

A reviewer is eligible for a manuscript when their topic areas intersect the
manuscript's topics AND no conflict of interest is declared (either the
reviewer is globally blocked from the manuscript or shares an affiliation
with one of the manuscript's authors).

The network is solved once with Dinic's algorithm, so the result is a global
optimum (total reviews assigned), not a sequence of local per-manuscript
greedy choices.

Feasibility is exact: all demands are satisfied iff max flow equals total
demand.  When it does not, the residual-graph reachable set is a *witness*
(a Hall-set certificate) and topic-local subflows pinpoint where capacity or
candidates are missing.
"""

from dataclasses import dataclass, field

from .flow import Dinic


@dataclass(frozen=True)
class ReviewerInput:
    reviewer_id: str
    topics: frozenset[str]
    conflicts: frozenset[str]  # manuscript ids blocked for this reviewer
    capacity: int


@dataclass(frozen=True)
class ManuscriptInput:
    manuscript_id: str
    authors: tuple[str, ...]
    topics: frozenset[str]
    reviews_needed: int


@dataclass(frozen=True)
class Assignment:
    manuscript_id: str
    reviewer_id: str


@dataclass(frozen=True)
class UnmetManuscript:
    manuscript_id: str
    reviews_needed: int
    reviews_assigned: int
    shortfall: int
    eligible_reviewers: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BottleneckReviewer:
    reviewer_id: str
    capacity: int
    assigned: int


@dataclass(frozen=True)
class TopicGap:
    topic: str
    demand: int          # manuscript review demand carrying this topic
    matched: int         # max reviews matchable using only reviewers of topic
    gap: int
    reviewer_capacity: int
    eligible_reviewer_count: int
    manuscripts: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    feasible: bool
    total_demand: int
    total_assigned: int
    assignments: list[Assignment] = field(default_factory=list)
    # infeasibility diagnostics (populated only when feasible is False)
    unmet: list[UnmetManuscript] = field(default_factory=list)
    witness: dict = field(default_factory=dict)
    bottleneck_reviewers: list[BottleneckReviewer] = field(default_factory=list)
    topic_gaps: list[TopicGap] = field(default_factory=list)


def _eligible(
    m: ManuscriptInput,
    r: ReviewerInput,
    manuscript_authors: dict[str, frozenset[str]],
) -> bool:
    if not (m.topics & r.topics):
        return False
    if m.manuscript_id in r.conflicts:
        return False
    # affiliation-level conflicts: shared author id between this manuscript
    # and any manuscript the reviewer is blocked from
    if r.conflicts and m.authors:
        blocked_authors: set[str] = set()
        for other_id in r.conflicts:
            blocked_authors.update(manuscript_authors.get(other_id, ()))
        if blocked_authors & set(m.authors):
            return False
    return True


def solve(
    manuscripts: list[ManuscriptInput],
    reviewers: list[ReviewerInput],
) -> MatchResult:
    """Compute the assignment for pre-validated, de-duplicated inputs.

    Input order is the authoritative ordering for tie-breaking: callers
    sort by id beforehand to get stable results.
    """
    n_m = len(manuscripts)
    n_r = len(reviewers)
    src = 0
    m0 = 1                       # first manuscript node
    r0 = m0 + n_m                # first reviewer node
    sink = r0 + n_r
    dinic = Dinic(sink + 1)

    # source -> manuscript (demand), reviewer -> sink (capacity)
    for i, m in enumerate(manuscripts):
        dinic.add_edge(src, m0 + i, max(0, m.reviews_needed))
    for j, r in enumerate(reviewers):
        dinic.add_edge(r0 + j, sink, max(0, r.capacity))

    # manuscript -> reviewer, unit capacity, eligibility filtered
    mr_edges: dict[tuple[int, int], object] = {}
    eligibility: list[list[int]] = [[] for _ in range(n_m)]
    manuscript_authors = {m.manuscript_id: frozenset(m.authors) for m in manuscripts}
    for i, m in enumerate(manuscripts):
        for j, r in enumerate(reviewers):
            if _eligible(m, r, manuscript_authors):
                mr_edges[(i, j)] = dinic.add_edge(m0 + i, r0 + j, 1)
                eligibility[i].append(j)

    total_demand = sum(max(0, m.reviews_needed) for m in manuscripts)
    total_assigned = dinic.max_flow(src, sink)

    # extract which manuscript->reviewer edges carry flow
    per_manuscript_assigned = [0] * n_m
    per_reviewer_assigned = [0] * n_r
    assignments: list[Assignment] = []
    for (i, j), edge in mr_edges.items():
        # initial capacity was 1; residual capacity 0 => saturated => used
        if edge.cap == 0:
            per_manuscript_assigned[i] += 1
            per_reviewer_assigned[j] += 1
            assignments.append(
                Assignment(manuscripts[i].manuscript_id, reviewers[j].reviewer_id)
            )

    if total_assigned == total_demand:
        return MatchResult(
            feasible=True,
            total_demand=total_demand,
            total_assigned=total_assigned,
            assignments=assignments,
        )

    return _infeasible_result(
        dinic=dinic,
        src=src,
        m0=m0,
        r0=r0,
        manuscripts=manuscripts,
        reviewers=reviewers,
        eligibility=eligibility,
        per_manuscript_assigned=per_manuscript_assigned,
        per_reviewer_assigned=per_reviewer_assigned,
        total_demand=total_demand,
        total_assigned=total_assigned,
    )


def _infeasible_result(
    *,
    dinic: Dinic,
    src: int,
    m0: int,
    r0: int,
    manuscripts: list[ManuscriptInput],
    reviewers: list[ReviewerInput],
    eligibility: list[list[int]],
    per_manuscript_assigned: list[int],
    per_reviewer_assigned: list[int],
    total_demand: int,
    total_assigned: int,
) -> MatchResult:
    n_m = len(manuscripts)
    n_r = len(reviewers)
    reachable = dinic.residual_reachable(src)

    # Hall witness: manuscripts on the source side of the minimum cut.
    p_star = [i for i in range(n_m) if reachable[m0 + i]]
    r_reach = [j for j in range(n_r) if reachable[r0 + j]]

    p_star_demand = sum(manuscripts[i].reviews_needed for i in p_star)

    # Neighbourhood N(P*): every reviewer eligible for at least one manuscript
    # in the witness set, regardless of which cut side the main flow placed
    # them on.  Hall's theorem for b-matching certifies infeasibility via
    # demand(P*) > capacity(N(P*)); recompute the restriction exactly.
    neighbour_pos = sorted(
        {
            j
            for i in p_star
            for j in eligibility[i]
        }
    )
    neighbour_capacity = sum(reviewers[j].capacity for j in neighbour_pos)
    sub_matched = _restricted_flow(
        manuscripts, reviewers, eligibility, p_star, neighbour_pos
    )
    witness_gap = p_star_demand - sub_matched

    # Per-manuscript diagnosis.
    unmet: list[UnmetManuscript] = []
    for i in p_star:
        m = manuscripts[i]
        got = per_manuscript_assigned[i]
        shortfall = m.reviews_needed - got
        if shortfall <= 0:
            continue
        reasons = []
        if not eligibility[i]:
            reasons.append("no reviewer covers any of the manuscript's topics without conflict")
        elif len(eligibility[i]) < m.reviews_needed:
            reasons.append(
                f"only {len(eligibility[i])} eligible reviewer(s) "
                f"but {m.reviews_needed} required"
            )
        else:
            reasons.append("eligible reviewers exhausted by global capacity/conflict constraints")
        unmet.append(
            UnmetManuscript(
                manuscript_id=m.manuscript_id,
                reviews_needed=m.reviews_needed,
                reviews_assigned=got,
                shortfall=shortfall,
                eligible_reviewers=len(eligibility[i]),
                reasons=tuple(reasons),
            )
        )
    # If an uncovered manuscript somehow is not in p_star, still report it
    # (defensive; max flow guarantees cannot happen for unit edges).
    reported = {u.manuscript_id for u in unmet}
    for i, m in enumerate(manuscripts):
        if m.manuscript_id in reported:
            continue
        shortfall = m.reviews_needed - per_manuscript_assigned[i]
        if shortfall > 0:
            unmet.append(
                UnmetManuscript(
                    manuscript_id=m.manuscript_id,
                    reviews_needed=m.reviews_needed,
                    reviews_assigned=per_manuscript_assigned[i],
                    shortfall=shortfall,
                    eligible_reviewers=len(eligibility[i]),
                    reasons=(
                        "not enough reviewer capacity across eligible reviewers",
                    ),
                )
            )
    unmet.sort(key=lambda u: (-u.shortfall, u.manuscript_id))

    # Bottleneck reviewers: saturated (capacity fully used), source-side
    # reviewers first; these are the binding capacities in the min cut.
    bottleneck: list[BottleneckReviewer] = []
    bottleneck_pos: dict[str, int] = {}
    for j in range(n_r):
        r = reviewers[j]
        if r.capacity > 0 and per_reviewer_assigned[j] >= r.capacity:
            bottleneck.append(
                BottleneckReviewer(
                    reviewer_id=r.reviewer_id,
                    capacity=r.capacity,
                    assigned=per_reviewer_assigned[j],
                )
            )
            bottleneck_pos[r.reviewer_id] = j
    r_reach_set = set(r_reach)
    bottleneck.sort(
        key=lambda b: (
            0 if bottleneck_pos[b.reviewer_id] in r_reach_set else 1,
            -b.capacity,
            b.reviewer_id,
        )
    )

    # Topic-local subflows: rerun max flow per topic so each topic's own
    # capacity shortage gets an exact certificate.  Demands overlap between
    # topics, so these numbers are per-topic diagnostics, not a partition.
    topic_gaps = _topic_gaps(manuscripts, reviewers)

    witness = {
        "manuscript_ids": [manuscripts[i].manuscript_id for i in p_star],
        "neighbour_reviewer_ids": [reviewers[j].reviewer_id for j in neighbour_pos],
        "reviewer_ids_in_cut": [reviewers[j].reviewer_id for j in r_reach],
        "demand_of_manuscript_set": p_star_demand,
        "neighbour_capacity": neighbour_capacity,
        "restricted_max_assignable": sub_matched,
        "gap": witness_gap,
        "shortfall": total_demand - total_assigned,
    }

    return MatchResult(
        feasible=False,
        total_demand=total_demand,
        total_assigned=total_assigned,
        unmet=unmet,
        witness=witness,
        bottleneck_reviewers=bottleneck,
        topic_gaps=topic_gaps,
    )


def _restricted_flow(
    manuscripts: list[ManuscriptInput],
    reviewers: list[ReviewerInput],
    eligibility: list[list[int]],
    manuscript_positions: list[int],
    reviewer_positions: list[int],
) -> int:
    """Max reviews assignable from the given manuscript subset to the given
    reviewer subset, respecting eligibility and capacities.

    This is an exact max flow on the restricted network; it is used to give
    the Hall certificate a precise shortage number.
    """
    mps = list(manuscript_positions)
    rps = set(reviewer_positions)
    n_m = len(mps)
    n_r = len(rps)
    if n_m == 0 or n_r == 0:
        return 0
    r_index = {j: b for b, j in enumerate(reviewer_positions)}
    src = 0
    m0 = 1
    r0 = m0 + n_m
    sink = r0 + n_r
    d = Dinic(sink + 1)
    for a, i in enumerate(mps):
        d.add_edge(src, m0 + a, manuscripts[i].reviews_needed)
    for j in rps:
        d.add_edge(r0 + r_index[j], sink, reviewers[j].capacity)
    for a, i in enumerate(mps):
        for j in eligibility[i]:
            if j in r_index:
                d.add_edge(m0 + a, r0 + r_index[j], 1)
    return d.max_flow(src, sink)


def _topic_gaps(
    manuscripts: list[ManuscriptInput],
    reviewers: list[ReviewerInput],
) -> list[TopicGap]:
    """Per-topic feasibility certificate via an independent small max flow."""
    all_topics = sorted({t for m in manuscripts for t in m.topics})
    gaps: list[TopicGap] = []
    for topic in all_topics:
        t_manuscripts = [m for m in manuscripts if topic in m.topics]
        t_reviewers = [r for r in reviewers if topic in r.topics]
        if not t_manuscripts or not t_reviewers:
            continue
        demand = sum(m.reviews_needed for m in t_manuscripts)
        capacity = sum(max(0, r.capacity) for r in t_reviewers)

        n_m = len(t_manuscripts)
        n_r = len(t_reviewers)
        src = 0
        m0 = 1
        r0 = m0 + n_m
        sink = r0 + n_r
        d = Dinic(sink + 1)
        for i, m in enumerate(t_manuscripts):
            d.add_edge(src, m0 + i, m.reviews_needed)
        for j, r in enumerate(t_reviewers):
            d.add_edge(r0 + j, sink, max(0, r.capacity))
        for i, m in enumerate(t_manuscripts):
            for j, r in enumerate(t_reviewers):
                if m.manuscript_id in r.conflicts:
                    continue
                if r.conflicts and m.authors:
                    blocked_authors: set[str] = set()
                    for other_id in r.conflicts:
                        for mm in manuscripts:
                            if mm.manuscript_id == other_id:
                                blocked_authors.update(mm.authors)
                    if blocked_authors & set(m.authors):
                        continue
                d.add_edge(m0 + i, r0 + j, 1)
        matched = d.max_flow(src, sink)
        gap = demand - matched
        if gap <= 0:
            continue
        gaps.append(
            TopicGap(
                topic=topic,
                demand=demand,
                matched=matched,
                gap=gap,
                reviewer_capacity=capacity,
                eligible_reviewer_count=len(t_reviewers),
                manuscripts=tuple(sorted(m.manuscript_id for m in t_manuscripts)),
            )
        )
    gaps.sort(key=lambda g: (-g.gap, g.topic))
    return gaps
