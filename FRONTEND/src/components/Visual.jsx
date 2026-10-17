import { Download } from "lucide-react";
import { downloadCsv, viewToRows } from "../lib/export";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const axis = {
  tick: { fill: "#94A3B8", fontSize: 10 },
  axisLine: false,
  tickLine: false,
};
const tooltip = {
  contentStyle: {
    backgroundColor: "#0f172a",
    border: "1px solid rgba(148,163,184,0.2)",
    borderRadius: "10px",
    color: "#E2E8F0",
  },
};

const TAGS = {
  breach: "critical",
  pending: "warning",
  "not producing": "critical",
  producing: "stable",
};

function tagFor(column, value) {
  if (column === "producing") return value === 1 || value === "yes" ? "producing" : "not producing";
  if (column === "status" && TAGS[value]) return value;
  return null;
}

function Cell({ column, value }) {
  const tag = tagFor(column, value);
  if (!tag) return <>{String(value ?? "")}</>;
  return <span className={`table-tag ${TAGS[tag].replace(/\s+/g, "-")}`}>{tag}</span>;
}

export function DataTable({ view }) {
  return (
    <div className='table-shell'>
      <table>
        <thead>
          <tr>
            {view.columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {view.rows.map((row, i) => (
            <tr key={i}>
              {view.columns.map((c) => (
                <td key={c.key}>
                  <Cell column={c.key} value={row[c.key]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {view.rows.length === 0 && <p className='viz-empty'>No matching records.</p>}
    </div>
  );
}

function WellCard({ view }) {
  return (
    <div className='viz-card'>
      <div className='viz-card-head'>
        <div>
          <strong>{view.title}</strong>
          <small>{view.subtitle}</small>
        </div>
        <span className={`table-tag ${view.producing ? "stable" : "critical"}`}>{view.headline}</span>
      </div>
      <div className='viz-metrics'>
        {view.metrics.map((m) => (
          <div key={m.label}>
            <small>{m.label}</small>
            <strong>{m.value}</strong>
            <em>{m.sub}</em>
          </div>
        ))}
      </div>
      <dl className='viz-facts'>
        {view.facts.map((f) => (
          <div key={f.label}>
            <dt>{f.label}</dt>
            <dd>
              {f.value}
              {f.flag && <span className='viz-flag'>{f.flag}</span>}
            </dd>
          </div>
        ))}
      </dl>
      {[
        ["Active notes", view.notes, (n) => `${n.author}: ${n.text} (${n.status}, ${n.from} → ${n.to ?? "open"})`],
        ["Upcoming", view.upcoming, (n) => `${n.author}: ${n.text} (from ${n.from})`],
        ["Open repairs", view.repairs, (r) => `${r.id} · ${r.text}`],
        ["Corrections", view.corrections, (c) => c.text],
      ].map(
        ([title, list, fmt]) =>
          list?.length > 0 && (
            <div key={title} className='viz-list'>
              <small>{title}</small>
              {list.map((x, i) => (
                <p key={i}>{fmt(x)}</p>
              ))}
            </div>
          ),
      )}
    </div>
  );
}

function GenericCard({ view }) {
  return (
    <div className='viz-card'>
      <dl className='viz-facts'>
        {view.items.map((f) => (
          <div key={f.label}>
            <dt>{f.label}</dt>
            <dd>{String(f.value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function BarView({ view }) {
  return (
    <div className='viz-chart'>
      <ResponsiveContainer width='100%' height='100%'>
        <BarChart data={view.items}>
          <CartesianGrid stroke='rgba(148,163,184,0.1)' vertical={false} />
          <XAxis dataKey='label' {...axis} />
          <YAxis {...axis} />
          <Tooltip {...tooltip} formatter={(v) => [`${v} ${view.unit}`, ""]} />
          <Bar dataKey='value' radius={[6, 6, 0, 0]} fill='#0EA5E9' />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ProducingDot({ cx, cy, payload }) {
  if (cx === undefined || cy === undefined) return null;
  return payload.producing ? (
    <circle cx={cx} cy={cy} r={3} fill='#10B981' />
  ) : (
    <circle cx={cx} cy={cy} r={5} fill='#F43F5E' stroke='#fff' strokeWidth={1} />
  );
}

function LineView({ view }) {
  const down = view.points.filter((p) => !p.producing).length;
  return (
    <>
      <div className='viz-chart'>
        <ResponsiveContainer width='100%' height='100%'>
          <LineChart data={view.points}>
            <CartesianGrid stroke='rgba(148,163,184,0.1)' vertical={false} />
            <XAxis dataKey='date' {...axis} tickFormatter={(d) => d.slice(5)} />
            <YAxis {...axis} unit='°' />
            <Tooltip {...tooltip} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#94A3B8" }} />
            <Line type='monotone' dataKey='wellhead' name='Wellhead °C' stroke='#10B981' strokeWidth={2} dot={<ProducingDot />} />
            <Line type='monotone' dataKey='ambient' name='Air °C' stroke='#0EA5E9' strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className='viz-caption'>
        Red markers: {down} reading{down === 1 ? "" : "s"} where the wellhead was less than {view.limit} °C above air (not producing).
      </p>
    </>
  );
}

function MapView({ view }) {
  const W = 440;
  const H = 250;
  const P = 34;
  const lats = view.pins.map((p) => p.lat);
  const lons = view.pins.map((p) => p.lon);
  const [minLat, maxLat, minLon, maxLon] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const x = (lon) => (maxLon === minLon ? W / 2 : P + ((lon - minLon) / (maxLon - minLon)) * (W - 2 * P));
  const y = (lat) => (maxLat === minLat ? H / 2 : H - P - ((lat - minLat) / (maxLat - minLat)) * (H - 2 * P));
  return (
    <div className='viz-map'>
      <svg viewBox={`0 0 ${W} ${H}`} role='img' aria-label='Map of wells'>
        {[0.25, 0.5, 0.75].map((f) => (
          <g key={f} stroke='rgba(148,163,184,0.12)'>
            <line x1={W * f} y1={0} x2={W * f} y2={H} />
            <line x1={0} y1={H * f} x2={W} y2={H * f} />
          </g>
        ))}
        {view.pins.map((p) => (
          <g key={`${p.id}-${p.lat}-${p.lon}`}>
            <circle cx={x(p.lon)} cy={y(p.lat)} r={16} fill='rgba(14,165,233,0.14)' />
            <circle cx={x(p.lon)} cy={y(p.lat)} r={6} fill='#0EA5E9' stroke='#e0f2fe' strokeWidth={1.5}>
              <title>{`${p.id} · ${p.lat}, ${p.lon}${p.detail ? ` · ${p.detail}` : ""}`}</title>
            </circle>
            <text
              x={x(p.lon) + (x(p.lon) > W - 70 ? -10 : 10)}
              y={y(p.lat) - 8}
              textAnchor={x(p.lon) > W - 70 ? "end" : "start"}
              fill='#e2e8f0'
              fontSize={10}>
              {p.id}
            </text>
          </g>
        ))}
        <text x={6} y={H - 6} fill='#64748b' fontSize={9}>{`${minLat.toFixed(3)}, ${minLon.toFixed(3)}`}</text>
        <text x={W - 6} y={12} fill='#64748b' fontSize={9} textAnchor='end'>{`${maxLat.toFixed(3)}, ${maxLon.toFixed(3)}`}</text>
      </svg>
      <p className='viz-caption'>
        {view.pins.length} pin{view.pins.length === 1 ? "" : "s"}, placed by latitude/longitude. Hover a pin for details.
      </p>
    </div>
  );
}

function HeatmapView({ view }) {
  return (
    <div className='viz-heat' style={{ gridTemplateColumns: `140px repeat(${view.cols.length}, minmax(26px, 1fr)) 48px` }}>
      <span />
      {view.cols.map((c) => (
        <span key={c} className='viz-heat-col'>
          {c}
        </span>
      ))}
      <span className='viz-heat-col'>Total</span>
      {view.rows.map((row, r) => (
        <div key={row} className='viz-heat-row'>
          <span className='viz-heat-label'>{row}</span>
          {view.cells[r].map((v, c) => (
            <span
              key={c}
              className='viz-heat-cell'
              title={`${row} · ${view.cols[c]}: ${v}`}
              style={{ backgroundColor: `rgba(14,165,233,${v === 0 ? 0.05 : 0.2 + (0.75 * v) / (view.max || 1)})` }}>
              {v}
            </span>
          ))}
          <strong className='viz-heat-total'>{view.totals[r]}</strong>
        </div>
      ))}
    </div>
  );
}

const WIDE = new Set(["card", "table", "heatmap"]); // these use the full width; charts and maps sit two per row

// One answer can carry several visuals; each gets a header (title + caption) and a CSV button.
export function VisualGrid({ items }) {
  return (
    <div className='viz-grid'>
      {items.map((item, i) => (
        <section key={item.id ?? i} className={`viz-block ${WIDE.has(item.view.type) || items.length === 1 ? "wide" : ""}`}>
          <header>
            <div>
              {item.title && <strong>{item.title}</strong>}
              {item.caption && <small>{item.caption}</small>}
            </div>
            <button type='button' onClick={() => downloadCsv((item.title ?? item.view.type).replace(/\W+/g, "-").toLowerCase(), viewToRows(item.view))}>
              <Download size={13} /> CSV
            </button>
          </header>
          <Visual view={item.view} />
        </section>
      ))}
    </div>
  );
}

export default function Visual({ view }) {
  if (!view) return null;
  switch (view.type) {
    case "card":
      return view.kind === "well" ? <WellCard view={view} /> : <GenericCard view={view} />;
    case "bar":
      return <BarView view={view} />;
    case "line":
      return <LineView view={view} />;
    case "map":
      return <MapView view={view} />;
    case "heatmap":
      return <HeatmapView view={view} />;
    default:
      return <DataTable view={view} />;
  }
}
