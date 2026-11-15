import { useRef, useState, type FormEvent } from "react";
import { ApiError } from "../api";
import type { AcademicAnswer } from "../types";
import { useWorkspace } from "../workspaceScope";

const MAX_QUESTION_LENGTH = 4096;
const ERRORS: Readonly<Record<string, string>> = {
  INVALID_REQUEST: "Escribe una pregunta de entre 1 y 4096 caracteres.",
  REQUEST_TOO_LARGE: "La pregunta excede el tamaño admitido.",
  ENGINE_UNAVAILABLE: "El motor académico no está disponible en este momento.",
  RAG_RETRIEVAL_ERROR: "El motor devolvió datos incompletos de las fuentes.",
  RAG_NOT_CONFIGURED: "La generación de respuestas requiere configuración en el servidor.",
  RAG_PROVIDER_ERROR: "El proveedor no pudo generar una respuesta.",
  RAG_PROVIDER_TIMEOUT: "El proveedor tardó demasiado. Puedes volver a enviar la pregunta.",
};

interface Exchange {
  question: string;
  reply: AcademicAnswer;
}

interface ChatError {
  message: string;
  requestId?: string;
}

function describeError(cause: unknown): ChatError {
  if (cause instanceof ApiError) {
    const error = cause.envelope?.error;
    return {
      message: (error && Object.hasOwn(ERRORS, error.code) ? ERRORS[error.code] : undefined) ??
        "El servidor no pudo completar la consulta.",
      requestId: error?.request_id,
    };
  }
  return { message: "No se pudo conectar con el servidor. Puedes volver a enviar la pregunta." };
}

function ExchangeView({ question, reply }: Exchange) {
  return (
    <article className="academic-exchange">
      <h3 className="academic-question">{question}</h3>
      {reply.status === "no_context" ? (
        <p className="academic-empty">No se encontraron pasajes que coincidan con la pregunta.</p>
      ) : (
        <>
          <p className="academic-answer">{reply.answer}</p>
          <ul className="academic-sources" aria-label="Fuentes consultadas">
            {reply.sources.map((source) => (
              <li key={source.chunk_id}>
                <details>
                  <summary>
                    <span className="academic-source-title">[{source.label}] {source.title}</span>
                    <span className="academic-source-meta">{source.authors} · {source.year}</span>
                  </summary>
                  <p className="academic-source-text">{source.content}</p>
                </details>
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}

export default function AcademicChat() {
  const { api, id } = useWorkspace();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ChatError | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const inFlight = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (inFlight.current || !question || question.length > MAX_QUESTION_LENGTH) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    input.current?.focus();
    try {
      const reply = await api.askAcademic(question);
      setExchanges((previous) => [{ question, reply }, ...previous]);
      setDraft("");
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  const title = id("academic-chat-title");
  const questionId = id("academic-question");
  return (
    <section className="panel academic-chat" aria-labelledby={title}>
      <div className="academic-content">
        <h2 id={title} className="panel-title">Consulta los papers</h2>
        <form className="academic-form" onSubmit={(event) => void ask(event)}>
          <label htmlFor={questionId}>Pregunta</label>
          <textarea
            id={questionId}
            ref={input}
            value={draft}
            maxLength={MAX_QUESTION_LENGTH}
            rows={3}
            readOnly={pending}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="How does HNSW use a hierarchy of proximity graphs?"
          />
          <div className="academic-actions">
            <button className="primary" type="submit" disabled={pending || !draft.trim()}>Preguntar</button>
            <span className="muted small" role="status">
              {pending ? "Consultando los papers y preparando la respuesta…" :
                exchanges.length > 0 && error === null ? "Respuesta disponible." : ""}
            </span>
          </div>
        </form>
        {error && (
          <div className="error-box" role="alert">
            {error.message}
            {error.requestId && <span className="academic-request-id">Solicitud <code>{error.requestId}</code></span>}
          </div>
        )}
        <div className="academic-history" aria-busy={pending}>
          {exchanges.map((exchange, index) => (
            <ExchangeView key={exchanges.length - index} {...exchange} />
          ))}
        </div>
      </div>
    </section>
  );
}
