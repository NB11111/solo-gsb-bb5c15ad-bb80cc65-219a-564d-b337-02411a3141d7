# Anonymous Review Assignment API

A FastAPI service that assigns reviewers to manuscripts (submissions) using a
single **global maximum-flow** computation. It enforces topic competence,
conflicts of interest and reviewer capacities simultaneously — it never makes
per-manuscript greedy decisions.

## Quick start (one command)

```bash
docker compose up --build
```

Then open:

| What | Address |
| --- | --- |
| Health check | http://localhost:8000/health |
| Interactive API docs (Swagger UI) | http://localhost:8000/docs |
| OpenAPI schema | http://localhost:8000/openapi.json |
| Assignment endpoint | `POST http://localhost:8000/assign` |

To use a different host port:

```bash
HOST_PORT=9000 docker compose up --build      # -> http://localhost:9000
```

To stop: `docker compose down`.

Dependencies are installed during the image build and the API starts with the
container — there is no separate initialization step.

## Configuration

All configuration is optional (defaults in parentheses). Set them via the
`environment:` block in `compose.yaml` or as shell environment variables.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEFAULT_REVIEWS_PER_MANUSCRIPT` | `2` | Reviews required per manuscript when a request does not specify `reviews_per_manuscript` or a per-manuscript override |
| `MAX_MANUSCRIPTS` | `10000` | Reject requests with more manuscripts than this (HTTP 422) |
| `MAX_REVIEWERS` | `10000` | Reject requests with more reviewers than this (HTTP 422) |
| `HOST_PORT` | `8000` | Host-side port published by Docker Compose |

## API

### `GET /health`

Returns `{"status": "ok", "stored_assignments": N}`.

### `POST /assign`

Request body:

```json
{
  "manuscripts": [
    {
      "manuscript_id": "m1",
      "authors": ["alice@example.org"],
      "topics": ["ml", "nlp"],
      "reviews_needed": 2
    }
  ],
  "reviewers": [
    {
      "reviewer_id": "r1",
      "topics": ["ml"],
      "conflicts": ["m2"],
      "capacity": 3
    }
  ],
  "reviews_per_manuscript": 2
}
```

Field semantics:

- `reviews_per_manuscript` (optional, default `2`) applies to every
  manuscript; a manuscript may override it with its own `reviews_needed`.
- A reviewer is **eligible** for a manuscript iff their topics intersect the
  manuscript's topics **and** no conflict applies.
- `conflicts` lists manuscript IDs the reviewer must not review. It also acts
  as an affiliation rule: if the reviewer is blocked from a manuscript whose
  `authors` overlap another manuscript's authors, that manuscript is blocked
  too.
- `capacity` is the maximum number of manuscripts the reviewer can be
  assigned. One manuscript never gets the same reviewer twice.

#### Feasible result — `200 OK`

```json
{
  "status": "feasible",
  "assignment_id": "9aa4b8eb7e1cf8f110eefff2939ea6d8",
  "total_demand": 4,
  "total_assigned": 4,
  "assignments": [
    {"manuscript_id": "m1", "reviewer_id": "r2"},
    {"manuscript_id": "m1", "reviewer_id": "r3"},
    {"manuscript_id": "m2", "reviewer_id": "r1"},
    {"manuscript_id": "m2", "reviewer_id": "r4"}
  ]
}
```

The assignment is stored in memory and can be fetched again with
`GET /assignments/{assignment_id}` (`GET /assignments` lists the count).

#### Infeasible result — `409 Conflict`

When no assignment can satisfy every manuscript, **no partial result is
written** (`"stored": false`) and the response explains exactly what is
missing:

```json
{
  "status": "infeasible",
  "stored": false,
  "total_demand": 2,
  "total_assigned": 0,
  "shortfall": 2,
  "unmet": [
    {
      "manuscript_id": "m1",
      "reviews_needed": 2,
      "reviews_assigned": 0,
      "shortfall": 2,
      "eligible_reviewers": 0,
      "reasons": ["no reviewer covers any of the manuscript's topics without conflict"]
    }
  ],
  "witness": {
    "manuscript_ids": ["m1"],
    "neighbour_reviewer_ids": [],
    "reviewer_ids_in_cut": [],
    "demand_of_manuscript_set": 2,
    "neighbour_capacity": 0,
    "restricted_max_assignable": 0,
    "gap": 2,
    "shortfall": 2
  },
  "bottleneck_reviewers": [],
  "topic_gaps": [
    {
      "topic": "ml", "demand": 2, "matched": 0, "gap": 2,
      "reviewer_capacity": 5, "eligible_reviewer_count": 1,
      "manuscripts": ["m1"]
    }
  ]
}
```

Diagnostic fields:

- **`unmet`** — every manuscript that cannot be fully served, with its demand,
  how many reviews the global flow still secured for it, the shortfall, its
  number of eligible reviewers, and a human-readable reason (candidate
  shortage vs. capacity shortage).
- **`witness`** — the exact infeasibility certificate. The manuscripts on the
  source side of the minimum cut (a Hall set) jointly demand
  `demand_of_manuscript_set` reviews; restricted to those manuscripts and
  their eligible reviewers, at most `restricted_max_assignable` reviews can be
  placed, leaving `gap` unsatisfiable.
- **`bottleneck_reviewers`** — reviewers whose capacity is fully saturated by
  the flow (the capacities that bind).
- **`topic_gaps`** — one independent max-flow per topic, giving the exact
  candidate/capacity shortage per topic area (topic demands can overlap, so
  these are diagnostics, not a partition).

Validation errors (duplicate ids, conflicts referencing unknown manuscripts,
negative capacities, oversized requests, etc.) return `422` with a detailed
message.

## Why a global flow and not greedy?

The problem is a bipartite b-matching, modelled as:

```
source ──capacity=reviews_needed──> manuscript
manuscript ──capacity=1──> reviewer   (edge exists only when eligible)
reviewer ──capacity=capacity──> sink
```

Dinic's algorithm computes the maximum flow over the **entire** network at
once. All demands are satisfied iff max flow equals total demand; otherwise
the residual graph's source-reachable set yields the minimum-cut witness. A
per-manuscript greedy algorithm can fail on perfectly feasible inputs: e.g.
taking a rare shared reviewer for an early manuscript starves a later
manuscript that had no alternative. The test
`test_global_flow_beats_greedy_ordering` pins exactly such a case.

## Determinism

Identical requests always produce identical output:

1. manuscripts and reviewers are sorted by id before building the network;
2. the Dinic implementation preserves edge insertion order in every
   traversal;
3. the returned assignment list is sorted by `(manuscript_id, reviewer_id)`;
4. `assignment_id` is a SHA-256 hash of a canonical (order-independent)
   rendering of the request, so reordering arrays in the JSON still returns
   the same id and the same assignment.

## Local development (without Docker)

Requires Python 3.11+.

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
pytest -q
```

## Project layout

```
app/
  flow.py      deterministic Dinic max-flow
  matcher.py   network construction, global solve, infeasibility diagnosis
  schemas.py   request/response models and input validation
  store.py     in-memory store for feasible assignments (canonical hashing)
  config.py    environment-based configuration
  main.py      FastAPI routes
tests/         API and algorithm tests
Dockerfile, compose.yaml, requirements.txt
```
