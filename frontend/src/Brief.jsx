import { useState, useRef, useEffect } from "react";
import TickerSearch from "./TickerSearch.jsx";
import Markdown from "./Markdown.jsx";
import { API } from "./api.js";

const LS_KEY = "equity-desk-watchlist";
const pct = (n) => (n === null || n === undefined ? "" : `${n > 0 ? "+" : ""}${n}%`);
const fmt = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 }));

function loadWatchlist() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || []; } catch { return []; }
}

export default function Brief() {
  const [watch, setWatch] = useState(loadWatchlist);
  const [add, setAdd] = useState("");
  const [markets, setMarkets] = useState(null);
  const [stocks, setStocks] = useState([]);
  const [text, setText] = useState("");
  const [phase, setPhase] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const esRef = useRef(null);

  useEffect(() => { localStorage.setItem(LS_KEY, JSON.stringify(watch)); }, [watch]);

  function addTicker() {
    const t = add.trim().toUpperCase();
    if (t && !watch.includes(t) && watch.length < 8) setWatch((w) => [...w, t]);
    setAdd("");
  }

  function generate() {
    if (busy) return;
    if (esRef.current) esRef.current.close();
    setMarkets(null); setStocks([]); setText(""); setError(""); setPhase("");
    setBusy(true);
    const thread = crypto.randomUUID();
    const es = new EventSource(`${API}/api/brief?thread=${thread}&tickers=${encodeURIComponent(watch.join(","))}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setBusy(false); setPhase(""); return; }
      if (ev.type === "phase") setPhase(ev.text);
      else if (ev.type === "markets") setMarkets(ev);
      else if (ev.type === "stock" && !ev.error) setStocks((s) => [...s.filter((x) => x.ticker !== ev.ticker), ev]);
      else if (ev.type === "brief") setText(ev.text);
      else if (ev.type === "error") { setError(ev.text); setBusy(false); es.close(); }
    };
    es.onerror = () => { es.close(); setBusy(false); setError((e) => e || "Stream dropped. Is the backend running?"); };
  }

  return (
    <div className="desk">
      <div className="eyebrow">Global cues · Indian indices · your watchlist, every morning</div>
      <h1>Morning Brief</h1>
      <p className="sub">Build a watchlist once (saved in your browser). One click each morning gets you the overnight moves, your stocks' news, earnings flags and an agent-written brief.</p>

      <div className="task-setup">
        <div className="row1">
          <span className="nse">NSE</span>
          <TickerSearch value={add} onChange={setAdd} disabled={busy} placeholder="Add a stock to your watchlist…" />
          <button className="preset" onClick={addTicker} disabled={busy || !add.trim() || watch.length >= 8}>+ Add</button>
          <button className="run" onClick={generate} disabled={busy}>{busy ? "Assembling…" : "☀️ Generate brief"}</button>
        </div>
        {watch.length > 0 && (
          <div className="pf-chips" style={{ marginTop: 8 }}>
            {watch.map((t) => (
              <span key={t} className="pf-chip">{t} <button className="bf-x" onClick={() => setWatch((w) => w.filter((x) => x !== t))} disabled={busy}>✕</button></span>
            ))}
          </div>
        )}
        {watch.length === 0 && <div className="footnote" style={{ marginTop: 6 }}>No watchlist yet — the brief will still cover global + Indian markets.</div>}
      </div>

      {busy && phase && <div className="eco-phase">{phase}</div>}
      {error && <div className="err" style={{ marginTop: 10 }}>⚠ {error}</div>}

      {markets && (
        <>
          <div className="bf-strip">
            {markets.india.map((m) => (
              <div key={m.index} className="bf-tile">
                <span className="bf-name">{m.index}</span>
                <span className="bf-level">{fmt(m.level)}</span>
                <span className={`bf-chg ${m.day_change_pct >= 0 ? "up" : "down"}`}>{pct(m.day_change_pct)}</span>
              </div>
            ))}
          </div>
          <div className="bf-strip">
            {markets.global.map((m) => (
              <div key={m.name} className="bf-tile bf-global">
                <span className="bf-name">{m.name}</span>
                <span className="bf-level">{fmt(m.level)}</span>
                <span className={`bf-chg ${m.change_pct >= 0 ? "up" : "down"}`}>{pct(m.change_pct)}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {stocks.length > 0 && (
        <div className="eco-grid">
          {stocks.map((s) => (
            <div key={s.ticker} className="eco-card">
              <div className="eco-card-title">
                {s.ticker} <span className={s.day_change_pct >= 0 ? "up" : "down"}>₹{fmt(s.price)} {pct(s.day_change_pct)}</span>
              </div>
              {s.earnings_in_days !== undefined && <div className="bf-flag">📅 Results in {s.earnings_in_days} day{s.earnings_in_days === 1 ? "" : "s"} ({s.earnings_date})</div>}
              {s.rsi_flag && <div className="bf-flag">⚡ RSI {s.rsi_14} — {s.rsi_flag}</div>}
              {(s.headlines || []).slice(0, 2).map((h, i) => <div key={i} className="eco-item" style={{ fontSize: 12.5 }}>• {h}</div>)}
            </div>
          ))}
        </div>
      )}

      {text && (
        <div className="event" style={{ marginTop: 14 }}>
          <span className="node final" /><div className="label">today's brief</div>
          <div className="verdict"><div className="thesis"><Markdown>{text}</Markdown></div></div>
        </div>
      )}

      <div className="footnote">Watchlist lives only in this browser. Informational only, not investment advice.</div>
    </div>
  );
}
