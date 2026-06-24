import { useState, useRef } from "react";

// Point this at your FastAPI backend.
const API = "http://localhost:8000";
const TICKERS = ["RELIANCE", "TCS", "INFY"];

// Pretty-print a tool call line: fn(arg=value)
function CallLine({ name, args }) {
  const inner = Object.entries(args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");
  return (
    <div className="call">
      <span className="fn">{name}</span>(<span className="arg">{inner}</span>)
    </div>
  );
}

// Split the agent's final text into "VERDICT" + thesis body.
function parseVerdict(text) {
  const lines = text.trim().split("\n");
  const first = (lines[0] || "").toUpperCase().replace(/[^A-Z]/g, "");
  const known = ["BUY", "SELL", "HOLD"].includes(first) ? first : null;
  const body = known ? lines.slice(1).join("\n").trim() : text.trim();
  return { verdict: known, body };
}

export default function App() {
  const [ticker, setTicker] = useState("RELIANCE");
  const [events, setEvents] = useState([]);
  const [running, setRunning] = useState(false);
  const esRef = useRef(null);

  function run() {
    if (esRef.current) esRef.current.close();
    setEvents([]);
    setRunning(true);

    // EventSource = the browser's built-in SSE client. It reconnects and
    // parses `data:` frames for us; we just react to each event.
    const es = new EventSource(`${API}/api/analyze?ticker=${ticker}`);
    esRef.current = es;

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") {
        es.close();
        setRunning(false);
        return;
      }
      setEvents((prev) => [...prev, ev]);
    };

    es.onerror = () => {
      es.close();
      setRunning(false);
      setEvents((prev) => [...prev, { type: "error", text: "Stream dropped. Is the backend running?" }]);
    };
  }

  return (
    <div className="wrap">
      <div className="eyebrow">Agentic AI · NSE equities · live reasoning</div>
      <h1>Autonomous Equity Research Agent</h1>
      <p className="sub">
        One prompt in. The agent plans, calls its own data and generation tools,
        reasons over what it finds, and returns a verdict — watch it think.
      </p>

      <div className="controls">
        {TICKERS.map((t) => (
          <button
            key={t}
            className="chip"
            aria-pressed={ticker === t}
            onClick={() => setTicker(t)}
            disabled={running}
          >
            {t}
          </button>
        ))}
        <button className="run" onClick={run} disabled={running}>
          {running ? "Agent working…" : "Run agent"}
        </button>
      </div>

      {events.length === 0 && !running && (
        <div className="empty">Pick a stock and run the agent. Each step streams in as it happens.</div>
      )}

      <div className="spine">
        {events.map((ev, i) => (
          <Event key={i} ev={ev} />
        ))}
        {running && (
          <div className="event">
            <span className="node tool_call" />
            <div className="thinking"><i /><i /><i /></div>
          </div>
        )}
      </div>

      <div className="footnote">
        Demo only. Mocked market data, not investment advice. Built for Mumbai Python Developers Group.
      </div>
    </div>
  );
}

function Event({ ev }) {
  if (ev.type === "plan") {
    return (
      <div className="event">
        <span className="node plan" />
        <div className="label">reasoning</div>
        <div className="plan-text">{ev.text}</div>
      </div>
    );
  }
  if (ev.type === "tool_call") {
    return (
      <div className="event">
        <span className="node tool_call" />
        <div className="label think">tool call</div>
        <CallLine name={ev.name} args={ev.args} />
      </div>
    );
  }
  if (ev.type === "tool_result") {
    const text =
      typeof ev.result === "string" ? ev.result : JSON.stringify(ev.result, null, 2);
    return (
      <div className="event">
        <span className="node tool_result" />
        <div className="label">{ev.name} returned</div>
        <div className="payload">{text}</div>
      </div>
    );
  }
  if (ev.type === "final") {
    const { verdict, body } = parseVerdict(ev.text);
    return (
      <div className="event">
        <span className="node final" />
        <div className="label">verdict</div>
        <div className="verdict">
          {verdict && <div className={`tag ${verdict}`}>{verdict}</div>}
          <div className="thesis">{body}</div>
        </div>
      </div>
    );
  }
  if (ev.type === "error") {
    return (
      <div className="event">
        <span className="node plan" />
        <div className="err">⚠ {ev.text}</div>
      </div>
    );
  }
  return null;
}
