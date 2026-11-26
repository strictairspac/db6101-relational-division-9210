from fastapi import APIRouter, Depends, HTTPException, Response

from src.config.resources import engine
from src.constants.job_state import JobState
from src.controllers.access import drill_author, drill_reader, drill_runner
from src.schemas.drills import (
    DrillAppend,
    DrillAppendResult,
    DrillCreate,
    DrillRunEntry,
    DrillSessionDetail,
    DrillSessionEntry,
)
from src.services import drills
from src.utils.serial import canonical_json

router = APIRouter(prefix="/drills", tags=["Drills"])


def _run_entry(batch, run):
    # Expose only drill-scoped fields; never the underlying case id.
    return {
        "id": run["id"],
        "status": run["status"],
        "parameter": run["parameter"],
        "parameter_label": drills._label(run["parameter"]),
        "actor": run["actor"],
        "created_at": run["created_at"],
        "finished_at": run["finished_at"],
        "result": run["result"],
        "failure": run["failure"],
        "digest": run["digest"],
        "batch_id": batch["id"],
        "session_id": batch["session_id"],
    }


@router.get("", response_model=list[DrillSessionEntry], dependencies=[Depends(drill_reader)])
def list_sessions():
    with engine.connect() as db:
        return drills.list_sessions(db)


@router.post("", response_model=DrillSessionDetail, status_code=201)
def create_session(form: DrillCreate, user=Depends(drill_author)):
    with engine.begin() as db:
        return drills.create_session(db, form, user["username"])


@router.get("/{session_id}", response_model=DrillSessionDetail)
def session_detail(session_id: int, user=Depends(drill_reader)):
    with engine.connect() as db:
        return drills.session_detail(db, session_id)


@router.post("/{session_id}/batches", response_model=DrillAppendResult)
def append_batches(session_id: int, form: DrillAppend, user=Depends(drill_author)):
    with engine.begin() as db:
        return drills.append(db, session_id, form, user["username"])


def _batch(db, session_id, batch_id):
    drills._session(db, session_id)
    return drills.get_batch(db, session_id, batch_id)


@router.get("/{session_id}/batches/{batch_id}/runs", response_model=list[DrillRunEntry])
def list_batch_runs(session_id: int, batch_id: int, user=Depends(drill_reader)):
    with engine.connect() as db:
        batch = _batch(db, session_id, batch_id)
        return [_run_entry(batch, run) for run in drills.batch_runs(db, batch)]


@router.post("/{session_id}/batches/{batch_id}/runs", response_model=DrillRunEntry, status_code=202)
def rerun_batch(session_id: int, batch_id: int, user=Depends(drill_runner)):
    # Operators and outsource accounts may both rerun a copy; runs are scoped to
    # the drill batch, so no original case or batch id is ever touched.
    with engine.begin() as db:
        run = drills.rerun(db, session_id, batch_id, user["username"])
        batch = drills.get_batch(db, session_id, batch_id)
        return _run_entry(batch, run)


@router.get("/{session_id}/batches/{batch_id}/runs/{run_id}", response_model=DrillRunEntry)
def run_detail(session_id: int, batch_id: int, run_id: int, user=Depends(drill_reader)):
    with engine.connect() as db:
        batch = _batch(db, session_id, batch_id)
        run = drills.run_view(db, session_id, batch_id, run_id)
        return _run_entry(batch, run)


@router.get("/{session_id}/batches/{batch_id}/runs/{run_id}/export")
def export_run(session_id: int, batch_id: int, run_id: int, user=Depends(drill_reader)):
    with engine.connect() as db:
        batch = _batch(db, session_id, batch_id)
        run = drills.run_view(db, session_id, batch_id, run_id)
        if run["status"] != JobState.DONE:
            raise HTTPException(409, "没有可导出的执行结果")
        payload = {
            "session": session_id,
            "batch": batch["ordinal"],
            "parameter": run["parameter"],
            "result": run["result"],
            "digest": run["digest"],
            "finished_at": run["finished_at"],
        }
    return Response(canonical_json(payload), media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=drill-{session_id}-{batch_id}-{run_id}.json",
    })
