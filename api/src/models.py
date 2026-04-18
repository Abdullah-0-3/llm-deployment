from pydantic import BaseModel, Field


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    source: str = Field(default="manual", max_length=200)


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(default=3, ge=1, le=10)


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


class RagSearchMatch(BaseModel):
    source: str
    content: str
    distance: float


class RagSearchResponse(BaseModel):
    query: str
    matches: list[RagSearchMatch]


class RagSourceItem(BaseModel):
    source: str
    chunk_count: int
    last_updated: str


class RagSourcesResponse(BaseModel):
    sources: list[RagSourceItem]


class DeleteRagSourceResponse(BaseModel):
    source: str
    deleted_chunks: int


class SessionIdItem(BaseModel):
    session_id: str
    message_count: int
    last_updated: str


class SessionIdsResponse(BaseModel):
    sessions: list[SessionIdItem]
