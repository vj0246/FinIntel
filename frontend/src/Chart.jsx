import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export default function Chart({ series, ticker, changePct }) {
  if (!series || series.length === 0) return null;
  const up = (changePct ?? 0) >= 0;
  const color = up ? "#3fb950" : "#f85149";
  const data = series.map((p) => ({ x: p.date || p.i, close: p.close }));
  return (
    <div className="chart">
      <div className="chart-head">
        <span className="chart-ticker">{ticker}</span>
        <span className="chart-change" style={{ color }}>
          {up ? "▲" : "▼"} {Math.abs(changePct ?? 0).toFixed(2)}% · 6mo
        </span>
      </div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
          <XAxis dataKey="x" hide />
          <YAxis domain={["auto", "auto"]} tick={{ fill: "#8b96a5", fontSize: 10 }} width={44} />
          <Tooltip
            contentStyle={{ background: "#0b0e14", border: "1px solid #232c38", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#8b96a5" }} itemStyle={{ color }} />
          <Line type="monotone" dataKey="close" stroke={color} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
