import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, RotateCcw, Sparkles } from "lucide-react";
import { api } from "../services/assetApi";
import { VisualGrid } from "./Visual";

// ids the backend cites: INS-0001-0203, MNT-…, REG-…, CTX-…, USR-…, and document chunks (sop:…, manual:…, report:…, note:…)
const ID = /\[?((?:INS|MNT|REG|CTX|USR)-\d{4}-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|(?:manual|sop|report|note):[\w.:-]*\w)\]?/g;
const cache = new Map();

export function Citation({ id }) {
  const [card, setCard] = useState(cache.get(id) ?? null);

  const load = () => {
    if (cache.get(id)) return setCard(cache.get(id));
    if (cache.has(id)) return;
    cache.set(id, null);
    api
      .evidence(id)
      .then((c) => cache.set(id, c))
      .catch(() => cache.set(id, { title: id, snippet: "No further detail is available for this record.", source: "" }))
      .finally(() => setCard(cache.get(id)));
  };

  return (
    <span className='citation' tabIndex={0} onMouseEnter={load} onFocus={load}>
      {id}
      <span className='citation-popover' role='tooltip'>
        {card ? (
          <>
            <strong>{card.title}</strong>
            <p>{card.snippet}</p>
            <small>{card.source}</small>
          </>
        ) : (
          <p>Loading the record…</p>
        )}
      </span>
    </span>
  );
}

const markdownComponents = {
  a: ({ href, children, ...rest }) =>
    href?.startsWith("#cite-") ? (
      <Citation id={decodeURIComponent(href.slice(6))} />
    ) : (
      <a href={href} target='_blank' rel='noreferrer' {...rest}>
        {children}
      </a>
    ),
  table: ({ children }) => (
    <div className='table-shell'>
      <table>{children}</table>
    </div>
  ),
};

const linkIds = (text) => text.replace(ID, (_, id) => `[${id}](#cite-${encodeURIComponent(id)})`);

// every visual of an answer; older stored answers only have a single `view`
const visualsOf = (payload) => payload?.visuals ?? (payload?.view ? [{ id: "v0", view: payload.view }] : []);

function CopyButton({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type='button'
      onClick={() => {
        navigator.clipboard?.writeText(text).catch(() => {});
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}>
      {done ? <Check size={13} /> : <Copy size={13} />}
      {done ? "Copied" : "Copy"}
    </button>
  );
}

export default function ChatMessage({ message, onRegenerate, onRetry }) {
  if (message.role === "user") {
    return (
      <div className='msg user'>
        <div className='user-bubble'>{message.text}</div>
      </div>
    );
  }

  const payload = message.payload;
  const visuals = visualsOf(payload);
  const sources = payload?.evidence ?? [];

  return (
    <div className='msg assistant'>
      <div className='assistant-mark' aria-hidden='true'>
        <Sparkles size={15} />
      </div>
      <div className='assistant-body'>
        {message.pending && (
          <div className='thinking' role='status'>
            <span className='dots'>
              <i />
              <i />
              <i />
            </span>
            Querying the field database… free-tier models can take up to a minute.
          </div>
        )}

        {message.error && (
          <div className='error-note' role='alert'>
            <strong>That didn't work.</strong>
            <p>{message.error}</p>
            {message.retry && (
              <button type='button' onClick={() => onRetry(message.retry)}>
                <RotateCcw size={13} /> Try again
              </button>
            )}
          </div>
        )}

        {message.text && (
          <div className='markdown'>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents} urlTransform={(u) => u}>
              {linkIds(message.text)}
            </ReactMarkdown>
          </div>
        )}

        {visuals.length > 0 && <VisualGrid items={visuals} />}

        {(payload?.steps?.length > 0 || sources.length > 0) && (
          <div className='meta-rows'>
            {payload?.steps?.length > 0 && (
              <details>
                <summary>How this was answered ({payload.steps.length})</summary>
                <ul>
                  {payload.steps.map((s, i) => (
                    <li key={i}>
                      {s.label.replace(/\.\.\.$/, "")}
                      <small> · {s.error ? "failed" : `${s.rows} rows`}</small>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {sources.length > 0 && (
              <details>
                <summary>Sources ({sources.length})</summary>
                <div className='source-list'>
                  {sources.slice(0, 40).map((id) => (
                    <Citation key={id} id={id} />
                  ))}
                </div>
              </details>
            )}
          </div>
        )}

        {message.text && (
          <div className='msg-actions'>
            <CopyButton text={message.text} />
            <button type='button' onClick={onRegenerate}>
              <RotateCcw size={13} />
              Regenerate
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
