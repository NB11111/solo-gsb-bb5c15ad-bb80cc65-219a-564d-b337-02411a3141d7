"""End-to-end tests using FastAPI's TestClient."""

from fastapi.testclient import TestClient

from app.main import app, store

client = TestClient(app)


def setup_function(_):
    store._records.clear()


def post(req):
    return client.post("/assign", json=req)


# ---------------------------------------------------------------------------
# basics
# ---------------------------------------------------------------------------

def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root_and_docs():
    assert client.get("/").status_code == 200
    assert client.get("/docs").status_code == 200


# ---------------------------------------------------------------------------
# feasible global assignment
# ---------------------------------------------------------------------------

def test_simple_feasible_assignment():
    req = {
        "manuscripts": [
            {"manuscript_id": "m1", "authors": ["a1"], "topics": ["ml"]},
            {"manuscript_id": "m2", "authors": ["a2"], "topics": ["nlp"]},
        ],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml", "nlp"], "conflicts": [], "capacity": 2},
            {"reviewer_id": "r2", "topics": ["ml"], "conflicts": [], "capacity": 1},
            {"reviewer_id": "r3", "topics": ["nlp"], "conflicts": [], "capacity": 1},
        ],
        "reviews_per_manuscript": 2,
    }
    r = post(req)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "feasible"
    assert body["total_demand"] == 4
    assert body["total_assigned"] == 4

    per_m = {}
    per_r = {}
    for a in body["assignments"]:
        per_m.setdefault(a["manuscript_id"], set()).add(a["reviewer_id"])
        per_r[a["reviewer_id"]] = per_r.get(a["reviewer_id"], 0) + 1
    assert per_m["m1"] == {"r1", "r2"}
    assert per_m["m2"] == {"r1", "r3"}
    assert all(c <= 2 for c in per_r.values())
    # same manuscript-reviewer pair never repeats (unit edges)
    assert len(body["assignments"]) == len({(a["manuscript_id"], a["reviewer_id"])
                                            for a in body["assignments"]})


def test_conflict_and_topics_respected():
    req = {
        "manuscripts": [
            {"manuscript_id": "m1", "authors": ["alice"], "topics": ["ml"]},
        ],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml"], "conflicts": ["m1"], "capacity": 5},
            {"reviewer_id": "r2", "topics": ["db"], "conflicts": [], "capacity": 5},
        ],
        "reviews_per_manuscript": 1,
    }
    r = post(req)
    # r1 is conflicted, r2 has no matching topic -> no eligible reviewer
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "infeasible"
    assert body["shortfall"] == 1
    assert body["unmet"][0]["manuscript_id"] == "m1"
    assert body["unmet"][0]["eligible_reviewers"] == 0
    assert not body["stored"]


def test_affiliation_conflict_via_shared_author():
    # r1 is blocked from m1; m2 shares author bob with m1, so r1 must also be
    # excluded from m2 even though m2 is not named in the conflict list.
    req = {
        "manuscripts": [
            {"manuscript_id": "m1", "authors": ["bob"], "topics": ["ml"]},
            {"manuscript_id": "m2", "authors": ["bob", "carol"], "topics": ["ml"]},
        ],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml"], "conflicts": ["m1"], "capacity": 2},
        ],
        "reviews_per_manuscript": 1,
    }
    r = post(req)
    assert r.status_code == 409
    assert {u["manuscript_id"] for u in r.json()["unmet"]} == {"m1", "m2"}


def test_capacity_constraint_holds():
    req = {
        "manuscripts": [
            {"manuscript_id": f"m{i}", "authors": [], "topics": ["ml"]}
            for i in range(3)
        ],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml"], "conflicts": [], "capacity": 2},
        ],
        "reviews_per_manuscript": 1,
    }
    r = post(req)
    assert r.status_code == 409
    body = r.json()
    assert body["shortfall"] == 1
    assert body["witness"]["demand_of_manuscript_set"] == 3
    bn = {b["reviewer_id"]: b for b in body["bottleneck_reviewers"]}
    assert bn["r1"]["assigned"] == 2 and bn["r1"]["capacity"] == 2
    tg = body["topic_gaps"][0]
    assert tg["topic"] == "ml"
    assert tg["gap"] == 1
    assert tg["reviewer_capacity"] == 2
    # infeasible request was not stored
    assert client.get("/assignments").json()["count"] == 0
    assert client.get(f"/assignments/{'x' * 32}").status_code == 404


# ---------------------------------------------------------------------------
# the key requirement: global flow succeeds where per-manuscript greedy fails
# ---------------------------------------------------------------------------

def test_global_flow_beats_greedy_ordering():
    # Classic greedy trap:
    #   m1 (ml)  eligible {r1, r2, r3}, needs 2
    #   m2 (nlp) eligible {r1, r4},       needs 2 (both are mandatory)
    # capacities are all 1 and sum exactly to total demand 4.
    # A greedy process that handles m1 first, taking the first available
    # reviewers r1+r2, leaves m2 with only r4 -> infeasible.  The global
    # maximum flow reserves r1 for m2 and assigns r2+r3 to m1.
    req = {
        "manuscripts": [
            {"manuscript_id": "m1", "authors": [], "topics": ["ml"]},
            {"manuscript_id": "m2", "authors": [], "topics": ["nlp"]},
        ],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml", "nlp"], "conflicts": [], "capacity": 1},
            {"reviewer_id": "r2", "topics": ["ml"], "conflicts": [], "capacity": 1},
            {"reviewer_id": "r3", "topics": ["ml"], "conflicts": [], "capacity": 1},
            {"reviewer_id": "r4", "topics": ["nlp"], "conflicts": [], "capacity": 1},
        ],
        "reviews_per_manuscript": 2,
    }
    r = post(req)
    assert r.status_code == 200, r.text
    pairs = {(a["manuscript_id"], a["reviewer_id"]) for a in r.json()["assignments"]}
    assert pairs == {("m1", "r2"), ("m1", "r3"), ("m2", "r1"), ("m2", "r4")}


def test_greedy_trap_with_shuffled_input_still_feasible_and_identical():
    base = {
        "manuscripts": [
            {"manuscript_id": "m2", "authors": [], "topics": ["nlp"]},
            {"manuscript_id": "m1", "authors": [], "topics": ["ml"]},
        ],
        "reviewers": [
            {"reviewer_id": "r3", "topics": ["ml"], "conflicts": [], "capacity": 1},
            {"reviewer_id": "r1", "topics": ["nlp", "ml"], "conflicts": [], "capacity": 1},
            {"reviewer_id": "r4", "topics": ["nlp"], "conflicts": [], "capacity": 1},
            {"reviewer_id": "r2", "topics": ["ml"], "conflicts": [], "capacity": 1},
        ],
        "reviews_per_manuscript": 2,
    }
    r1 = post(base)
    assert r1.status_code == 200
    # canonical same request (different order, duplicated fields) -> same id
    shuffled = {
        "reviewers": list(reversed(base["reviewers"])),
        "manuscripts": list(reversed(base["manuscripts"])),
        "reviews_per_manuscript": 2,
    }
    r2 = post(shuffled)
    assert r2.status_code == 200
    assert r1.json()["assignment_id"] == r2.json()["assignment_id"]
    assert r1.json()["assignments"] == r2.json()["assignments"]
    # stored once and fetchable
    assert client.get("/assignments").json()["count"] == 1
    aid = r1.json()["assignment_id"]
    got = client.get(f"/assignments/{aid}")
    assert got.status_code == 200
    assert got.json()["assignments"] == r1.json()["assignments"]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def test_validation_errors():
    # duplicate manuscript ids
    bad = {
        "manuscripts": [
            {"manuscript_id": "m1", "topics": ["ml"]},
            {"manuscript_id": "m1", "topics": ["db"]},
        ],
        "reviewers": [{"reviewer_id": "r1", "topics": ["ml"], "capacity": 1}],
    }
    assert post(bad).status_code == 422

    # conflict referencing unknown manuscript
    bad2 = {
        "manuscripts": [{"manuscript_id": "m1", "topics": ["ml"]}],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml"], "conflicts": ["nope"], "capacity": 1}
        ],
    }
    assert post(bad2).status_code == 422

    # negative capacity
    bad3 = {
        "manuscripts": [{"manuscript_id": "m1", "topics": ["ml"]}],
        "reviewers": [{"reviewer_id": "r1", "topics": ["ml"], "capacity": -1}],
    }
    assert post(bad3).status_code == 422


def test_default_reviews_per_manuscript_when_field_omitted():
    req = {
        "manuscripts": [{"manuscript_id": "m1", "topics": ["ml"]}],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml"], "capacity": 1},
            {"reviewer_id": "r2", "topics": ["ml"], "capacity": 1},
        ],
    }
    r = post(req)
    assert r.status_code == 200, r.text
    assert len(r.json()["assignments"]) == 2  # default is 2


def test_per_manuscript_override():
    req = {
        "manuscripts": [
            {"manuscript_id": "m1", "topics": ["ml"], "reviews_needed": 1},
            {"manuscript_id": "m2", "topics": ["ml"], "reviews_needed": 2},
        ],
        "reviewers": [
            {"reviewer_id": "r1", "topics": ["ml"], "capacity": 2},
            {"reviewer_id": "r2", "topics": ["ml"], "capacity": 2},
        ],
        "reviews_per_manuscript": 3,
    }
    r = post(req)
    assert r.status_code == 200, r.text
    counts = {}
    for a in r.json()["assignments"]:
        counts[a["manuscript_id"]] = counts.get(a["manuscript_id"], 0) + 1
    assert counts == {"m1": 1, "m2": 2}
