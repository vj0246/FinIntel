import { useState, useRef, useEffect } from "react";
import Chart from "./Chart.jsx";

const API = "http://localhost:8000";
const SUGGEST = ["Do a fundamental analysis", "Why did it fall recently?", "Technical view & chart", "Bull vs bear case", "Buy, hold or sell?"];

const TOOL_LABEL = {
  get_quote: "Quote", get_price_chart: "Chart", get_fundamentals: "Fundamentals",
  get_valuation: "Valuation", get_fundamental_analysis: "Fundamental analysis",
  get_technical_analysis: "Technical analysis", explain_price_move: "Reason for the move",
  get_risk_assessment: "Risk assessment", get_bull_bear_case: "Bull vs bear",
  analyze_news_sentiment: "News sentiment", get_news_headlines: "News headlines",
  get_splits: "Stock splits", get_dividends: "Dividends", get_52week_range: "52-week range",
  get_performance: "Performance", get_analyst_ratings: "Analyst ratings",
  get_quarterly_results: "Quarterly results", get_key_stats: "Key stats",
  deep_desk_analysis: "Desk analysis",
};

export default function Chat() {
  const [ticker, setTicker] = useState("RELIANCE");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const esRef = useRef(null);
  const thread = useRef(crypto.randomUUID());
  const bottom = useRef(null);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  function reset() {
    if (esRef.current) esRef.current.close();
    thread.current = crypto.randomUUID();   // fresh conversation memory
    setMsgs([]); setInput(""); setBusy(false);
  }

  function ask(text) {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", text: q }, { role: "assistant", steps: [], chart: null, answer: "", loading: true }]);

    if (esRef.current) esRef.current.close();
    const url = `${API}/api/chat?ticker=${encodeURIComponent(ticker)}&q=${encodeURIComponent(q)}&thread=${thread.current}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setBusy(false); setMsgs((m) => patchLast(m, { loading: false })); return; }
      setMsgs((m) => {
        const last = m[m.length - 1];
        if (last?.role !== "assistant") return m;
        if (ev.type === "tool_call") return patchLast(m, { steps: [...last.steps, { name: ev.name, args: ev.args }] });
        if (ev.type === "chart") return patchLast(m, { chart: { series: ev.series, ticker: ev.ticker, changePct: ev.change_pct } });
        if (ev.type === "answer") return patchLast(m, { answer: ev.text });
        if (ev.type === "tool_result") return m; // kept quiet; tool_call already shown
        if (ev.type === "error") return patchLast(m, { answer: "⚠ " + ev.text });
        return m;
      });
    };
    es.onerror = () => { es.close(); setBusy(false); setMsgs((m) => patchLast(m, { loading: false, answer: m[m.length - 1].answer || "⚠ Connection dropped. Is the backend running?" })); };
  }

  return (
    <div className="chat">
      <div className="chat-top">
        <div className="chat-title-row">
          <div className="chat-title">Ask about a stock</div>
          <button className="chat-refresh" onClick={reset} disabled={busy} title="Clear chat & start fresh" aria-label="Clear chat">↻ New</button>
        </div>
        <div className="chat-sub">Free-form Q&amp;A — it answers instantly and picks its own tools, no step-by-step approvals. (The Analyst on the left works one approved step at a time.)</div>
        <div className="chat-ticker-row">
          <span className="nse">NSE</span>
          <input
            className="ticker-input"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="Stock symbol, e.g. RELIANCE"
            spellCheck={false}
          />
        </div>
      </div>

      <div className="chat-body">
        {msgs.length === 0 && (
          <div className="chat-empty">
            <p>Pick a stock, ask anything.</p>
            <div className="suggest">
              {SUGGEST.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="bubble user">{m.text}</div>
          ) : (
            <div key={i} className="bubble bot">
              {m.steps.length > 0 && (
                <div className="steps">
                  {m.steps.map((s, j) => <span key={j} className="step-chip">{TOOL_LABEL[s.name] || s.name}</span>)}
                </div>
              )}
              {m.chart && <Chart series={m.chart.series} ticker={m.chart.ticker} changePct={m.chart.changePct} />}
              {m.answer && <div className="bot-text">{m.answer}</div>}
              {m.loading && !m.answer && <div className="dots"><i /><i /><i /></div>}
            </div>
          )
        )}
        <div ref={bottom} />
      </div>

      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder={`Ask about ${ticker}…`}
          disabled={busy}
        />
        <button onClick={() => ask()} disabled={busy || !input.trim()}>Send</button>
      </div>
    </div>
  );
}

function patchLast(arr, patch) {
  const copy = arr.slice();
  copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
  return copy;
}
