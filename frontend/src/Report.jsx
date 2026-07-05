import { useState, useRef } from "react";
import TickerSearch from "./TickerSearch.jsx";
import Markdown from "./Markdown.jsx";
import { API } from "./api.js";

const fmt = (n, d = 2) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d }));

const SNAP_LABELS = {
  pe: "P/E", pb: "P/B", sector_pe: "Sector P/E", market_cap_cr: "M-cap (₹ cr)",
  roe_pct: "ROE %", roce_pct: "ROCE %", net_margin_pct: "Net margin %",
  dividend_yield_pct: "Div yield %", debt_to_equity: "D/E", eps_ttm: "EPS (TTM)",
  revenue_ttm_cr: "Revenue TTM (₹ cr)", change_6m_pct: "6-month move %",
};
const QUANT_LABELS = {
  annualised_volatility_pct: "Volatility %", sharpe_ratio: "Sharpe",
  max_drawdown_pct: "Max drawdown %", beta_vs_nifty50: "Beta vs NIFTY",
  rsi_14: "RSI(14)", sma_20: "SMA 20", sma_50: "SMA 50",
  period_return_pct: "6m return %",
};

export default function Report() {
  const [ticker, setTicker] = useState("");
  const [r, setR] = useState({});         // accumulated report sections
  const [phase, setPhase] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const esRef = useRef(null);

  function start() {
    if (!ticker.trim() || busy) return;
    if (esRef.current) esRef.current.close();
    setR({}); setError(""); setPhase("");
    setBusy(true);
    const thread = crypto.randomUUID();
    const es = new EventSource(`${API}/api/report?ticker=${encodeURIComponent(ticker.trim())}&thread=${thread}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setBusy(false); setPhase(""); return; }
      if (ev.type === "phase") setPhase(ev.text);
      else if (ev.type === "error") { setError(ev.text); setBusy(false); es.close(); }
      else setR((prev) => ({ ...prev, [ev.type]: ev }));
    };
    es.onerror = () => { es.close(); setBusy(false); setError((e) => e || "Stream dropped. Is the backend running?"); };
  }

  const eco = r.ecosystem?.data;

  return (
    <div className="desk">
      <div className="eyebrow">Every engine on the desk · one institutional-style note · print to PDF</div>
      <h1>Research Report</h1>
      <p className="sub">One click orchestrates live data, quant, financials, shareholding, the ecosystem map and the multi-agent desk verdict into a single research note you can print or save as PDF.</p>

      <div className="task-setup">
        <div className="row1">
          <span className="nse">NSE</span>
          <TickerSearch value={ticker} onChange={setTicker} disabled={busy} placeholder="Company / ticker (e.g. INFY)" />
          <button className="run" onClick={start} disabled={busy || !ticker.trim()}>{busy ? "Compiling…" : "▶ Generate"}</button>
          {r.summary && !busy && <button className="preset" onClick={() => window.print()}>🖨 Print / PDF</button>}
        </div>
      </div>

      {busy && phase && <div className="eco-phase">{phase}</div>}
      {error && <div className="err" style={{ marginTop: 10 }}>⚠ {error}</div>}

      {r.cover && (
        <div className="report" id="report-print">
          <div className="rp-cover">
            <div className="rp-title">{r.cover.name} <span className="pf-chip">{r.cover.ticker}</span>
              {r.cover.source !== "live" && <span className="pf-chip">sample data</span>}</div>
            <div className="eco-meta">
              <span>Equity Research Note · {r.cover.date}</span>
              {r.cover.price != null && <span>₹{fmt(r.cover.price)}</span>}
              {r.cover.sector && <span>{r.cover.sector}</span>}
              {r.verdict?.verdict && <span className={`wr-badge wr-${r.verdict.verdict.toLowerCase()}`}>{r.verdict.verdict}</span>}
            </div>
          </div>

          {r.summary && (
            <div className="rp-section"><h3>Executive summary</h3><Markdown>{r.summary.text}</Markdown></div>
          )}

          {r.snapshot && (
            <div className="rp-section"><h3>Snapshot</h3>
              <div className="rp-stats">
                {Object.entries(SNAP_LABELS).map(([k, label]) => r.snapshot.data[k] !== undefined && (
                  <div key={k} className="rp-stat"><span>{label}</span><b>{fmt(r.snapshot.data[k])}</b></div>
                ))}
                {r.snapshot.data.week52?.high && <div className="rp-stat"><span>52w high / low</span><b>{fmt(r.snapshot.data.week52.high)} / {fmt(r.snapshot.data.week52.low)}</b></div>}
              </div>
            </div>
          )}

          {r.quant && (
            <div className="rp-section"><h3>Quantitative profile</h3>
              <div className="rp-stats">
                {Object.entries(QUANT_LABELS).map(([k, label]) => r.quant.data[k] !== undefined && r.quant.data[k] !== null && (
                  <div key={k} className="rp-stat"><span>{label}</span><b>{fmt(r.quant.data[k])}</b></div>
                ))}
              </div>
              {r.quant.data.trend_signal && <div className="footnote">Trend: {r.quant.data.trend_signal}</div>}
            </div>
          )}

          {r.financials && (r.financials.quarterly?.length > 0 || r.financials.annual?.length > 0) && (
            <div className="rp-section"><h3>Financials (₹ crore)</h3>
              {r.financials.quarterly?.length > 0 && (
                <div className="pf-tablewrap"><table className="pf-table">
                  <thead><tr><th>Quarter</th><th>Revenue</th><th>Net profit</th><th>Op. profit</th><th>EPS ₹</th></tr></thead>
                  <tbody>{r.financials.quarterly.map((q, i) => (
                    <tr key={i}><td>{q.quarter}</td><td>{fmt(q.revenue_cr, 0)}</td><td>{fmt(q.net_income_cr, 0)}</td><td>{fmt(q.operating_income_cr, 0)}</td><td>{fmt(q.eps)}</td></tr>
                  ))}</tbody>
                </table></div>
              )}
              {r.financials.annual?.length > 0 && (
                <div className="pf-tablewrap"><table className="pf-table">
                  <thead><tr><th>Year</th><th>Revenue</th><th>Net profit</th><th>OPM %</th><th>EPS ₹</th></tr></thead>
                  <tbody>{r.financials.annual.map((a, i) => (
                    <tr key={i}><td>{a.year}</td><td>{fmt(a.revenue_cr, 0)}</td><td>{fmt(a.net_income_cr, 0)}</td><td>{fmt(a.opm_pct)}</td><td>{fmt(a.eps)}</td></tr>
                  ))}</tbody>
                </table></div>
              )}
            </div>
          )}

          {r.shareholding && (
            <div className="rp-section"><h3>Shareholding pattern (%)</h3>
              <div className="pf-tablewrap"><table className="pf-table">
                <thead><tr><th>Quarter</th><th>Promoters</th><th>FIIs</th><th>DIIs</th><th>Public</th></tr></thead>
                <tbody>{r.shareholding.data.map((s, i) => (
                  <tr key={i}><td>{s.quarter}</td><td>{fmt(s.promoters_pct)}</td><td>{fmt(s.fiis_pct)}</td><td>{fmt(s.diis_pct)}</td><td>{fmt(s.public_pct)}</td></tr>
                ))}</tbody>
              </table></div>
            </div>
          )}

          {eco && (eco.competitors?.length > 0 || eco.moat) && (
            <div className="rp-section"><h3>Ecosystem</h3>
              {eco.moat && <p className="eco-item">🏰 {eco.moat}</p>}
              {eco.competitors?.length > 0 && (
                <p className="eco-item"><b>Competes with:</b> {eco.competitors.map((c) => c.name).join(", ")}</p>
              )}
              {eco.key_risks?.length > 0 && (
                <p className="eco-item"><b>Key risks:</b> {eco.key_risks.join("; ")}</p>
              )}
            </div>
          )}

          {r.bullbear && (
            <div className="rp-section"><h3>Bull vs bear</h3><Markdown>{r.bullbear.text}</Markdown></div>
          )}

          {r.verdict && (
            <div className="rp-section"><h3>Desk verdict</h3>
              <Markdown>{r.verdict.text}</Markdown>
              {r.verdict.action && <div className="gate-action" style={{ marginTop: 8 }}><span>Proposed action</span>{r.verdict.action}</div>}
            </div>
          )}
        </div>
      )}

      <div className="footnote">Verdicts from reports are logged to the desk track record. Informational only, not investment advice.</div>
    </div>
  );
}
