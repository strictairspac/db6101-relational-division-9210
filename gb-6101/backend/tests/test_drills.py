"""
Drill-copy tests. They run only when DRILL_TEST_DATABASE_URL points at a throwaway
PostgreSQL database (the schema is dropped and recreated). Without it the module
is skipped so the default image has no test database dependency.

    DRILL_TEST_DATABASE_URL=postgresql+psycopg://... pytest backend/tests
"""
import os
import sys
import threading

import pytest

URL = os.environ.get("DRILL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set DRILL_TEST_DATABASE_URL to run drill tests")


@pytest.fixture(scope="module")
def engine():
    os.environ["DATABASE_URL"] = URL
    os.environ["JWT_SECRET"] = "drill-test"
    os.environ["DEMO_PASSWORD"] = "Demo-DbWorkbench-2026"
    import fakeredis  # pytest-only dependency
    import redis

    redis.Redis.from_url = classmethod(lambda cls, *a, **k: fakeredis.FakeRedis())

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from src.models import audit, cases, drill, reviews, runs, users  # noqa: F401  (register metadata)
    from src.models.base import metadata
    from src.config.resources import engine as db_engine
    from scripts.seed_demo import seed, setup_schema

    with db_engine.begin() as db:
        metadata.drop_all(db)
    setup_schema()
    seed()
    return db_engine


def _drain():
    from src.services.execution import service_one
    while service_one():
        pass


def _done_run(engine, minute, code="YP-1124-AM"):
    from sqlalchemy import select
    from src.models.cases import cases
    from src.services import runs

    with engine.begin() as db:
        case_id = db.execute(select(cases.c.id).where(cases.c.code == code)).scalar_one()
        run_id = runs.enqueue(db, case_id, minute, "operator")["id"]
    _drain()
    return run_id


def _rows(engine, run_id):
    from src.services import runs
    with engine.connect() as db:
        return runs.get(db, run_id)["result"]["rows"]


def test_drill_reproduces_decision_and_uses_code_names(engine):
    from sqlalchemy import select
    from src.schemas.drills import DrillCreate
    from src.models.drill import drill_aliases
    from src.services import drills

    source = _done_run(engine, 480)
    original = {row["车辆"]: (row["放行决定"], row["交接备注"], row["证据诊断"]) for row in _rows(engine, source)}

    with engine.begin() as db:
        session = drills.create_session(db, DrillCreate(title="重算演练", source_run_ids=[source]), "operator")
    _drain()
    assert session["batch_count"] == 1
    code_names = session["batches"][0]["vehicles"]
    assert len(code_names) == len(original)
    assert not set(code_names) & set(original)  # no original plate survives

    with engine.connect() as db:
        mapping = dict(db.execute(select(drill_aliases.c.original_asset, drill_aliases.c.alias)).all())
        batch = drills.get_batch(db, session["id"], session["batches"][0]["id"])
        run_id = drills.batch_runs(db, batch)[0]["id"]
    drill_rows = {row["车辆"]: (row["放行决定"], row["交接备注"], row["证据诊断"]) for row in _rows(engine, run_id)}
    assert drill_rows == {mapping[orig]: value for orig, value in original.items()}


def test_same_scene_keeps_alias_and_new_scene_changes_it(engine):
    from src.schemas.drills import DrillCreate
    from src.services import drills

    a = _done_run(engine, 480)
    b = _done_run(engine, 470)
    c = _done_run(engine, 460)
    with engine.begin() as db:
        s1 = drills.create_session(db, DrillCreate(title="场一", source_run_ids=[a, b]), "operator")
    # Same original plates -> identical code names across both batches.
    assert s1["batches"][0]["vehicles"] == s1["batches"][1]["vehicles"]
    # Different cars within the scene get different code names.
    names = s1["batches"][0]["vehicles"]
    assert len(set(names)) == len(names)

    # Appending another batch of the same material keeps the same code names.
    from src.schemas.drills import DrillAppend
    with engine.begin() as db:
        appended = drills.append(db, s1["id"], DrillAppend(source_run_ids=[c]), "operator")
    assert appended["session"]["batches"][-1]["vehicles"] == names

    # A new scene regenerates every code name.
    with engine.begin() as db:
        s2 = drills.create_session(db, DrillCreate(title="场二", source_run_ids=[a]), "operator")
    assert set(s2["batches"][0]["vehicles"]).isdisjoint(names)


def test_append_is_idempotent_and_reports_failures(engine):
    from src.schemas.drills import DrillAppend, DrillCreate
    from src.services import drills

    a = _done_run(engine, 480)
    b = _done_run(engine, 470)
    with engine.begin() as db:
        session = drills.create_session(db, DrillCreate(title="追加", source_run_ids=[a]), "operator")
    sid = session["id"]
    with engine.begin() as db:
        first = drills.append(db, sid, DrillAppend(source_run_ids=[b, 999999]), "operator")
    assert first["created"] and first["failed"] and first["failed"][0]["source_run_id"] == 999999
    count = first["session"]["batch_count"]
    with engine.begin() as db:
        repeat = drills.append(db, sid, DrillAppend(source_run_ids=[b]), "operator")
    assert repeat["created"] == [] and repeat["existing"] == [b]
    assert repeat["session"]["batch_count"] == count


def test_concurrent_appends_do_not_duplicate_batches(engine):
    from sqlalchemy import select
    from src.models.drill import drill_batches
    from src.schemas.drills import DrillAppend, DrillCreate
    from src.services import drills

    a = _done_run(engine, 480)
    b = _done_run(engine, 470)
    c = _done_run(engine, 460)
    with engine.begin() as db:
        session = drills.create_session(db, DrillCreate(title="并发", source_run_ids=[a]), "operator")
    sid = session["id"]
    barrier = threading.Barrier(2)

    def work(name, ids):
        barrier.wait()
        with engine.begin() as db:
            drills.append(db, sid, DrillAppend(source_run_ids=ids), name)

    t1 = threading.Thread(target=work, args=("甲", [b, c]))
    t2 = threading.Thread(target=work, args=("乙", [c, b]))
    t1.start(); t2.start(); t1.join(); t2.join()

    with engine.connect() as db:
        sources = db.execute(select(drill_batches.c.source_run_id).where(
            drill_batches.c.session_id == sid
        )).scalars().all()
    assert len(sources) == len(set(sources)), "a batch was duplicated by concurrent appends"
    assert sorted(sources) == sorted([a, b, c])


def test_mismatched_source_is_rejected(engine):
    from sqlalchemy import insert
    from src.models.cases import cases as case_table
    from src.models.runs import runs as run_table
    from src.schemas.drills import DrillCreate
    from src.services import drills

    payload = {
        "vehicles": [{"asset": "Q1", "category": "电动"}],
        "requirements": [{"category": "电动", "check": "制动"}],
        "evidence": [{"seq": 1, "asset": "Q1", "check": "制动", "checked": 450, "expires": 570, "status": "pass"}],
    }
    wrong = [{"车辆": "Q1", "车型": "电动", "放行决定": "停放", "交接备注": "制动", "证据诊断": "制动（无当时回执）"}]
    with engine.begin() as db:
        case_id = db.execute(insert(case_table).values(
            code="CASE-MISMATCH", title="合成原件", description="", payload=payload, created_by="seed",
        )).inserted_primary_key[0]
        run_id = db.execute(insert(run_table).values(
            case_id=case_id, status="done", parameter=480, actor="seed", created_at=1, finished_at=2,
            result={"summary": "x", "metrics": {}, "rows": wrong}, digest="x",
        )).inserted_primary_key[0]
    with pytest.raises(Exception) as exc:
        with engine.begin() as db:
            drills.create_session(db, DrillCreate(title="不一致", source_run_ids=[run_id]), "operator")
    assert "不一致" in str(exc.value)


def test_outsource_isolation(engine):
    from fastapi.testclient import TestClient
    from src.main import app as fastapi_app

    with TestClient(fastapi_app) as client:
        def headers(user):
            token = client.post(
                "/auth/login", json={"username": user, "password": "Demo-DbWorkbench-2026"}
            ).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        out = headers("outsource")
        for path in ("/cases", "/runs", "/audit"):
            assert client.get(path, headers=out).status_code == 403
        listing = client.get("/drills", headers=out)
        assert listing.status_code == 200
        if listing.json():
            sid = listing.json()[0]["id"]
            body = client.get(f"/drills/{sid}", headers=out).text
            for leak in ("YP-T12", "YP-1124-AM", "CASE-"):
                assert leak not in body
        assert client.post("/drills", headers=out, json={"title": "x y", "source_run_ids": [1]}).status_code == 403
