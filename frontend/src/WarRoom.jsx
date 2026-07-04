import { useState, useRef, useEffect } from "react";
import TickerSearch from "./TickerSearch.jsx";
import Markdown from "./Markdown.jsx";
import { API } from "./api.js";

const PRESETS = [
  ["⚖️ Long-term hold?", "Is this stock worth holding for the long term?"],
  ["🥊 Full debate", "Run a full bull vs bear debate and give me a verdict."],
  ["📉 After the fall", "The stock has fallen recently — is this a buying opportunity or a warning?"],
  ["🆚 Compare", "Compare this stock against its closest NSE competitor as an investment."],
];

const ROLE_COLOR = {
  "Quant Analyst": "var(--indigo)",
  "Fundamental Researcher": "var(--think)",
  "News & Sentiment": "var(--signal)",
  "Risk Officer": "var(--sell)",
};

export default function WarRoom() {
  const [ticker, setTicker] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [verdict, setVerdict] = useState(null);
  const [pending, setPending] = useState(null);
  const [feedback, setFeedback] = useState("");
  const [phase, setPhase] = useState("idle");   // idle | working | awaiting | done
  const esRef = useRef(null);
  const thread = useRef(null);
  const bottom = useRef(null);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [items, pending, verdict]);

  function listen(url) {
    if (esRef.current) esRef.current.close();
    setPhase("working"); setPending(null);
    const es = new EventSource(url);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setPhase((p) => (p === "working" ? "idle" : p)); return; }
      if (ev.type === "plan") setItems((p) => [...p, { kind: "plan", text: ev.text, specialists: ev.specialists, tickers: ev.tickers }]);
      else if (ev.type === "specialist") setItems((p) => [...p, { kind: "spec", label: ev.label, ticker: ev.ticker, text: ev.text }]);
      else if (ev.type === "phase") setItems((p) => [...p, { kind: "phase", text: ev.text }]);
      else if (ev.type === "debate") setItems((p) => [...p, { kind: "debate", side: ev.side, text: ev.text }]);
      else if (ev.type === "verdict") setVerdict(ev);
      else if (ev.type === "approval_request") { setPending({ recommendation: ev.recommendation, action: ev.action }); setPhase("awaiting"); es.close(); }
      else if (ev.type === "final") { setItems((p) => [...p, { kind: "final", text: ev.text }]); setPhase("done"); es.close(); }
      else if (ev.type === "error") { setItems((p) => [...p, { kind: "error", text: ev.text }]); setPhase("idle"); es.close(); }
    };
    es.onerror = () => { es.close(); setPhase("idle"); setItems((p) => [...p, { kind: "error", text: "Stream dropped. Is the backend running?" }]); };
  }

  function start() {
    if (!q.trim() || phase === "working") return;
    thread.current = crypto.randomUUID();
    setItems([]); setVerdict(null); setPending(null);
    listen(`${API}/api/war/start?q=${encodeURIComponent(q.trim())}&ticker=${encodeURIComponent(ticker.trim())}&thread=${thread.current}`);
  }

  const decide = (d) => listen(`${API}/api/war/resume?thread=${thread.current}&decision=${encodeURIComponent(d)}`);
  const running = phase === "working";

  return (
    <div className="desk">
      <div className="eyebrow">Orchestrated research · bull vs bear debate · judged verdict</div>
      <h1>Research War Room</h1>
      <p className="sub">A Chief Analyst plans the research, deploys specialist agents in parallel, then a Bull and a Bear argue the case and a Judge rules — with your sign-off on the verdict.</p>

      <div className="task-setup">
        <div className="row1">
          <span className="nse">NSE</span>
          <TickerSearch value={ticker} onChange={setTicker} disabled={running} placeholder="Stock (optional if named in the question)" />
        </div>
        <div className="presets">
          {PRESETS.map(([label, t]) => (
            <button key={label} className="preset" onClick={() => setQ(t)} disabled={running}>{label}</button>
          ))}
        </div>
        <div className="row2">
          <input className="task-input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && start()} placeholder="Your research question…" disabled={running} />
          <button className="run" onClick={start} disabled={running || !q.trim()}>{running ? "In session…" : "▶ Convene"}</button>
        </div>
      </div>

      {items.length === 0 && phase === "idle" && (
        <div className="empty">Ask a research question. The desk convenes, debates, and a judge rules — you approve the final call.</div>
      )}

      <div className="spine">
        {items.map((it, i) =>
          it.kind === "plan" ? (
            <div key={i} className="event"><span className="node plan" />
              <div className="plan-text">{it.text}</div>
              <div className="pf-chips" style={{ marginTop: 6 }}>
                {it.tickers.map((t) => <span key={t} className="pf-chip">{t}</span>)}
                {it.specialists.map((s) => <span key={s} className="pf-chip">{s}</span>)}
              </div>
            </div>
          ) : it.kind === "spec" ? (
            <div key={i} className="event" style={{ "--c": ROLE_COLOR[it.label] || "var(--muted)" }}>
              <span className="node role" />
              <div className="label" style={{ color: ROLE_COLOR[it.label] || "var(--muted)" }}>{it.label} · {it.ticker}</div>
              <div className="plan-text" style={{ fontStyle: "normal" }}><Markdown>{it.text}</Markdown></div>
            </div>
          ) : it.kind === "phase" ? (
            <div key={i} className="event"><span className="node plan" /><div className="plan-text">{it.text}</div></div>
          ) : it.kind === "debate" ? (
            <div key={i} className={`event wr-${it.side.toLowerCase()}`} style={{ "--c": it.side === "Bull" ? "var(--buy)" : "var(--sell)" }}>
              <span className="node role" />
              <div className="label" style={{ color: it.side === "Bull" ? "var(--buy)" : "var(--sell)" }}>{it.side === "Bull" ? "🐂 Bull advocate" : "🐻 Bear advocate"}</div>
              <div className="wr-case"><Markdown>{it.text}</Markdown></div>
            </div>
          ) : it.kind === "final" ? (
            <div key={i} className="event"><span className="node final" /><div className="label">war-room report</div><div className="verdict"><div className="thesis"><Markdown>{it.text}</Markdown></div></div></div>
          ) : (
            <div key={i} className="event"><span className="node plan" /><div className="err">⚠ {it.text}</div></div>
          )
        )}
        {running && <div className="event"><span className="node tool_call" /><div className="thinking"><i /><i /><i /></div></div>}
        <div ref={bottom} />
      </div>

      {verdict && phase !== "done" && (
        <div className="wr-verdict">
          <div className="wr-verdict-head">
            <span className={`wr-badge wr-${verdict.verdict.toLowerCase()}`}>{verdict.verdict}</span>
            <span className="wr-conf">confidence {verdict.confidence_pct}%</span>
            {verdict.bull_score != null && <span className="wr-score">🐂 {verdict.bull_score}/10 · 🐻 {verdict.bear_score}/10</span>}
          </div>
          <div className="wr-conf-bar"><i style={{ width: `${verdict.confidence_pct}%` }} /></div>
          <div className="plan-text" style={{ fontStyle: "normal", marginTop: 8 }}>{verdict.reasoning}</div>
        </div>
      )}

      {phase === "awaiting" && pending && (
        <div className="gate">
          <div className="gate-tag">⏸ Judge has ruled — your call</div>
          <div className="gate-action"><span>Proposed action</span>{pending.action}</div>
          <div className="gate-btns">
            <button className="approve" onClick={() => decide("approve")}>✓ Approve & log the call</button>
            <button className="reject" onClick={() => decide("reject")}>✕ Reject</button>
          </div>
          <div className="revise">
            <input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="…or challenge the ruling (e.g. 'you underweighted the debt risk')" />
            <button onClick={() => feedback.trim() && (decide(feedback.trim()), setFeedback(""))} disabled={!feedback.trim()}>↩ Re-judge</button>
          </div>
        </div>
      )}

      <div className="footnote">Informational only, not investment advice. Approved calls are logged and graded on the Portfolio tab's track record.</div>
    </div>
  );
}
