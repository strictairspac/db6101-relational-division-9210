"""Drill copies ("演练副本").

An operator copies historical hand-over batches into a practice session ("场").
The copy is a fresh case whose vehicles are replaced by per-session code names
("代号"): the same original vehicle keeps one code name for every batch and
every later append of that session, while a new session regenerates all code
names. The copy keeps the source batch's review minute, so the recompute must
reproduce the original release decision and missing-item reasons exactly.

Outsource accounts only ever see drill data, never the original case, original
batch number or original vehicle number.
"""
import secrets
from time import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from src.config.resources import engine
from src.constants.job_state import JobState
from src.domain import scenario
from src.models.cases import cases
from src.models.drill import drill_aliases, drill_batches, drill_sessions
from src.models.runs import runs
from . import audit, runs as run_service

ALIAS_PREFIX = "车辆"
BATCH_STATE_READY = "ready"


class DrillSourceError(Exception):
    """A source batch cannot be copied as-is; a request may keep its other batches."""


def _tag():
    return secrets.token_hex(3).upper()


def _alias(tag, ordinal):
    # The session tag keeps a vehicle's code name different from one drill
    # session to the next; the ordinal keeps different vehicles apart and stable
    # for every batch and later append within the same session.
    return f"{ALIAS_PREFIX}-{tag}-{ordinal:02d}"


def _label(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _batch_label(ordinal):
    return f"演练批次 {ordinal}"


def _source(db, run_id):
    row = db.execute(
        select(runs.c.id, runs.c.case_id, runs.c.status, runs.c.parameter, runs.c.result, cases.c.payload)
        .join(cases, cases.c.id == runs.c.case_id)
        .where(runs.c.id == run_id)
    ).mappings().first()
    if row is None:
        raise DrillSourceError(f"历史批次 {run_id} 不存在")
    if row["status"] != JobState.DONE:
        raise DrillSourceError(f"历史批次 {run_id} 尚未执行成功")
    if not row["result"] or not isinstance(row["result"].get("rows"), list):
        raise DrillSourceError(f"历史批次 {run_id} 缺少可复演的判定结果")
    # Only original hand-over batches seed a drill. Copying a copy would alias
    # already-aliased vehicles and blur which scene the code names belong to.
    nested = db.scalar(select(drill_batches.c.id).where(drill_batches.c.case_id == row["case_id"]))
    if nested is not None:
        raise DrillSourceError(f"历史批次 {run_id} 属于演练副本，不能再次复制")
    return dict(row)


def _assets(payload):
    return [row["asset"] for row in payload["vehicles"]]


def _anonymize(payload, mapping):
    return {
        "vehicles": [{**row, "asset": mapping[row["asset"]]} for row in payload["vehicles"]],
        "requirements": payload["requirements"],
        "evidence": [{**row, "asset": mapping[row["asset"]]} for row in payload["evidence"]],
    }


def _original_decisions(result, mapping):
    """The original order's per-vehicle decision, keyed by the drill code name."""
    expected = {}
    for row in result["rows"]:
        asset = row.get("车辆")
        if asset not in mapping:
            raise DrillSourceError(f"原单包含未在车辆表中的车辆 {asset}")
        expected[mapping[asset]] = (
            row.get("放行决定"), row.get("交接备注"), row.get("证据诊断"),
        )
    return expected


def _recompute(anonymized, parameter):
    """Run the copy on a fresh connection so temporary staging tables never leak
    into the caller's transaction, then return decisions keyed by code name."""
    with engine.begin() as probe:
        rows = scenario.run(anonymized, parameter, probe)["rows"]
    return {row["车辆"]: (row["放行决定"], row["交接备注"], row["证据诊断"]) for row in rows}


def _session(db, session_id):
    row = db.execute(select(drill_sessions).where(drill_sessions.c.id == session_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "演练场不存在")
    return dict(row)


def _alias_state(db, session_id):
    rows = db.execute(
        select(drill_aliases.c.original_asset, drill_aliases.c.alias, drill_aliases.c.ordinal)
        .where(drill_aliases.c.session_id == session_id)
    ).mappings().all()
    alias_for = {row["original_asset"]: row["alias"] for row in rows}
    next_ordinal = max((row["ordinal"] for row in rows), default=0) + 1
    return alias_for, next_ordinal


def _assign_aliases(payload, tag, alias_for, next_ordinal):
    mapping, fresh = {}, []
    ordinal = next_ordinal
    for asset in _assets(payload):
        if asset in alias_for:
            mapping[asset] = alias_for[asset]
        else:
            mapping[asset] = _alias(tag, ordinal)
            fresh.append((asset, mapping[asset], ordinal))
            ordinal += 1
    return mapping, fresh, ordinal


def _copy_batch(db, session, source, alias_for, next_alias_ordinal, batch_ordinal, kind, actor):
    """Build one drill batch inside a savepoint, so a failure leaves no partial
    aliases, case, batch or run behind. The copy is only persisted after its
    recompute is proven identical to the original order at the same minute.
    """
    payload = source["payload"]
    parameter = source["parameter"]
    mapping, fresh, next_alias_ordinal = _assign_aliases(
        payload, session["tag"], alias_for, next_alias_ordinal,
    )
    anonymized = _anonymize(payload, mapping)
    try:
        expected = _original_decisions(source["result"], mapping)
        actual = _recompute(anonymized, parameter)
    except ValueError as exc:
        raise DrillSourceError(f"原件无法重算：{exc}") from exc
    if expected != actual:
        raise DrillSourceError("演练结果与原单不一致，未创建副本")

    with db.begin_nested():
        for asset, code, ordinal in fresh:
            db.execute(insert(drill_aliases).values(
                session_id=session["id"], original_asset=asset, alias=code, ordinal=ordinal,
            ))
        entry = db.execute(insert(cases).values(
            code=f"CASE-{uuid4().hex[:12].upper()}",
            title=f"{session['title']} · {_batch_label(batch_ordinal)}",
            description="演练副本，车辆已用本场代号替换。",
            payload=anonymized,
            created_by=actor,
        ))
        case_id = entry.inserted_primary_key[0]
        batch = db.execute(insert(drill_batches).values(
            session_id=session["id"], case_id=case_id, source_run_id=source["id"],
            parameter=parameter, ordinal=batch_ordinal, kind=kind, state=BATCH_STATE_READY,
            created_by=actor, created_at=int(time()),
        ))
        batch_id = batch.inserted_primary_key[0]
        run_service.enqueue(db, case_id, parameter, actor)

    for asset, code, _ in fresh:
        alias_for[asset] = code
    return batch_id, next_alias_ordinal


def _next_batch_ordinal(db, session_id):
    return (db.scalar(select(func.max(drill_batches.c.ordinal)).where(
        drill_batches.c.session_id == session_id
    )) or 0) + 1


def _new_session(db, data, actor):
    """Insert a session, regenerating the scene tag on the (rare) unique clash."""
    for _ in range(5):
        try:
            with db.begin_nested():
                session_id = db.execute(insert(drill_sessions).values(
                    code=f"DRILL-{uuid4().hex[:10].upper()}",
                    tag=_tag(),
                    title=data.title,
                    created_by=actor,
                    created_at=int(time()),
                )).inserted_primary_key[0]
            return session_id
        except IntegrityError:
            continue
    raise HTTPException(503, "建立演练场时发生冲突，请重试")


def create_session(db, data, actor):
    sources = []
    for run_id in data.source_run_ids:
        try:
            sources.append(_source(db, run_id))
        except DrillSourceError as exc:
            raise HTTPException(422, str(exc)) from exc

    session_id = _new_session(db, data, actor)
    session = _session(db, session_id)
    alias_for, next_alias_ordinal = {}, 1
    batch_ordinal = 1
    for source in sources:
        # Creation is all-or-nothing: any failure rolls back the whole session.
        try:
            _, next_alias_ordinal = _copy_batch(
                db, session, source, alias_for, next_alias_ordinal, batch_ordinal, "initial", actor,
            )
        except DrillSourceError as exc:
            raise HTTPException(422, str(exc)) from exc
        batch_ordinal += 1
    audit.record(db, "create_drill", actor, "drill", session_id)
    return session_detail(db, session_id)


def append(db, session_id, data, actor):
    # Serialise concurrent appends on the session row, so two operators filling
    # the same session cannot interleave alias or batch allocation. Each batch is
    # committed whole inside its own savepoint before the writer moves on.
    locked = db.execute(
        select(drill_sessions.c.id).where(drill_sessions.c.id == session_id).with_for_update()
    ).first()
    if locked is None:
        raise HTTPException(404, "演练场不存在")
    session = _session(db, session_id)
    existing = set(db.scalars(select(drill_batches.c.source_run_id).where(
        drill_batches.c.session_id == session_id
    )))
    alias_for, next_alias_ordinal = _alias_state(db, session_id)
    batch_ordinal = _next_batch_ordinal(db, session_id)
    created, skipped, failed = [], [], []
    for run_id in data.source_run_ids:
        if run_id in existing:
            skipped.append(run_id)
            continue
        try:
            source = _source(db, run_id)
            batch_id, next_alias_ordinal = _copy_batch(
                db, session, source, alias_for, next_alias_ordinal, batch_ordinal, "append", actor,
            )
        except DrillSourceError as exc:
            failed.append({"source_run_id": run_id, "reason": str(exc)})
            continue
        created.append(batch_id)
        existing.add(run_id)
        batch_ordinal += 1
    if created:
        audit.record(db, "append_drill", actor, "drill", session_id)
    return {
        "session": session_detail(db, session_id),
        "created": created,
        "existing": skipped,
        "failed": failed,
    }


def list_sessions(db):
    rows = db.execute(
        select(drill_sessions, func.count(drill_batches.c.id).label("batch_count"))
        .outerjoin(drill_batches, drill_batches.c.session_id == drill_sessions.c.id)
        .group_by(drill_sessions.c.id)
        .order_by(drill_sessions.c.id.desc())
        .limit(100)
    ).mappings().all()
    return [dict(row) for row in rows]


def _vehicles(payload):
    return [row["asset"] for row in payload["vehicles"]]


def session_detail(db, session_id):
    session = _session(db, session_id)
    rows = db.execute(
        select(drill_batches, cases.c.payload)
        .join(cases, cases.c.id == drill_batches.c.case_id)
        .where(drill_batches.c.session_id == session_id, drill_batches.c.state == BATCH_STATE_READY)
        .order_by(drill_batches.c.ordinal)
    ).mappings().all()
    batches = [{
        "id": row["id"],
        "ordinal": row["ordinal"],
        "label": _batch_label(row["ordinal"]),
        "kind": row["kind"],
        "state": row["state"],
        "parameter": row["parameter"],
        "parameter_label": _label(row["parameter"]),
        "vehicles": _vehicles(row["payload"]),
    } for row in rows]
    return {**session, "batch_count": len(batches), "batches": batches}


def get_batch(db, session_id, batch_id):
    row = db.execute(
        select(drill_batches).where(
            drill_batches.c.id == batch_id, drill_batches.c.session_id == session_id,
        )
    ).mappings().first()
    if row is None or row["state"] != BATCH_STATE_READY:
        raise HTTPException(404, "演练批次不存在")
    return dict(row)


def batch_runs(db, batch):
    rows = db.execute(
        select(runs).where(runs.c.case_id == batch["case_id"]).order_by(runs.c.id.desc())
    ).mappings().all()
    return [dict(row) for row in rows]


def rerun(db, session_id, batch_id, actor):
    _session(db, session_id)
    batch = get_batch(db, session_id, batch_id)
    run = run_service.enqueue(db, batch["case_id"], batch["parameter"], actor)
    audit.record(db, "drill_run", actor, "drill", session_id)
    return run


def run_view(db, session_id, batch_id, run_id):
    _session(db, session_id)
    batch = get_batch(db, session_id, batch_id)
    row = db.execute(select(runs).where(
        runs.c.id == run_id, runs.c.case_id == batch["case_id"],
    )).mappings().first()
    if row is None:
        raise HTTPException(404, "演练执行不存在")
    return dict(row)
