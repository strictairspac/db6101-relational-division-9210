from pydantic import BaseModel, Field, field_validator

from src.constants.job_state import JobState


class DrillCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    source_run_ids: list[int] = Field(min_length=1, max_length=50)

    @field_validator("title")
    @classmethod
    def check_title(cls, title):
        if len(title.strip()) < 2:
            raise ValueError("请输入至少两个字符的演练名称")
        return title.strip()

    @field_validator("source_run_ids")
    @classmethod
    def check_sources(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("同一历史批次不能重复加入")
        return values


class DrillAppend(BaseModel):
    source_run_ids: list[int] = Field(min_length=1, max_length=50)

    @field_validator("source_run_ids")
    @classmethod
    def check_sources(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("同一历史批次不能重复加入")
        return values


class DrillBatchEntry(BaseModel):
    id: int
    ordinal: int
    label: str
    kind: str
    state: str
    parameter: int
    parameter_label: str
    vehicles: list[str]


class DrillSessionEntry(BaseModel):
    id: int
    code: str
    title: str
    created_by: str
    created_at: int
    batch_count: int


class DrillSessionDetail(DrillSessionEntry):
    batches: list[DrillBatchEntry]


class DrillAppendResult(BaseModel):
    session: DrillSessionDetail
    created: list[int]
    existing: list[int]
    failed: list[dict]


class DrillRunEntry(BaseModel):
    id: int
    batch_id: int
    session_id: int
    status: JobState
    parameter: int
    parameter_label: str
    actor: str
    created_at: int
    finished_at: int | None
    result: dict | None
    failure: str | None
    digest: str | None
