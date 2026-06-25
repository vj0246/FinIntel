import { useState } from "react";
import Analyst from "./Analyst.jsx";
import Chat from "./Chat.jsx";

export default function App() {
  // shared ticker: the side chat follows the analyst unless changed independently
  const [ticker, setTicker] = useState("");

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">▦</span>
          <span className="brand-name">Agentic Equity Desk</span>
        </div>
        <div className="topbar-sub">Multi-step agent · human-in-the-loop · NSE</div>
      </header>
      <div className="app">
        <main className="main">
          <Analyst ticker={ticker} setTicker={setTicker} />
        </main>
        <aside className="side">
          <Chat ticker={ticker} setTicker={setTicker} />
        </aside>
      </div>
    </div>
  );
}