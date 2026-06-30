import { useState } from "react";
import Analyst from "./Analyst.jsx";
import Chat from "./Chat.jsx";

export default function App() {
  // shared ticker: the side chat follows the analyst unless changed independently
  const [ticker, setTicker] = useState("");
  // mobile tab state: "analyst" or "chat"
  const [mobileTab, setMobileTab] = useState("analyst");

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">▦</span>
          <span className="brand-name">Agentic Equity Desk</span>
        </div>
        <div className="topbar-sub">Multi-step agent · human-in-the-loop · NSE</div>
      </header>

      {/* Mobile tab switcher — hidden on desktop via CSS */}
      <nav className="mobile-tabs">
        <button
          className={mobileTab === "analyst" ? "active" : ""}
          onClick={() => setMobileTab("analyst")}
        >
          📊 Analyst
        </button>
        <button
          className={mobileTab === "chat" ? "active" : ""}
          onClick={() => setMobileTab("chat")}
        >
          💬 Chat
        </button>
      </nav>

      <div className="app">
        <main className={`main${mobileTab !== "analyst" ? " tab-hidden" : ""}`}>
          <Analyst ticker={ticker} setTicker={setTicker} />
        </main>
        <aside className={`side${mobileTab !== "chat" ? " tab-hidden" : ""}`}>
          <Chat ticker={ticker} setTicker={setTicker} />
        </aside>
      </div>
    </div>
  );
}