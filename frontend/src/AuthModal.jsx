import { useState } from "react";
import { API } from "./api.js";

const AUTH_KEY = "equity-desk-auth";
const PROFILE_KEY = "equity-desk-risk-profile";

export function getAuth() {
  try { return JSON.parse(localStorage.getItem(AUTH_KEY)) || null; } catch { return null; }
}

export function signOut() {
  localStorage.removeItem(AUTH_KEY);
}

/* Push the server-stored profile into localStorage so every agent picks it up. */
function syncProfile(profile, answers) {
  if (profile) {
    localStorage.setItem(PROFILE_KEY, JSON.stringify({ profile, answers: answers || Array(5).fill(null), saved: new Date().toISOString() }));
  }
}

export default function AuthModal({ onClose, onSignedIn }) {
  const [mode, setMode] = useState("login");     // login | signup
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (busy || !email.trim() || !password) return;
    setBusy(true); setError("");
    try {
      const r = await fetch(`${API}/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Something went wrong.");
      localStorage.setItem(AUTH_KEY, JSON.stringify({ token: d.token, email: d.email }));
      syncProfile(d.profile, d.answers);
      onSignedIn?.(d.email, d.profile || "");
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rp-overlay" onClick={onClose}>
      <div className="rp-modal" style={{ width: "min(400px, 100%)" }} onClick={(e) => e.stopPropagation()}>
        <div className="rp-modal-head">
          <b>{mode === "login" ? "Sign in" : "Create your account"}</b>
          <button className="bf-x" onClick={onClose} style={{ fontSize: 14 }}>✕</button>
        </div>
        <p className="footnote" style={{ margin: "4px 0 12px" }}>
          Your risk profile is saved against your email — set it once, use it from any device, change it any time.
        </p>
        <div className="auth-fields">
          <input type="email" placeholder="Email" value={email} autoComplete="email"
            onChange={(e) => setEmail(e.target.value)} disabled={busy}
            onKeyDown={(e) => e.key === "Enter" && submit()} />
          <input type="password" placeholder={mode === "signup" ? "Password (min 8 characters)" : "Password"}
            value={password} autoComplete={mode === "signup" ? "new-password" : "current-password"}
            onChange={(e) => setPassword(e.target.value)} disabled={busy}
            onKeyDown={(e) => e.key === "Enter" && submit()} />
        </div>
        {error && <div className="err" style={{ marginTop: 8 }}>⚠ {error}</div>}
        <div className="gate-btns" style={{ marginTop: 12 }}>
          <button className="approve" onClick={submit} disabled={busy || !email.trim() || !password}>
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Sign up"}
          </button>
        </div>
        <div className="footnote" style={{ marginTop: 10 }}>
          {mode === "login" ? (
            <>New here? <a className="auth-switch" onClick={() => { setMode("signup"); setError(""); }}>Create an account</a></>
          ) : (
            <>Already have an account? <a className="auth-switch" onClick={() => { setMode("login"); setError(""); }}>Sign in</a></>
          )}
        </div>
      </div>
    </div>
  );
}
