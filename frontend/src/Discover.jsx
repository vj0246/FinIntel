import { useState, useRef } from "react";
import Markdown from "./Markdown.jsx";
import { API } from "./api.js";

const PRESETS = [
  ["💎 Quality compounders", "profitable companies with ROE above 20, PE below 30 and revenue growing over 10%"],
  ["🏦 FIIs buying", "stocks where FIIs increased their stake this quarter with ROE above 15"],
  ["📉 Beaten-down value", "stocks trading near their 52-week low with PE below 20 and positive profit growth"],
  ["🚀 High growth", "companies with revenue growth above 20% and profit growth above 20%"],
  ["🛡 Dividend payers", "dividend yield above 2% with ROE above 15"],
];

const fmt = (n, d = 1) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d }));

const COLS = [
  ["price", "₹ Price", 2], ["pe", "PE", 1], ["pb", "PB", 1], ["roe_pct", "ROE%", 1],
  ["roce_pct", "ROCE%", 1], ["dividend_yield_pct", "Yield%", 2], ["market_cap_cr", "M-cap ₹cr", 0],
  ["rev_yoy_pct", "Rev YoY%", 1], ["profit_yoy_pct", "Profit YoY%", 1],
  ["rev_cagr_3y_pct", "Rev 3y CAGR%", 1],
  ["promoter_change_pct", "Prom Δ", 2], ["fii_change_pct", "FII Δ", 2],
  ["ret_6m_pct", "6m%", 1], ["rsi_14", "RSI", 0], ["volatility_pct", "Vol%", 1],
  ["sharpe", "Sharpe", 2], ["beta", "Beta", 2], ["dist_52w_high_pct", "vs 52w-hi%", 1],
];

export default function Discover() {
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState(null);
  const [progress, setProgress] = useState(null);
  const [rows, setRows] = useState(null);
  const [note, setNote] = useState("");
  const [commentary, setCommentary] = useState("");
  const [phase, setPhase] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const esRef = useRef(null);

  function start(text) {
    const query = (text || q).trim();
    if (!query || busy) return;
    if (esRef.current) esRef.current.close();
    setPlan(null); setProgress(null); setRows(null); setNote(""); setCommentary(""); setError(""); setPhase("");
    setBusy(true);
    const thread = crypto.randomUUID();
    const es = new EventSource(`${API}/api/discover?q=${encodeURIComponent(query)}&thread=${thread}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setBusy(false); setPhase(""); return; }
      if (ev.type === "phase") setPhase(ev.text);
      else if (ev.type === "plan") setPlan(ev);
      else if (ev.type === "progress") setProgress(ev);
      else if (ev.type === "results") { setRows(ev.rows); setNote(ev.note || ""); }
      else if (ev.type === "commentary") setCommentary(ev.text);
      else if (ev.type === "error") { setError(ev.text); setBusy(false); es.close(); }
    };
    es.onerror = () => { es.close(); setBusy(false); setError((e) => e || "Stream dropped. Is the backend running?"); };
  }

  // only show columns that at least one row has a value for
  const activeCols = rows?.length ? COLS.filter(([k]) => rows.some((r) => r[k] !== null && r[k] !== undefined)) : [];

  return (
    <div className="desk">
      <div className="eyebrow">Natural-language screener · deterministic filters · live universe sweep</div>
      <h1>Discover</h1>
      <p className="sub">Describe the stocks you're hunting for in plain English. An agent turns it into hard filters, sweeps ~100 NSE names with real data, and explains every hit.</p>

      <div className="task-setup">
        <div className="presets">
          {PRESETS.map(([label, t]) => (
            <button key={label} className="preset" onClick={() => { setQ(t); start(t); }} disabled={busy}>{label}</button>
          ))}
        </div>
        <div className="row2">
          <input className="task-input" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()} disabled={busy}
            placeholder="e.g. IT stocks with ROE above 20, PE below 30, where FIIs are buying…" />
          <button className="run" onClick={() => start()} disabled={busy || !q.trim()}>{busy ? "Screening…" : "▶ Screen"}</button>
        </div>
      </div>

      {plan && (
        <div className="pf-chips" style={{ marginTop: 10 }}>
          {plan.sectors.map((s) => <span key={s} className="pf-chip">📁 {s}</span>)}
          {plan.filters.map((f, i) => <span key={i} className="pf-chip">{f.metric} {f.op} {f.value}</span>)}
          {plan.sort_by && <span className="pf-chip">sort: {plan.sort_by} {plan.sort_dir}</span>}
        </div>
      )}

      {busy && (
        <div className="eco-phase">
          {phase}{progress ? ` — scanned ${progress.scanned}/${progress.total}, ${progress.hits} hits` : ""}
        </div>
      )}
      {progress && busy && (
        <div className="wr-conf-bar"><i style={{ width: `${(progress.scanned / progress.total) * 100}%` }} /></div>
      )}
      {error && <div className="err" style={{ marginTop: 10 }}>⚠ {error}</div>}

      {rows && rows.length === 0 && <div className="empty">{note}</div>}
      {rows && rows.length > 0 && (
        <>
          <div className="label" style={{ margin: "14px 0 4px" }}>{note}</div>
          <div className="pf-tablewrap">
            <table className="pf-table">
              <thead>
                <tr><th>Stock</th><th>Sector</th>{activeCols.map(([k, label]) => <th key={k}>{label}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.ticker}>
                    <td><b>{r.ticker}</b></td><td>{r.sector}</td>
                    {activeCols.map(([k, , d]) => <td key={k}>{fmt(r[k], d)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {commentary && (
        <div className="event" style={{ marginTop: 14 }}>
          <span className="node final" /><div className="label">analyst take</div>
          <div className="verdict"><div className="thesis"><Markdown>{commentary}</Markdown></div></div>
        </div>
      )}

      <div className="footnote">Screens a curated ~100-stock NSE universe with live Screener/market data; missing data never passes a filter. Informational only, not investment advice.</div>
    </div>
  );
}
