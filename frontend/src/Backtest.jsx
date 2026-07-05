import { useState, useRef } from "react";
import TickerSearch from "./TickerSearch.jsx";
import Markdown from "./Markdown.jsx";
import { API } from "./api.js";

const inr = (n) => (n === null || n === undefined ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);
const pct = (n) => (n === null || n === undefined ? "—" : `${n > 0 ? "+" : ""}${n}%`);

/* Tiny dependency-free chart: position value (solid) vs amount invested (dashed). */
function ValueChart({ series }) {
  if (!series || series.length < 2) return null;
  const W = 560, H = 130, P = 4;
  const vals = series.flatMap((s) => [s.value, s.invested]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const x = (i) => P + (i / (series.length - 1)) * (W - 2 * P);
  const y = (v) => H - P - ((v - min) / (max - min || 1)) * (H - 2 * P);
  const path = (key) => series.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(s[key]).toFixed(1)}`).join("");
  const up = series[series.length - 1].value >= series[series.length - 1].invested;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="bt-chart" preserveAspectRatio="none">
      <path d={path("invested")} fill="none" stroke="var(--muted)" strokeWidth="1.2" strokeDasharray="4 4" opacity="0.7" />
      <path d={path("value")} fill="none" stroke={up ? "var(--buy)" : "var(--sell)"} strokeWidth="1.8" />
    </svg>
  );
}

export default function Backtest() {
  const [tickers, setTickers] = useState([""]);
  const [mode, setMode] = useState("sip");
  const [lumpsum, setLumpsum] = useState(100000);
  const [sipAmount, setSipAmount] = useState(10000);
  const [sipDay, setSipDay] = useState(1);
  const [stepup, setStepup] = useState(0);
  const [years, setYears] = useState(3);
  const [custom, setCustom] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [brokerage, setBrokerage] = useState(0);
  const [dividends, setDividends] = useState(true);
  const [benchmark, setBenchmark] = useState(true);
  const [results, setResults] = useState([]);
  const [warns, setWarns] = useState([]);
  const [narrative, setNarrative] = useState("");
  const [phase, setPhase] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const esRef = useRef(null);

  const showLump = mode !== "sip", showSip = mode !== "lumpsum";

  function run() {
    const ts = tickers.map((t) => t.trim().toUpperCase()).filter(Boolean);
    if (!ts.length || busy) return;
    if (esRef.current) esRef.current.close();
    setResults([]); setWarns([]); setNarrative(""); setError(""); setPhase("");
    setBusy(true);
    const thread = crypto.randomUUID();
    const qs = new URLSearchParams({
      thread, tickers: ts.join(","), mode,
      lumpsum: String(lumpsum), sip_amount: String(sipAmount), sip_day: String(sipDay),
      stepup_pct: String(stepup), brokerage_pct: String(brokerage),
      dividends: dividends ? "1" : "0", benchmark: benchmark ? "1" : "0",
      ...(custom && start && end ? { start, end } : { years: String(years) }),
    });
    const es = new EventSource(`${API}/api/backtest?${qs}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setBusy(false); setPhase(""); return; }
      if (ev.type === "phase") setPhase(ev.text);
      else if (ev.type === "result") setResults((r) => [...r, ev]);
      else if (ev.type === "warn") setWarns((w) => [...w, ev.text]);
      else if (ev.type === "narrative") setNarrative(ev.text);
      else if (ev.type === "error") { setError(ev.text); setBusy(false); es.close(); }
    };
    es.onerror = () => { es.close(); setBusy(false); setError((e) => e || "Stream dropped. Is the backend running?"); };
  }

  const setTicker = (i, v) => setTickers((ts) => ts.map((t, j) => (j === i ? v : t)));

  return (
    <div className="desk">
      <div className="eyebrow">Lumpsum vs SIP · XIRR · dividends · drawdowns · NIFTY benchmark</div>
      <h1>What-if Backtest</h1>
      <p className="sub">"What if I had invested?" — pick stocks, strategy and window; every number is computed from real price history, then an agent reads the result back to you.</p>

      <div className="task-setup bt-form">
        <div className="bt-row">
          {tickers.map((t, i) => (
            <div key={i} className="row1" style={{ flex: 1, minWidth: 220 }}>
              <span className="nse">NSE</span>
              <TickerSearch value={t} onChange={(v) => setTicker(i, v)} disabled={busy} placeholder={`Stock ${i + 1}`} />
              {tickers.length > 1 && <button className="preset" onClick={() => setTickers((ts) => ts.filter((_, j) => j !== i))} disabled={busy}>✕</button>}
            </div>
          ))}
          {tickers.length < 3 && <button className="preset" onClick={() => setTickers((ts) => [...ts, ""])} disabled={busy}>+ Compare another</button>}
        </div>

        <div className="bt-row">
          <label className="bt-field"><span>Strategy</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={busy}>
              <option value="sip">Monthly SIP</option>
              <option value="lumpsum">One-time lumpsum</option>
              <option value="both">Both (compare)</option>
            </select>
          </label>
          {showLump && (
            <label className="bt-field"><span>Lumpsum ₹</span>
              <input type="number" min="1000" step="10000" value={lumpsum} onChange={(e) => setLumpsum(e.target.value)} disabled={busy} />
            </label>
          )}
          {showSip && (
            <>
              <label className="bt-field"><span>SIP ₹ / month</span>
                <input type="number" min="500" step="1000" value={sipAmount} onChange={(e) => setSipAmount(e.target.value)} disabled={busy} />
              </label>
              <label className="bt-field"><span>SIP day (1-28)</span>
                <input type="number" min="1" max="28" value={sipDay} onChange={(e) => setSipDay(e.target.value)} disabled={busy} />
              </label>
              <label className="bt-field"><span>Annual step-up %</span>
                <input type="number" min="0" max="100" step="5" value={stepup} onChange={(e) => setStepup(e.target.value)} disabled={busy} />
              </label>
            </>
          )}
        </div>

        <div className="bt-row">
          <label className="bt-field"><span>Window</span>
            <select value={custom ? "custom" : String(years)} disabled={busy}
              onChange={(e) => { if (e.target.value === "custom") setCustom(true); else { setCustom(false); setYears(Number(e.target.value)); } }}>
              <option value="1">Last 1 year</option>
              <option value="3">Last 3 years</option>
              <option value="5">Last 5 years</option>
              <option value="10">Last 10 years</option>
              <option value="custom">Custom dates…</option>
            </select>
          </label>
          {custom && (
            <>
              <label className="bt-field"><span>From</span><input type="date" value={start} onChange={(e) => setStart(e.target.value)} disabled={busy} /></label>
              <label className="bt-field"><span>To</span><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} disabled={busy} /></label>
            </>
          )}
          <label className="bt-field"><span>Brokerage % / buy</span>
            <input type="number" min="0" max="5" step="0.05" value={brokerage} onChange={(e) => setBrokerage(e.target.value)} disabled={busy} />
          </label>
          <label className="bt-check"><input type="checkbox" checked={dividends} onChange={(e) => setDividends(e.target.checked)} disabled={busy} /> Include dividends</label>
          <label className="bt-check"><input type="checkbox" checked={benchmark} onChange={(e) => setBenchmark(e.target.checked)} disabled={busy} /> vs NIFTY 50</label>
          <button className="run" onClick={run} disabled={busy || !tickers.some((t) => t.trim())}>{busy ? "Running…" : "▶ Run backtest"}</button>
        </div>
      </div>

      {busy && phase && <div className="eco-phase">{phase}</div>}
      {error && <div className="err" style={{ marginTop: 10 }}>⚠ {error}</div>}
      {warns.map((w, i) => <div key={i} className="err" style={{ marginTop: 6 }}>⚠ {w}</div>)}

      {results.length > 0 && (
        <div className="bt-results">
          {results.map((r, i) => (
            <div key={i} className={`eco-card bt-card${r.is_benchmark ? " bt-bench" : ""}`}>
              <div className="eco-card-title">
                {r.ticker} · {r.strategy === "sip" ? "SIP" : "Lumpsum"}
                {r.is_benchmark && <span className="eco-hint">benchmark</span>}
                <span className={(r.abs_return_pct ?? 0) >= 0 ? "up" : "down"} style={{ marginLeft: "auto" }}>{pct(r.abs_return_pct)}</span>
              </div>
              <ValueChart series={r.series} />
              <div className="rp-stats">
                <div className="rp-stat"><span>Invested</span><b>{inr(r.invested)}</b></div>
                <div className="rp-stat"><span>Final value</span><b>{inr(r.final_value)}</b></div>
                {r.dividend_cash > 0 && <div className="rp-stat"><span>Dividend cash</span><b>{inr(r.dividend_cash)}</b></div>}
                <div className="rp-stat"><span>{r.strategy === "sip" ? "XIRR" : "CAGR"}</span><b>{pct(r.strategy === "sip" ? r.xirr_pct : r.cagr_pct)}</b></div>
                <div className="rp-stat"><span>Max drawdown</span><b>{pct(r.max_drawdown_pct)}</b></div>
                <div className="rp-stat"><span>Trades</span><b>{r.trades}</b></div>
                {r.strategy === "sip" && <div className="rp-stat"><span>Avg buy price</span><b>{inr(r.avg_buy_price)}</b></div>}
                {r.strategy === "lumpsum" && <div className="rp-stat"><span>Bought at</span><b>{inr(r.buy_price)} ({r.buy_date})</b></div>}
                {r.best_day_pct !== undefined && r.best_day_pct !== null && <div className="rp-stat"><span>Best / worst day</span><b>{pct(r.best_day_pct)} / {pct(r.worst_day_pct)}</b></div>}
              </div>
            </div>
          ))}
        </div>
      )}

      {narrative && (
        <div className="event" style={{ marginTop: 14 }}>
          <span className="node final" /><div className="label">the read</div>
          <div className="verdict"><div className="thesis"><Markdown>{narrative}</Markdown></div></div>
        </div>
      )}

      <div className="footnote">Solid line = position value, dashed = amount invested. Past performance only — not a prediction, not investment advice.</div>
    </div>
  );
}
