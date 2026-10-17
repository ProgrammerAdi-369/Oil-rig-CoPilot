const flat = (v) => (v !== null && typeof v === "object" ? JSON.stringify(v) : (v ?? ""));
const quote = (v) => `"${String(flat(v)).replaceAll('"', '""')}"`;

// the rows behind a visual, whatever its type, for the CSV button
export function viewToRows(view) {
  switch (view?.type) {
    case "table":
      return view.rows;
    case "bar":
      return view.items.map((i) => ({ label: i.label, [view.unit]: i.value }));
    case "line":
      return view.points;
    case "map":
      return view.pins;
    case "heatmap":
      return view.rows.flatMap((row, r) => view.cols.map((col, c) => ({ row, column: col, value: view.cells[r][c] })));
    case "card":
      return view.kind === "well"
        ? [...view.metrics.map((m) => ({ label: m.label, value: m.value })), ...view.facts.map((f) => ({ label: f.label, value: f.value }))]
        : view.items;
    default:
      return [];
  }
}

export function downloadCsv(name, rows) {
  if (!rows?.length) return;
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const text = [cols.map(quote).join(","), ...rows.map((r) => cols.map((c) => quote(r[c])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `${name}.csv` });
  a.click();
  URL.revokeObjectURL(url);
}
