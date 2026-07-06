import { useState } from "react";
import Analyst from "./Analyst.jsx";
import Portfolio from "./Portfolio.jsx";
import WarRoom from "./WarRoom.jsx";
import Ecosystem from "./Ecosystem.jsx";
import Discover from "./Discover.jsx";
import Brief from "./Brief.jsx";
import Report from "./Report.jsx";
import Backtest from "./Backtest.jsx";
import Chat from "./Chat.jsx";
import RiskProfile, { getProfile } from "./RiskProfile.jsx";
import AuthModal, { getAuth, signOut } from "./AuthModal.jsx";

const VIEWS = [
  ["analyst", "📊 Analyst"],
  ["brief", "🌅 Brief"],
  ["discover", "🔎 Discover"],
  ["portfolio", "💼 Portfolio"],
  ["war", "⚔️ War Room"],
  ["eco", "🕸️ Ecosystem"],
  ["report", "📑 Report"],
  ["backtest", "⏳ Backtest"],
];

export default function App() {
  // shared ticker: the side chat follows the analyst unless changed independently
  const [ticker, setTicker] = useState("");
  // which panel fills the main area on desktop
  const [view, setView] = useState("analyst");   // "analyst" | "portfolio" | "war" | "eco"
  // mobile tab state: main views + "chat"
  const [mobileTab, setMobileTab] = useState("analyst");
  const [showProfile, setShowProfile] = useState(false);
  const [profile, setProfile] = useState(getProfile);
  const [showAuth, setShowAuth] = useState(false);
  const [user, setUser] = useState(() => getAuth()?.email || "");

  const showMain = mobileTab !== "chat";
  const mainView = mobileTab === "chat" ? view : mobileTab;

  const pick = (v) => { setView(v); setMobileTab(v); };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">▦</span>
          <span className="brand-name">Agentic Equity Desk</span>
        </div>
        <nav className="view-tabs" aria-label="Main view">
          {VIEWS.map(([v, label]) => (
            <button key={v} className={mainView === v ? "active" : ""} onClick={() => pick(v)}>{label}</button>
          ))}
        </nav>
        <div className="topbar-right">
          <button className={`profile-btn${profile ? ` rp-badge-${profile}` : ""}`}
            onClick={() => setShowProfile(true)}
            title="Set your risk profile — agents judge suitability against it">
            {profile ? `🛡 ${profile}` : "🛡 Risk profile"}
          </button>
          {user ? (
            <button className="profile-btn" title="Signed in — click to sign out"
              onClick={() => { signOut(); setUser(""); }}>
              👤 {user.split("@")[0]} ✕
            </button>
          ) : (
            <button className="profile-btn" onClick={() => setShowAuth(true)}
              title="Sign in to keep your risk profile against your email">
              👤 Sign in
            </button>
          )}
        </div>
      </header>
      {showProfile && <RiskProfile onClose={() => setShowProfile(false)} onSaved={setProfile} />}
      {showAuth && <AuthModal onClose={() => setShowAuth(false)}
        onSignedIn={(email, prof) => { setUser(email); if (prof) setProfile(prof); }} />}

      {/* Mobile tab switcher — hidden on desktop via CSS */}
      <nav className="mobile-tabs" aria-label="Panel switcher">
        {VIEWS.map(([v, label]) => (
          <button key={v} className={mobileTab === v ? "active" : ""} onClick={() => pick(v)} aria-selected={mobileTab === v}>
            {label}
          </button>
        ))}
        <button className={mobileTab === "chat" ? "active" : ""} onClick={() => setMobileTab("chat")} aria-selected={mobileTab === "chat"}>
          💬 Chat
        </button>
      </nav>

      <div className="app">
        <main className={`main${!showMain ? " tab-hidden" : ""}`}>
          {mainView === "portfolio" ? <Portfolio /> : mainView === "war" ? <WarRoom /> :
           mainView === "eco" ? <Ecosystem /> : mainView === "discover" ? <Discover /> :
           mainView === "brief" ? <Brief /> : mainView === "report" ? <Report /> :
           mainView === "backtest" ? <Backtest /> : <Analyst ticker={ticker} setTicker={setTicker} />}
        </main>
        <aside className={`side${mobileTab !== "chat" ? " tab-hidden" : ""}`}>
          <Chat ticker={ticker} setTicker={setTicker} />
        </aside>
      </div>
    </div>
  );
}
