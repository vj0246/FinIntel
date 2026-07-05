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
  const [ledger, setLedger] = useState(null);     // paper-trading ledger
  const [st, setSt] = useState({ rows: [], impact: null, narrative: "", phase: "", busy: false, scenario: null, custom: { market: -10, crude: 0, inr: 0, rates: 0 }, showCustom: false });
  const stRef = useRef(null);
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
    try {
      const l = await fetch(`${API}/api/ledger`);
      setLedger(await l.json());
    } catch { /* ledger stays hidden */ }
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

  const profileParam = () => {
    try { const p = JSON.parse(localStorage.getItem("equity-desk-risk-profile"))?.profile; return p ? `&profile=${p}` : ""; }
    catch { return ""; }
  };
  const audit = () => listen(`${API}/api/portfolio/analyze?thread=${thread.current}${profileParam()}`);
  const decide = (d) => listen(`${API}/api/portfolio/resume?thread=${thread.current}&decision=${encodeURIComponent(d)}`);

  const running = phase === "working";

  function stressRun(scenario, custom) {
    if (st.busy || holdings.length === 0) return;
    if (stRef.current) stRef.current.close();
    setSt((s) => ({ ...s, rows: [], impact: null, narrative: "", phase: "", busy: true, scenario }));
    const qs = custom
      ? `&market=${custom.market || 0}&crude=${custom.crude || 0}&inr=${custom.inr || 0}&rates=${custom.rates || 0}`
      : "";
    const es = new EventSource(`${API}/api/portfolio/stress?thread=${thread.current}&scenario=${scenario}${qs}${profileParam()}`);
    stRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setSt((s) => ({ ...s, busy: false, phase: "" })); return; }
      if (ev.type === "phase") setSt((s) => ({ ...s, phase: ev.text }));
      else if (ev.type === "shock") setSt((s) => ({ ...s, rows: [...s.rows.filter((r) => r.ticker !== ev.ticker), ev].sort((a, b) => a.loss - b.loss) }));
      else if (ev.type === "impact") setSt((s) => ({ ...s, impact: ev }));
      else if (ev.type === "narrative") setSt((s) => ({ ...s, narrative: ev.text }));
      else if (ev.type === "error") { setSt((s) => ({ ...s, busy: false, phase: `⚠ ${ev.text}` })); es.close(); }
    };
    es.onerror = () => { es.close(); setSt((s) => ({ ...s, busy: false })); };
  }

  const SCENARIOS = [
    ["gfc_2008", "🌊 2008 crisis"],
    ["covid_crash", "🦠 COVID crash"],
    ["taper_2013", "💸 Rupee rout"],
    ["crude_spike", "🛢 Crude +40%"],
    ["it_winter", "❄️ IT winter"],
    ["rate_shock", "🏦 Rates +100bps"],
  ];

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

      {holdings.length > 0 && (
        <div className="st-panel">
          <div className="label" style={{ marginBottom: 6 }}>Stress test — what would this scenario do to your portfolio?</div>
          <div className="presets">
            {SCENARIOS.map(([key, label]) => (
              <button key={key} className={`preset${st.scenario === key ? " active" : ""}`}
                onClick={() => stressRun(key)} disabled={st.busy}>{label}</button>
            ))}
            <button className="preset" onClick={() => setSt((s) => ({ ...s, showCustom: !s.showCustom }))} disabled={st.busy}>⚙ Custom…</button>
          </div>
          {st.showCustom && (
            <div className="bt-row" style={{ marginTop: 8 }}>
              {[["market", "Market %"], ["crude", "Crude %"], ["inr", "USD/INR %"], ["rates", "Rates bps"]].map(([k, label]) => (
                <label key={k} className="bt-field"><span>{label}</span>
                  <input type="number" value={st.custom[k]}
                    onChange={(e) => setSt((s) => ({ ...s, custom: { ...s.custom, [k]: e.target.value } }))} disabled={st.busy} />
                </label>
              ))}
              <button className="run" onClick={() => stressRun("custom", st.custom)} disabled={st.busy}>▶ Shock it</button>
            </div>
          )}
          {st.busy && st.phase && <div className="eco-phase">{st.phase}</div>}
          {!st.busy && st.phase.startsWith("⚠") && <div className="err">{st.phase}</div>}

          {st.impact && (
            <div className="pf-chips" style={{ marginTop: 8 }}>
              <span className={`pf-chip ${st.impact.portfolio_move_pct >= 0 ? "pf-up" : "pf-down"}`}>
                Portfolio {pct(st.impact.portfolio_move_pct)} → ₹{fmt(st.impact.shocked_value, 0)}
              </span>
              <span className="pf-chip pf-down">Loss ₹{fmt(Math.abs(st.impact.total_loss), 0)}</span>
              {st.impact.worst_position && <span className="pf-chip">Worst: {st.impact.worst_position.ticker} {pct(st.impact.worst_position.est_move_pct)}</span>}
              {st.impact.profile && (
                <span className={`pf-chip ${st.impact.within_tolerance ? "pf-up" : "pf-down"}`}>
                  {st.impact.within_tolerance ? "✓ within" : "✕ breaches"} your {st.impact.profile} tolerance ({st.impact.tolerance_pct}%)
                </span>
              )}
            </div>
          )}

          {st.rows.length > 0 && (
            <div className="pf-tablewrap">
              <table className="pf-table">
                <thead><tr><th>Stock</th><th>Sector</th><th>Beta</th><th>Value ₹</th><th>Est. move</th><th>Shocked ₹</th><th>Loss ₹</th></tr></thead>
                <tbody>
                  {st.rows.map((r) => (
                    <tr key={r.ticker}>
                      <td>{r.ticker}</td><td>{r.sector}</td><td>{r.beta ?? "~1.0"}</td>
                      <td>{fmt(r.value, 0)}</td>
                      <td className={r.est_move_pct >= 0 ? "pf-up" : "pf-down"}>{pct(r.est_move_pct)}</td>
                      <td>{fmt(r.shocked_value, 0)}</td>
                      <td className={r.loss >= 0 ? "pf-up" : "pf-down"}>{fmt(r.loss, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {st.narrative && (
            <div className="event" style={{ marginTop: 10 }}>
              <span className="node final" /><div className="label">damage report</div>
              <div className="verdict"><div className="thesis"><Markdown>{st.narrative}</Markdown></div></div>
            </div>
          )}
          {st.rows.length > 0 && <div className="footnote" style={{ marginTop: 4 }}>Coarse factor model: real beta × market shock + fixed sector sensitivities to crude, USD/INR and rates. Not a prediction.</div>}
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

      {ledger && ledger.positions?.length > 0 && (
        <div className="pf-record">
          <div className="label" style={{ marginBottom: 6 }}>
            Paper-trading ledger — ₹{fmt(ledger.notional_per_call, 0)} virtual per call
          </div>
          <div className="pf-chips" style={{ marginBottom: 8 }}>
            <span className={`pf-chip ${ledger.total_pnl >= 0 ? "pf-up" : "pf-down"}`}>Total P&L ₹{fmt(ledger.total_pnl, 0)}</span>
            {ledger.win_rate_pct !== null && <span className="pf-chip">Win rate {ledger.win_rate_pct}%</span>}
            {ledger.alpha !== null && ledger.alpha !== undefined && (
              <span className={`pf-chip ${ledger.alpha >= 0 ? "pf-up" : "pf-down"}`}>Alpha vs NIFTY ₹{fmt(ledger.alpha, 0)}</span>
            )}
          </div>
          <div className="pf-tablewrap">
            <table className="pf-table">
              <thead><tr><th>Date</th><th>Stock</th><th>Call</th><th>Entry ₹</th><th>Now ₹</th><th>Days</th><th>P&L ₹</th><th>P&L %</th><th>vs NIFTY ₹</th></tr></thead>
              <tbody>
                {ledger.positions.slice(0, 8).map((p, i) => (
                  <tr key={i}>
                    <td>{p.date}</td>
                    <td>{p.ticker}</td>
                    <td>{p.verdict === "BUY" ? "🟢 Long" : "🔴 Short signal"}</td>
                    <td>{fmt(p.entry_price)}</td>
                    <td>{fmt(p.current_price)}</td>
                    <td>{p.days_held ?? "—"}</td>
                    <td className={p.pnl > 0 ? "pf-up" : p.pnl < 0 ? "pf-down" : ""}>{fmt(p.pnl, 0)}</td>
                    <td className={p.pnl_pct > 0 ? "pf-up" : p.pnl_pct < 0 ? "pf-down" : ""}>{pct(p.pnl_pct)}</td>
                    <td>{p.alpha !== undefined ? fmt(p.alpha, 0) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="footnote" style={{ marginTop: 4 }}>Every approved BUY/SELL becomes a ₹1,00,000 virtual position, marked to market live. HOLD calls aren't traded.</div>
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
