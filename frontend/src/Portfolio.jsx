import { useState, useRef, useEffect } from "react";
import Markdown from "./Markdown.jsx";
import { API } from "./api.js";

const SAMPLE = "RELIANCE, 10, 2400\nTCS, 5, 3900\nINFY, 20, 1600";

const fmt = (n, d = 2) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d }));
const pct = (n) => (n === null || n === undefined ? "—" : `${n > 0 ? "+" : ""}${fmt(n)}%`);

export default function Portfolio() {
  const [text, setText] = useState("");
  const [holdings, setHoldings] = useState([]);   // parsed rows, enriched live during audit
  const [warnings, setWarnings] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [items, setItems] = useState([]);         // timeline: intro / risk / final / error
  const [pending, setPending] = useState(null);   // {summary, actions}
  const [feedback, setFeedback] = useState("");
  const [phase, setPhase] = useState("idle");     // idle | working | awaiting | done
  const [record, setRecord] = useState(null);     // track-record scoreboard
  const esRef = useRef(null);
  const fileRef = useRef(null);
  const thread = useRef(crypto.randomUUID());
  const bottom = useRef(null);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [items, pending]);
  useEffect(() => { loadRecord(); }, []);

  async function loadRecord() {
    try {
      const r = await fetch(`${API}/api/track-record`);
      setRecord(await r.json());
    } catch { /* backend offline — scoreboard just stays hidden */ }
  }

  async function load(body) {
    setWarnings([]); setMetrics(null); setItems([]); setPending(null); setPhase("idle");
    try {
      const r = await fetch(`${API}/api/portfolio`, { method: "POST", body });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Could not parse holdings");
      setHoldings(d.holdings);
      setWarnings(d.warnings || []);
    } catch (err) {
      setHoldings([]); setWarnings([err.message]);
    }
  }

  function loadText() {
    if (!text.trim()) return;
    const fd = new FormData();
    fd.append("thread", thread.current);
    fd.append("text", text);
    load(fd);
  }

  function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("thread", thread.current);
    fd.append("file", file);
    load(fd);
    if (fileRef.current) fileRef.current.value = "";
  }

  function listen(url) {
    if (esRef.current) esRef.current.close();
    setPhase("working"); setPending(null);
    const es = new EventSource(url);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setPhase((p) => (p === "working" ? "idle" : p)); return; }
      if (ev.type === "intro") setItems((p) => [...p, { kind: "intro", text: ev.text }]);
      else if (ev.type === "holding")
        setHoldings((hs) => hs.map((h) => (h.ticker === ev.ticker ? { ...h, ...ev } : h)));
      else if (ev.type === "portfolio") setMetrics(ev.metrics);
      else if (ev.type === "agent") setItems((p) => [...p, { kind: "risk", text: ev.text }]);
      else if (ev.type === "approval_request") { setPending({ summary: ev.summary, actions: ev.actions }); setPhase("awaiting"); es.close(); }
      else if (ev.type === "final") { setItems((p) => [...p, { kind: "final", text: ev.text }]); setPhase("done"); es.close(); loadRecord(); }
      else if (ev.type === "error") { setItems((p) => [...p, { kind: "error", text: ev.text }]); setPhase("idle"); es.close(); }
    };
    es.onerror = () => { es.close(); setPhase("idle"); setItems((p) => [...p, { kind: "error", text: "Stream dropped. Is the backend running?" }]); };
  }

  const audit = () => listen(`${API}/api/portfolio/analyze?thread=${thread.current}`);
  const decide = (d) => listen(`${API}/api/portfolio/resume?thread=${thread.current}&decision=${encodeURIComponent(d)}`);

  const running = phase === "working";

  return (
    <div className="desk">
      <div className="eyebrow">Portfolio auditor · parallel multi-agent · human-in-the-loop</div>
      <h1>Portfolio Risk Auditor</h1>
      <p className="sub">Paste your holdings or upload a broker CSV (Zerodha / Groww export). Every stock is analysed in parallel, a risk officer flags portfolio-level dangers, and rebalance ideas wait for your sign-off.</p>

      <div className="task-setup">
        <textarea
          className="pf-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"One holding per line:  TICKER, quantity, avg buy price\n" + SAMPLE}
          rows={4}
          disabled={running}
        />
        <div className="row2">
          <button className="preset" onClick={() => setText(SAMPLE)} disabled={running}>Try sample</button>
          <button className="preset" onClick={() => fileRef.current?.click()} disabled={running}>📎 Broker CSV</button>
          <input ref={fileRef} type="file" accept=".csv,.txt" onChange={onFile} hidden />
          <button className="preset" onClick={loadText} disabled={running || !text.trim()}>Load holdings</button>
          <button className="run" onClick={audit} disabled={running || holdings.length === 0}>
            {running ? "Auditing…" : "▶ Run audit"}
          </button>
        </div>
        {warnings.map((w, i) => <div key={i} className="err" style={{ marginTop: 6 }}>⚠ {w}</div>)}
      </div>

      {holdings.length > 0 && (
        <div className="pf-tablewrap">
          <table className="pf-table">
            <thead>
              <tr><th>Stock</th><th>Qty</th><th>Avg cost</th><th>LTP</th><th>Value</th><th>P&L</th><th>Sector</th><th>P/E</th></tr>
            </thead>
            <tbody>
              {holdings.map((h) => (
                <tr key={h.ticker} className={h.error ? "pf-err" : ""}>
                  <td>{h.ticker}</td>
                  <td>{fmt(h.qty, 0)}</td>
                  <td>{fmt(h.avg_cost)}</td>
                  <td>{h.error ? "no data" : fmt(h.ltp)}</td>
                  <td>{fmt(h.value, 0)}</td>
                  <td className={h.pnl_pct > 0 ? "pf-up" : h.pnl_pct < 0 ? "pf-down" : ""}>{pct(h.pnl_pct)}</td>
                  <td>{h.sector || "—"}</td>
                  <td>{fmt(h.pe, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {metrics && !metrics.error && (
        <div className="pf-chips">
          <span className="pf-chip">Value ₹{fmt(metrics.total_value, 0)}</span>
          {metrics.total_pnl_pct !== null && <span className={`pf-chip ${metrics.total_pnl_pct >= 0 ? "pf-up" : "pf-down"}`}>P&L {pct(metrics.total_pnl_pct)}</span>}
          {metrics.weighted_pe && <span className="pf-chip">Weighted P/E {metrics.weighted_pe}</span>}
          <span className="pf-chip">Top position {metrics.top_position.ticker} {metrics.top_position.weight_pct}%</span>
          {Object.entries(metrics.sectors).slice(0, 3).map(([s, w]) => <span key={s} className="pf-chip">{s} {w}%</span>)}
        </div>
      )}

      <div className="spine">
        {items.map((it, i) =>
          it.kind === "intro" ? (
            <div key={i} className="event"><span className="node plan" /><div className="plan-text">{it.text}</div></div>
          ) : it.kind === "risk" ? (
            <div key={i} className="event" style={{ "--c": "var(--signal)" }}><span className="node role" /><div className="label" style={{ color: "var(--signal)" }}>Risk officer</div><div className="plan-text" style={{ fontStyle: "normal" }}><Markdown>{it.text}</Markdown></div></div>
          ) : it.kind === "final" ? (
            <div key={i} className="event"><span className="node final" /><div className="label">audit report</div><div className="verdict"><div className="thesis"><Markdown>{it.text}</Markdown></div></div></div>
          ) : (
            <div key={i} className="event"><span className="node plan" /><div className="err">⚠ {it.text}</div></div>
          )
        )}
        {running && <div className="event"><span className="node tool_call" /><div className="thinking"><i /><i /><i /></div></div>}
        <div ref={bottom} />
      </div>

      {phase === "awaiting" && pending && (
        <div className="gate">
          <div className="gate-tag">⏸ Rebalance proposal — your call</div>
          <div className="gate-action"><span>Portfolio verdict</span>{pending.summary}</div>
          <ol className="pf-actions">
            {pending.actions.map((a, i) => <li key={i}><b>{a.action}</b>{a.reason ? ` — ${a.reason}` : ""}</li>)}
          </ol>
          <div className="gate-btns">
            <button className="approve" onClick={() => decide("approve")}>✓ Approve plan</button>
            <button className="reject" onClick={() => decide("reject")}>✕ Reject</button>
          </div>
          <div className="revise">
            <input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="…or revise (e.g. 'I want to keep my INFY position')" />
            <button onClick={() => feedback.trim() && (decide(feedback.trim()), setFeedback(""))} disabled={!feedback.trim()}>↩ Revise</button>
          </div>
        </div>
      )}

      {record && record.calls?.length > 0 && (
        <div className="pf-record">
          <div className="label" style={{ marginBottom: 6 }}>
            Desk track record — {record.scored ? `${record.correct}/${record.scored} calls correct (${record.hit_rate_pct}%)` : "no scored calls yet"}
            <button className="preset" style={{ marginLeft: 10 }} onClick={loadRecord}>↻</button>
          </div>
          <div className="pf-tablewrap">
            <table className="pf-table">
              <thead><tr><th>Date</th><th>Stock</th><th>Call</th><th>At ₹</th><th>Now ₹</th><th>Move</th><th>Result</th></tr></thead>
              <tbody>
                {record.calls.slice(0, 8).map((c, i) => (
                  <tr key={i}>
                    <td>{(c.date || "").slice(0, 10)}</td>
                    <td>{c.ticker}</td>
                    <td>{c.verdict}</td>
                    <td>{fmt(c.price)}</td>
                    <td>{fmt(c.current_price)}</td>
                    <td className={c.change_pct > 0 ? "pf-up" : c.change_pct < 0 ? "pf-down" : ""}>{pct(c.change_pct)}</td>
                    <td>{c.status === "correct" ? "✅" : c.status === "wrong" ? "❌" : c.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="footnote" style={{ marginTop: 4 }}>Scoring: BUY needs &gt;+2%, SELL needs &lt;−2%, HOLD within ±5%; calls under 2 days old aren't scored.</div>
        </div>
      )}

      <div className="footnote">Informational only, not investment advice. The desk proposes; you approve.</div>
    </div>
  );
}
