import { useState, useRef, useEffect } from "react";
import TickerSearch from "./TickerSearch.jsx";
import Markdown from "./Markdown.jsx";
import { API } from "./api.js";

const fmt = (v, dash = "—") => (v === null || v === undefined ? dash : v);
const inr = (v) => (v === null || v === undefined ? "—" : `₹${Number(v).toLocaleString("en-IN")}`);

const SECTIONS = [
  ["customers", "🧑‍💼 Customers", "Who it sells to"],
  ["suppliers", "🏭 Suppliers & vendors", "Who it buys from"],
  ["partners", "🤝 Partners & alliances", "Who it works with"],
  ["subsidiaries", "🏢 Subsidiaries", "What it owns"],
];

export default function Ecosystem() {
  const [ticker, setTicker] = useState("");
  const [profile, setProfile] = useState(null);
  const [eco, setEco] = useState(null);
  const [peers, setPeers] = useState([]);
  const [phases, setPhases] = useState([]);
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const esRef = useRef(null);
  const bottom = useRef(null);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [peers, summary, error]);

  function start() {
    if (!ticker.trim() || busy) return;
    if (esRef.current) esRef.current.close();
    setProfile(null); setEco(null); setPeers([]); setPhases([]); setSummary(""); setError("");
    setBusy(true);
    const thread = crypto.randomUUID();
    const es = new EventSource(`${API}/api/ecosystem?ticker=${encodeURIComponent(ticker.trim())}&thread=${thread}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setBusy(false); return; }
      if (ev.type === "phase") setPhases((p) => [...p, ev.text]);
      else if (ev.type === "profile") setProfile(ev);
      else if (ev.type === "map") setEco(ev.ecosystem);
      else if (ev.type === "peer") setPeers((p) => [...p.filter((x) => x.ticker !== ev.ticker), ev]
        .sort((a, b) => (b.is_self ? 1 : 0) - (a.is_self ? 1 : 0) || (b.market_cap_cr || 0) - (a.market_cap_cr || 0)));
      else if (ev.type === "summary") setSummary(ev.text);
      else if (ev.type === "error") { setError(ev.text); setBusy(false); es.close(); }
    };
    es.onerror = () => { es.close(); setBusy(false); if (!summary) setError("Stream dropped. Is the backend running?"); };
  }

  return (
    <div className="desk">
      <div className="eyebrow">Value chain · competitors priced live · dependencies</div>
      <h1>Company Ecosystem</h1>
      <p className="sub">Enter a company and see who it competes with, sells to, buys from and partners with — competitors are priced live for a real side-by-side.</p>

      <div className="task-setup">
        <div className="row1">
          <span className="nse">NSE</span>
          <TickerSearch value={ticker} onChange={setTicker} disabled={busy} placeholder="Company / ticker (e.g. TATAMOTORS)" />
          <button className="run" onClick={start} disabled={busy || !ticker.trim()}>{busy ? "Mapping…" : "▶ Map it"}</button>
        </div>
      </div>

      {!profile && !busy && !error && (
        <div className="empty">Pick a stock. The desk maps its business ecosystem — customers, vendors, rivals, segments — with live peer pricing.</div>
      )}

      {busy && phases.length > 0 && <div className="eco-phase">{phases[phases.length - 1]}</div>}
      {error && <div className="err">⚠ {error}</div>}

      {profile && (
        <div className="eco-head">
          <div className="eco-title">{profile.name} <span className="pf-chip">{profile.ticker}</span>
            {profile.source !== "live" && <span className="pf-chip">sample data</span>}
          </div>
          <div className="eco-meta">
            {profile.sector && <span>{profile.sector}</span>}
            {profile.industry && <span>{profile.industry}</span>}
            {profile.price != null && <span>{inr(profile.price)}</span>}
            {profile.market_cap_cr != null && <span>M-cap {inr(profile.market_cap_cr)} cr</span>}
            {profile.pe != null && <span>PE {profile.pe}</span>}
          </div>
        </div>
      )}

      {eco && (
        <>
          {eco.moat && <div className="eco-moat">🏰 <b>Moat:</b> {eco.moat}</div>}

          <div className="eco-grid">
            {SECTIONS.map(([key, title, hint]) =>
              (eco[key] || []).length > 0 && (
                <div key={key} className="eco-card">
                  <div className="eco-card-title">{title} <span className="eco-hint">{hint}</span></div>
                  {eco[key].map((it, i) => (
                    <div key={i} className="eco-item"><b>{it.name}</b>{it.note && <span> — {it.note}</span>}</div>
                  ))}
                </div>
              )
            )}
            {(eco.revenue_segments || []).length > 0 && (
              <div className="eco-card">
                <div className="eco-card-title">📦 Revenue segments</div>
                {eco.revenue_segments.map((s, i) => (
                  <div key={i} className="eco-seg">
                    <span>{s.segment}</span>
                    {s.approx_share_pct != null && (
                      <span className="eco-seg-bar"><i style={{ width: `${Math.min(100, s.approx_share_pct)}%` }} /><em>~{s.approx_share_pct}%</em></span>
                    )}
                  </div>
                ))}
              </div>
            )}
            {(eco.key_inputs || []).length > 0 && (
              <div className="eco-card">
                <div className="eco-card-title">⚙️ Key inputs & cost drivers</div>
                <div className="pf-chips">{eco.key_inputs.map((x, i) => <span key={i} className="pf-chip">{x}</span>)}</div>
              </div>
            )}
            {(eco.key_risks || []).length > 0 && (
              <div className="eco-card eco-risk">
                <div className="eco-card-title">⚠️ Key risks</div>
                {eco.key_risks.map((r, i) => <div key={i} className="eco-item">{r}</div>)}
              </div>
            )}
          </div>
        </>
      )}

      {peers.length > 0 && (
        <div className="eco-peers">
          <div className="eco-card-title">🥊 Competitive set — live numbers</div>
          <div className="pf-tablewrap">
            <table className="pf-table">
              <thead><tr><th>Company</th><th>Price</th><th>6m %</th><th>PE</th><th>PB</th><th>M-cap (₹ cr)</th><th>ROE %</th><th>Yield %</th></tr></thead>
              <tbody>
                {peers.map((p) => (
                  <tr key={p.ticker} className={p.is_self ? "eco-self" : ""}>
                    <td>{p.name || p.ticker}{p.is_self ? " ★" : ""}</td>
                    <td>{inr(p.price)}</td>
                    <td className={p.change_6m_pct >= 0 ? "up" : "down"}>{fmt(p.change_6m_pct)}</td>
                    <td>{fmt(p.pe)}</td><td>{fmt(p.pb)}</td>
                    <td>{p.market_cap_cr != null ? Number(p.market_cap_cr).toLocaleString("en-IN") : "—"}</td>
                    <td>{fmt(p.roe_pct)}</td><td>{fmt(p.dividend_yield_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {summary && (
        <div className="event" style={{ marginTop: 14 }}>
          <span className="node final" /><div className="label">ecosystem read</div>
          <div className="verdict"><div className="thesis"><Markdown>{summary}</Markdown></div></div>
        </div>
      )}

      <div ref={bottom} />
      <div className="footnote">Relationship map is analyst knowledge grounded in live data; verify before acting. Informational only, not investment advice.</div>
    </div>
  );
}
