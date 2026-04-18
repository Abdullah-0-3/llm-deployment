from pydantic import BaseModel, Field


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    source: str = Field(default="manual", max_length=200)


class SubmitResponse(BaseModel):
    task_id: str
    status: str


class ResultResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None
    error: str | None = None


class IngestResponse(BaseModel):
    source: str
    chunks_stored: int
