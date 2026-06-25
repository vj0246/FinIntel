import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from "recharts";

const fmtINR = (v) => "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: v < 100 ? 2 : 0 });

export default function Chart({ series, ticker, changePct }) {
  if (!series || series.length === 0) return null;
  const up = (changePct ?? 0) >= 0;
  const color = up ? "#16a34a" : "#dc2626";

  const hasDates = series.some((p) => p.date);
  const data = series.map((p, i) => ({ x: p.date || i, close: p.close }))
                     .filter((d) => typeof d.close === "number" && d.close === d.close);
  if (data.length === 0) return null;

  // Padded domain so the line isn't glued to the top/bottom edges and the scale reads cleanly.
  const closes = data.map((d) => d.close);
  const lo = Math.min(...closes), hi = Math.max(...closes);
  const pad = (hi - lo) * 0.12 || hi * 0.02 || 1;
  const domain = [Math.floor(lo - pad), Math.ceil(hi + pad)];

  const fmtDate = (v) => {
    if (typeof v !== "string") return v;
    const d = new Date(v);
    return isNaN(d) ? v : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  };
  const fmtFull = (v) => {
    if (typeof v !== "string") return `Point ${v}`;
    const d = new Date(v);
    return isNaN(d) ? v : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  };

  return (
    <div className="chart">
      <div className="chart-head">
        <span className="chart-ticker">{ticker}</span>
        <span className="chart-change" style={{ color }}>
          {up ? "▲" : "▼"} {Math.abs(changePct ?? 0).toFixed(2)}% · 6mo
        </span>
      </div>
      <ResponsiveContainer width="100%" height={172}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 2, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" vertical={false} />
          <XAxis
            dataKey="x"
            tickFormatter={fmtDate}
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            tickMargin={6}
            minTickGap={28}
            interval="preserveStartEnd"
            axisLine={{ stroke: "#e2e8f0" }}
            tickLine={false}
          />
          <YAxis
            domain={domain}
            tickFormatter={fmtINR}
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            width={62}
            tickCount={5}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 12, boxShadow: "0 4px 16px rgba(15,23,42,0.07)" }}
            labelStyle={{ color: "#475569", marginBottom: 2 }}
            itemStyle={{ color }}
            labelFormatter={hasDates ? fmtFull : undefined}
            formatter={(val) => [fmtINR(val), "Close"]}
          />
          <Line type="monotone" dataKey="close" stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
