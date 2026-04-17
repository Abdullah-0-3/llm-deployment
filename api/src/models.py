from pydantic import BaseModel, Field


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)


class SubmitResponse(BaseModel):
    task_id: str
    status: str


class ResultResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None
    error: str | None = None
