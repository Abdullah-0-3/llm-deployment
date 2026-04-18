import { FormEvent, useMemo, useState } from "react";

type GenerateResponse = {
  response?: string;
  detail?: string;
};

type SubmitResponse = {
  task_id: string;
  status: string;
};

type ResultResponse = {
  task_id: string;
  status: string;
  result?: { response?: string };
  error?: string;
};

type IngestResponse = {
  source: string;
  chunks_stored: number;
};

type RagSearchResponse = {
  query: string;
  matches: Array<{ source: string; content: string; distance: number }>;
};

const API_BASE = "/api";

async function postJson<T>(path: string, apiKey: string, body: object): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey
    },
    body: JSON.stringify(body)
  });

  const payload = await response.json();
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "Request failed";
    throw new Error(detail);
  }

  return payload as T;
}

async function getJson<T>(path: string, apiKey: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "X-API-Key": apiKey
    }
  });

  const payload = await response.json();
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "Request failed";
    throw new Error(detail);
  }

  return payload as T;
}

export default function App() {
  const [apiKey, setApiKey] = useState("adminLLM");
  const [prompt, setPrompt] = useState("Do I like apples?");
  const [sessionId, setSessionId] = useState("");
  const [syncResult, setSyncResult] = useState("");
  const [syncLoading, setSyncLoading] = useState(false);

  const [asyncPrompt, setAsyncPrompt] = useState("Explain caching in one paragraph.");
  const [taskId, setTaskId] = useState("");
  const [asyncResult, setAsyncResult] = useState("");
  const [asyncLoading, setAsyncLoading] = useState(false);

  const [source, setSource] = useState("notes");
  const [ingestText, setIngestText] = useState("Apples are rich in fiber and vitamin C.");
  const [ingestResult, setIngestResult] = useState("");
  const [ingestLoading, setIngestLoading] = useState(false);

  const [ragQuery, setRagQuery] = useState("Are apples healthy?");
  const [ragLimit, setRagLimit] = useState(3);
  const [ragResult, setRagResult] = useState("");
  const [ragLoading, setRagLoading] = useState(false);

  const [healthStatus, setHealthStatus] = useState("unknown");
  const [error, setError] = useState("");

  const cleanSession = useMemo(() => sessionId.trim(), [sessionId]);

  async function checkHealth() {
    try {
      const response = await fetch(`${API_BASE}/`);
      if (!response.ok) {
        throw new Error("health check failed");
      }
      setHealthStatus("healthy");
    } catch {
      setHealthStatus("unreachable");
    }
  }

  async function handleGenerate(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSyncLoading(true);
    try {
      const payload = await postJson<GenerateResponse>("/generate", apiKey, {
        prompt,
        session_id: cleanSession || undefined
      });
      setSyncResult(payload.response ?? payload.detail ?? "No response body");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Generate failed");
    } finally {
      setSyncLoading(false);
    }
  }

  async function handleSubmitAsync() {
    setError("");
    setAsyncLoading(true);
    try {
      const submitted = await postJson<SubmitResponse>("/submit", apiKey, { prompt: asyncPrompt });
      setTaskId(submitted.task_id);
      setAsyncResult(`Task queued: ${submitted.task_id}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Submit failed");
    } finally {
      setAsyncLoading(false);
    }
  }

  async function handlePollResult() {
    if (!taskId.trim()) {
      setError("Enter a task id first.");
      return;
    }

    setError("");
    setAsyncLoading(true);
    try {
      const result = await getJson<ResultResponse>(`/result/${taskId.trim()}`, apiKey);
      if (result.status === "completed") {
        setAsyncResult(result.result?.response ?? JSON.stringify(result.result));
      } else if (result.status === "failed") {
        setAsyncResult(result.error ?? "Task failed");
      } else {
        setAsyncResult(`Task status: ${result.status}`);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Poll failed");
    } finally {
      setAsyncLoading(false);
    }
  }

  async function handleIngest() {
    setError("");
    setIngestLoading(true);
    try {
      const payload = await postJson<IngestResponse>("/ingest", apiKey, {
        source,
        text: ingestText
      });
      setIngestResult(`Source: ${payload.source} | Chunks: ${payload.chunks_stored}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Ingest failed");
    } finally {
      setIngestLoading(false);
    }
  }

  async function handleRagSearch() {
    setError("");
    setRagLoading(true);
    try {
      const payload = await postJson<RagSearchResponse>("/rag/search", apiKey, {
        query: ragQuery,
        limit: ragLimit
      });

      const formatted = payload.matches.length
        ? payload.matches
            .map(
              (match, index) =>
                `${index + 1}. [${match.source}] distance=${match.distance.toFixed(4)}\n${match.content}`
            )
            .join("\n\n")
        : "No matches";

      setRagResult(formatted);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "RAG search failed");
    } finally {
      setRagLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">LLMOps Console</p>
          <h1>Minimal Control Surface</h1>
        </div>
        <div className="status-wrap">
          <span className={`status-pill ${healthStatus}`}>API: {healthStatus}</span>
          <button className="ghost-btn" onClick={checkHealth} type="button">
            Check Health
          </button>
        </div>
      </header>

      <main className="grid">
        <section className="card">
          <h2>Sync Generate</h2>
          <form onSubmit={handleGenerate} className="form">
            <label>
              API Key
              <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
            </label>
            <label>
              Session ID (optional)
              <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} />
            </label>
            <label>
              Prompt
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={4} />
            </label>
            <button disabled={syncLoading} type="submit" className="primary-btn">
              {syncLoading ? "Generating..." : "Generate"}
            </button>
          </form>
          <pre className="result-box">{syncResult || "Response will appear here."}</pre>
        </section>

        <section className="card">
          <h2>Async Queue</h2>
          <div className="form">
            <label>
              Prompt
              <textarea value={asyncPrompt} onChange={(event) => setAsyncPrompt(event.target.value)} rows={3} />
            </label>
            <div className="row-actions">
              <button disabled={asyncLoading} className="primary-btn" type="button" onClick={handleSubmitAsync}>
                Submit Task
              </button>
              <button disabled={asyncLoading} className="ghost-btn" type="button" onClick={handlePollResult}>
                Poll Result
              </button>
            </div>
            <label>
              Task ID
              <input value={taskId} onChange={(event) => setTaskId(event.target.value)} />
            </label>
          </div>
          <pre className="result-box">{asyncResult || "Async status/result will appear here."}</pre>
        </section>

        <section className="card">
          <h2>RAG Ingest</h2>
          <div className="form">
            <label>
              Source
              <input value={source} onChange={(event) => setSource(event.target.value)} />
            </label>
            <label>
              Knowledge Text
              <textarea value={ingestText} onChange={(event) => setIngestText(event.target.value)} rows={4} />
            </label>
            <button disabled={ingestLoading} className="primary-btn" type="button" onClick={handleIngest}>
              {ingestLoading ? "Ingesting..." : "Ingest"}
            </button>
          </div>
          <pre className="result-box">{ingestResult || "Ingest summary will appear here."}</pre>
        </section>

        <section className="card">
          <h2>RAG Search Debug</h2>
          <div className="form">
            <label>
              Query
              <input value={ragQuery} onChange={(event) => setRagQuery(event.target.value)} />
            </label>
            <label>
              Limit
              <input
                type="number"
                min={1}
                max={10}
                value={ragLimit}
                onChange={(event) => setRagLimit(Number(event.target.value))}
              />
            </label>
            <button disabled={ragLoading} className="primary-btn" type="button" onClick={handleRagSearch}>
              {ragLoading ? "Searching..." : "Search"}
            </button>
          </div>
          <pre className="result-box">{ragResult || "Matches will appear here."}</pre>
        </section>
      </main>

      {error ? <div className="error-banner">{error}</div> : null}
    </div>
  );
}
