import { useState } from "react";

const LS_KEY = "equity-desk-risk-profile";

export function getProfile() {
  try { return JSON.parse(localStorage.getItem(LS_KEY))?.profile || ""; } catch { return ""; }
}

const QUESTIONS = [
  ["How long can this money stay invested?",
    ["Under 1 year", "1–3 years", "3–10 years", "Over 10 years"]],
  ["Your portfolio falls 20% in a month. You…",
    ["Sell everything", "Sell some, sleep badly", "Hold and wait", "Buy more"]],
  ["Your experience with equities?",
    ["None yet", "Under 2 years", "2–5 years", "5+ years"]],
  ["Your income situation?",
    ["Irregular / dependent on this money", "Stable but tight", "Stable with some savings", "Stable with strong savings"]],
  ["What are you investing for?",
    ["Protecting capital", "Steady income", "Long-term growth", "Maximum growth, risk accepted"]],
];

const PROFILE_DESC = {
  conservative: "Capital preservation first. The desk will flag volatile, high-beta and speculative names as unsuitable for you.",
  balanced: "Growth with guardrails. The desk flags concentrated bets and volatility above ~35%.",
  aggressive: "Risk-tolerant. The desk still shows the risks — it just won't nag you about ordinary volatility.",
};

export default function RiskProfile({ onClose, onSaved }) {
  const [answers, setAnswers] = useState(() => {
    try { return JSON.parse(localStorage.getItem(LS_KEY))?.answers || Array(5).fill(null); }
    catch { return Array(5).fill(null); }
  });

  const done = answers.every((a) => a !== null);
  const score = answers.reduce((s, a) => s + (a || 0), 0);
  const profile = score <= 5 ? "conservative" : score <= 10 ? "balanced" : "aggressive";

  function save() {
    localStorage.setItem(LS_KEY, JSON.stringify({ profile, answers, saved: new Date().toISOString() }));
    onSaved?.(profile);
    onClose();
  }

  function clear() {
    localStorage.removeItem(LS_KEY);
    onSaved?.("");
    onClose();
  }

  return (
    <div className="rp-overlay" onClick={onClose}>
      <div className="rp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="rp-modal-head">
          <b>Your risk profile</b>
          <button className="bf-x" onClick={onClose} style={{ fontSize: 14 }}>✕</button>
        </div>
        <p className="footnote" style={{ margin: "4px 0 10px" }}>
          Five questions, saved only in this browser. Every agent then judges suitability against your profile — a SEBI-style suitability layer.
        </p>
        {QUESTIONS.map(([q, opts], qi) => (
          <div key={qi} className="rp-q">
            <div className="rp-q-text">{qi + 1}. {q}</div>
            <div className="rp-opts">
              {opts.map((o, oi) => (
                <button key={oi} className={`rp-opt${answers[qi] === oi ? " active" : ""}`}
                  onClick={() => setAnswers((a) => a.map((v, i) => (i === qi ? oi : v)))}>{o}</button>
              ))}
            </div>
          </div>
        ))}
        {done && (
          <div className="rp-result">
            <span className={`pf-chip rp-badge-${profile}`}>{profile.toUpperCase()}</span>
            <span>{PROFILE_DESC[profile]}</span>
          </div>
        )}
        <div className="gate-btns" style={{ marginTop: 12 }}>
          <button className="approve" onClick={save} disabled={!done}>✓ Save profile</button>
          <button className="reject" onClick={clear}>Clear profile</button>
        </div>
      </div>
    </div>
  );
}
