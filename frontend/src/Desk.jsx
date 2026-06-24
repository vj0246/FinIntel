import { useState, useRef } from "react";

const API = "http://localhost:8000";
const TICKERS = ["RELIANCE", "TCS", "INFY"];

// role → accent colour for the reasoning spine
const ROLE = {
  Researcher: "var(--think)",
  Risk: "var(--signal)",
  Synthesiser: "var(--indigo)",
  Desk: "var(--buy)",
};

function parseVerdict(text) {
  const m = text.match(/\b(BUY|SELL|HOLD)\b/);
  return m ? m[1] : null;
}

export default function Desk() {
  const [ticker, setTicker] = useState("RELIANCE");
  const [events, setEvents] = useState([]);
  const [phase, setPhase] = useState("idle"); // idle | running | awaiting | resuming | done
  const [approval, setApproval] = useState(null);
  const [feedback, setFeedback] = useState("");
  const esRef = useRef(null);
  const threadRef = useRef(null);

  function listen(url) {
    if (esRef.current) esRef.current.close();
    const es = new EventSource(url);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); if (phaseRef.current !== "awaiting") setPhase("done"); return; }
      if (ev.type === "approval_request") {
        setApproval({ recommendation: ev.recommendation, action: ev.action });
        setPhase("awaiting"); phaseRef.current = "awaiting";
        es.close();
        return;
      }
      setEvents((p) => [...p, ev]);
    };
    es.onerror = () => { es.close(); setEvents((p) => [...p, { type: "error", text: "Stream dropped — backend running?" }]); setPhase("done"); };
  }

  // tiny ref mirror so the SSE closure sees the latest phase
  const phaseRef = useRef("idle");

  function run() {
    const tid = crypto.randomUUID();
    threadRef.current = tid;
    setEvents([]); setApproval(null); setFeedback("");
    setPhase("running"); phaseRef.current = "running";
    listen(`${API}/api/analyze?ticker=${ticker}&thread=${tid}`);
  }

  function decide(decision) {
    setApproval(null);
    setPhase("resuming"); phaseRef.current = "resuming";
    const d = encodeURIComponent(decision);
    listen(`${API}/api/resume?thread=${threadRef.current}&decision=${d}`);
  }

  const busy = phase === "running" || phase === "resuming";

  return (
    <div className="desk">
      <div className="eyebrow">Multi-agent · human-in-the-loop · NSE equities</div>
      <h1>The Agent Desk</h1>
      <p className="sub">
        Three agents research, weigh risk, and draft a call with a proposed action —
        then the desk <b>pauses for your sign-off</b> before it acts.
      </p>

      {/* pipeline */}
      <div className="pipe">
        {["Researcher", "Risk", "Synthesiser", "You"].map((n, i) => (
          <span key={n} className="stage" style={{ "--c": n === "You" ? "var(--buy)" : Object.values(ROLE)[i] }}>
            {n}{i < 3 && <em>→</em>}
          </span>
        ))}
      </div>

      <div className="controls">
        {TICKERS.map((t) => (
          <button key={t} className="chip" aria-pressed={ticker === t} onClick={() => setTicker(t)} disabled={busy}>
            {t}
          </button>
        ))}
        <button className="run" onClick={run} disabled={busy}>
          {busy ? "Desk working…" : "Run the desk"}
        </button>
      </div>

      {events.length === 0 && phase === "idle" && (
        <div className="empty">Pick a stock and run the desk. Agents stream in; you approve before it acts.</div>
      )}

      <div className="spine">
        {events.map((ev, i) => <Event key={i} ev={ev} />)}
        {busy && <div className="event"><span className="node tool_call" /><div className="thinking"><i /><i /><i /></div></div>}
      </div>

      {/* approval gate */}
      {phase === "awaiting" && approval && (
        <div className="gate">
          <div className="gate-tag">⏸ Awaiting your sign-off</div>
          {(() => { const v = parseVerdict(approval.recommendation);
            return v && <div className={`tag ${v}`} style={{ fontSize: 26 }}>{v}</div>; })()}
          <div className="gate-rec">{approval.recommendation}</div>
          <div className="gate-action"><span>Proposed action</span>{approval.action}</div>
          <div className="gate-btns">
            <button className="approve" onClick={() => decide("approve")}>Approve & act</button>
            <button className="reject" onClick={() => decide("reject")}>Reject</button>
          </div>
          <div className="revise">
            <input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="…or send feedback to revise (e.g. 'weigh the news more')" />
            <button onClick={() => feedback.trim() && decide(feedback.trim())} disabled={!feedback.trim()}>Revise</button>
          </div>
        </div>
      )}

      <div className="footnote">
        Demo — mocked data, advisory only, not investment advice. The human gate is the point:
        the agent proposes, you sign off, then it acts.
      </div>
    </div>
  );
}

function Event({ ev }) {
  if (ev.type === "agent") {
    return (
      <div className="event" style={{ "--c": ROLE[ev.name] || "var(--muted)" }}>
        <span className="node role" />
        <div className="label" style={{ color: ROLE[ev.name] || "var(--muted)" }}>{ev.name}</div>
        <div className="plan-text" style={{ fontStyle: "normal", whiteSpace: "pre-wrap" }}>{ev.text}</div>
      </div>
    );
  }
  if (ev.type === "final") {
    const v = parseVerdict(ev.text);
    return (
      <div className="event"><span className="node final" />
        <div className="label">outcome</div>
        <div className="verdict">
          {v && <div className={`tag ${v}`}>{v}</div>}
          <div className="thesis" style={{ whiteSpace: "pre-wrap" }}>{ev.text}</div>
        </div>
      </div>
    );
  }
  if (ev.type === "error") {
    return <div className="event"><span className="node plan" /><div className="err">⚠ {ev.text}</div></div>;
  }
  return null;
}
