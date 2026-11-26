from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import insert, select

from src.domain import scenario
from src.models.cases import cases
from src.models.drill import drill_batches
from .audit import record

# Drill copies live as cases too, but they belong to the drill module. Keep them
# out of the ordinary materials directory so staff and outsource surfaces never
# blur original batches with practice copies.
_drill_case_ids = select(drill_batches.c.case_id)


def get(db, case_id):
    entry = db.execute(select(cases).where(cases.c.id == case_id)).mappings().first()
    if entry is None:
        raise HTTPException(404, "资料不存在")
    return dict(entry)


def list_entries(db):
    query = (
        select(cases)
        .where(~cases.c.id.in_(_drill_case_ids))
        .order_by(cases.c.id.desc())
        .limit(100)
    )
    return [dict(row) for row in db.execute(query).mappings()]


def create(db, data, actor):
    validator = getattr(scenario, "validate", None)
    if validator is not None:
        try:
            validator(data.payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    change = db.execute(insert(cases).values(**data.model_dump(), code=f"CASE-{uuid4().hex[:12].upper()}", created_by=actor))
    case_id = change.inserted_primary_key[0]
    record(db, "create_case", actor, "case", case_id)
    return get(db, case_id)
