import { useState } from "react";
import Analyst from "./Analyst.jsx";
import Portfolio from "./Portfolio.jsx";
import WarRoom from "./WarRoom.jsx";
import Chat from "./Chat.jsx";

export default function App() {
  // shared ticker: the side chat follows the analyst unless changed independently
  const [ticker, setTicker] = useState("");
  // which panel fills the main area on desktop
  const [view, setView] = useState("analyst");   // "analyst" | "portfolio" | "war"
  // mobile tab state: "analyst" | "portfolio" | "chat"
  const [mobileTab, setMobileTab] = useState("analyst");

  const showMain = mobileTab !== "chat";
  const mainView = mobileTab === "chat" ? view : mobileTab;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">▦</span>
          <span className="brand-name">Agentic Equity Desk</span>
        </div>
        <nav className="view-tabs" aria-label="Main view">
          <button className={mainView === "analyst" ? "active" : ""} onClick={() => { setView("analyst"); setMobileTab("analyst"); }}>📊 Analyst</button>
          <button className={mainView === "portfolio" ? "active" : ""} onClick={() => { setView("portfolio"); setMobileTab("portfolio"); }}>💼 Portfolio</button>
          <button className={mainView === "war" ? "active" : ""} onClick={() => { setView("war"); setMobileTab("war"); }}>⚔️ War Room</button>
        </nav>
        <div className="topbar-sub">Multi-step agent · human-in-the-loop · NSE</div>
      </header>

      {/* Mobile tab switcher — hidden on desktop via CSS */}
      <nav className="mobile-tabs" aria-label="Panel switcher">
        <button className={mobileTab === "analyst" ? "active" : ""} onClick={() => { setMobileTab("analyst"); setView("analyst"); }} aria-selected={mobileTab === "analyst"}>
          📊 Analyst
        </button>
        <button className={mobileTab === "portfolio" ? "active" : ""} onClick={() => { setMobileTab("portfolio"); setView("portfolio"); }} aria-selected={mobileTab === "portfolio"}>
          💼 Portfolio
        </button>
        <button className={mobileTab === "war" ? "active" : ""} onClick={() => { setMobileTab("war"); setView("war"); }} aria-selected={mobileTab === "war"}>
          ⚔️ War Room
        </button>
        <button className={mobileTab === "chat" ? "active" : ""} onClick={() => setMobileTab("chat")} aria-selected={mobileTab === "chat"}>
          💬 Chat
        </button>
      </nav>

      <div className="app">
        <main className={`main${!showMain ? " tab-hidden" : ""}`}>
          {mainView === "portfolio" ? <Portfolio /> : mainView === "war" ? <WarRoom /> : <Analyst ticker={ticker} setTicker={setTicker} />}
        </main>
        <aside className={`side${mobileTab !== "chat" ? " tab-hidden" : ""}`}>
          <Chat ticker={ticker} setTicker={setTicker} />
        </aside>
      </div>
    </div>
  );
}
