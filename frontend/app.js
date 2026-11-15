// AP Invoice Automation dashboard - plain JavaScript, talks to the FastAPI backend.

const $ = (id) => document.getElementById(id);
const PAGE = 25;
const state = { dataset: null, offset: 0, total: 0 };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => "$" + Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v) => (Number(v) * 100).toFixed(1) + "%";

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

function stateBadge(s) {
  const cls = s === "PAYMENT_READY" ? "ok" : s === "DUPLICATE_BLOCKED" ? "bad" : "warn";
  return `<span class="pill ${cls}">${esc(s.replace(/_/g, " ").toLowerCase())}</span>`;
}

function showBanner(msg) {
  $("banner").textContent = msg;
  $("banner").classList.toggle("hidden", !msg);
}

// ---------------------------------------------------------------- summary
async function loadSummary() {
  const s = await api(`/api/summary?dataset=${state.dataset}`);
  const m = s.metrics, k = m.kpis, v = s.validation;
  const cards = [
    ["Invoices processed", k.invoices_processed.toLocaleString()],
    ["Straight-through rate", pct(k.straight_through_rate)],
    ["Payment-ready value", money(k.payment_ready_value)],
    ["Duplicates prevented", money(k.duplicate_payments_prevented_value)],
    ["Over-billing stopped", money(k.overbilling_prevented_value)],
    ["Blocked but payment-ready", m.safety.blocked_invoices_marked_payment_ready + " · " + m.safety.gate, "ok"],
    ["Data validation", `${v.checks_total - v.checks_failed}/${v.checks_total} checks`],
    ["Reproducible (same seed)", s.reproducibility?.identical ? "Yes" : "Not checked"],
  ];
  $("kpis").innerHTML = cards.map(([l, val, cls]) =>
    `<div class="card"><div class="label">${esc(l)}</div><div class="value ${cls || ""}">${esc(val)}</div></div>`).join("");

  $("acceptance").innerHTML = "<thead><tr><th>Criterion</th><th class='num'>Pass rate</th></tr></thead><tbody>" +
    Object.entries(m.acceptance).map(([c, r]) => `<tr><td>${esc(c.replace(/_/g, " "))}</td><td class="num">${pct(r)}</td></tr>`).join("") +
    "</tbody>";

  $("detection").innerHTML = "<thead><tr><th>Exception</th><th class='num'>Support</th><th class='num'>TP</th><th class='num'>FP</th>" +
    "<th class='num'>FN</th><th class='num'>Precision</th><th class='num'>Recall</th><th class='num'>F1</th></tr></thead><tbody>" +
    Object.entries(m.exception_detection).map(([c, d]) =>
      `<tr><td>${esc(c)}</td><td class="num">${d.support}</td><td class="num">${d.tp}</td><td class="num">${d.fp}</td>` +
      `<td class="num">${d.fn}</td><td class="num">${pct(d.precision)}</td><td class="num">${pct(d.recall)}</td><td class="num">${pct(d.f1)}</td></tr>`).join("") +
    "</tbody>";
}

async function loadQueues() {
  const rows = await api(`/api/queues?dataset=${state.dataset}`);
  const byQueue = {};
  rows.forEach((r) => {
    const q = byQueue[r.queue] || (byQueue[r.queue] = { n: 0, value: 0, codes: [] });
    q.n += r.n; q.value += r.value_at_risk || 0; q.codes.push(`${r.code} (${r.n})`);
  });
  const entries = Object.entries(byQueue).sort((a, b) => b[1].n - a[1].n);
  const max = Math.max(1, ...entries.map(([, q]) => q.n));
  $("queues").innerHTML = "<thead><tr><th>Queue</th><th class='num'>Exceptions</th><th></th><th class='num'>Value at risk</th></tr></thead><tbody>" +
    entries.map(([name, q]) =>
      `<tr title="${esc(q.codes.join(", "))}"><td>${esc(name)}</td><td class="num">${q.n}</td>` +
      `<td><span class="bar" style="width:${Math.max(4, (q.n / max) * 160)}px"></span></td><td class="num">${money(q.value)}</td></tr>`).join("") +
    "</tbody>";
  const sel = $("queueFilter"), current = sel.value;
  sel.innerHTML = `<option value="">All queues</option>` + entries.map(([n]) => `<option>${esc(n)}</option>`).join("");
  sel.value = current;
}

// ---------------------------------------------------------------- analysis panels
async function loadAnalysis() {
  const q = `?dataset=${state.dataset}`;
  const [w, r, i] = await Promise.all(["whatif", "robustness", "impact"].map((n) =>
    api(`/api/${n}${q}`).catch(() => null)));
  $("whatifPanel").classList.toggle("hidden", !w);
  $("robustPanel").classList.toggle("hidden", !r);
  $("impactPanel").classList.toggle("hidden", !i);
  if (w) {
    const maxPaid = Math.max(1, ...w.rows.map((x) => Number(x.overcharge_paid_usd)));
    $("whatif").innerHTML = "<thead><tr><th>Price tolerance</th><th class='num'>Touchless</th><th class='num'>Need a person</th>" +
      "<th class='num'>Good invoices blocked</th><th class='num'>Variances missed</th><th>Overcharge paid</th></tr></thead><tbody>" +
      w.rows.map((x) => `<tr${x.current_policy ? ' style="font-weight:650"' : ""}><td>${x.tolerance_pct.toFixed(0)}%${x.current_policy ? " (current)" : ""}</td>` +
        `<td class="num">${pct(x.touchless_rate)}</td><td class="num">${x.needs_human}</td><td class="num">${x.good_invoices_blocked}</td>` +
        `<td class="num">${x.price_variances_missed}</td><td><span class="bar" style="width:${Math.max(2, Number(x.overcharge_paid_usd) / maxPaid * 120)}px"></span> ${money(x.overcharge_paid_usd)}</td></tr>`).join("") +
      "</tbody>";
  }
  if (r) {
    $("robustLead").textContent = `${r.documents_damaged} documents damaged on purpose; ${r.unsafe_payments} unsafe payments.`;
    $("robust").innerHTML = "<thead><tr><th>Damage</th><th class='num'>Docs</th><th class='num'>Handled OK</th><th class='num'>Blocked</th><th class='num'>Unsafe</th></tr></thead><tbody>" +
      Object.values(r.by_damage_type).map((x) => { const o = x.outcomes;
        return `<tr><td>${esc(x.description)}</td><td class="num">${x.documents_damaged}</td><td class="num">${o.HANDLED_OK}</td>` +
          `<td class="num">${o.SAFE_FAILURE + o.STILL_BLOCKED}</td><td class="num"><b>${o.UNSAFE_PAYMENT}</b></td></tr>`; }).join("") + "</tbody>";
  }
  if (i) {
    $("impact").innerHTML = "<thead><tr><th>Item</th><th class='num'>Value</th><th>Basis</th></tr></thead><tbody>" +
      i.rows.map((x) => `<tr><td>${esc(x.item)}</td><td class="num">${esc(x.value)}</td><td class="muted small">${esc(x.basis)}</td></tr>`).join("") + "</tbody>";
  }
}

// ---------------------------------------------------------------- invoices
async function loadInvoices() {
  const p = new URLSearchParams({ dataset: state.dataset, limit: PAGE, offset: state.offset });
  if ($("search").value.trim()) p.set("search", $("search").value.trim());
  if ($("stateFilter").value) p.set("state", $("stateFilter").value);
  if ($("queueFilter").value) p.set("queue", $("queueFilter").value);
  const data = await api(`/api/invoices?${p}`);
  state.total = data.total;
  $("invoices").innerHTML = "<thead><tr><th>Invoice</th><th>Vendor</th><th>PO</th><th class='num'>Total</th>" +
    "<th>State</th><th>Exceptions</th><th>Queue</th></tr></thead><tbody>" +
    (data.items.length ? data.items.map((d) =>
      `<tr data-id="${esc(d.invoice_id)}"><td>${esc(d.invoice_id)}</td><td>${esc(d.vendor_name || d.vendor_id)}</td>` +
      `<td>${esc(d.po_id || "non-PO")}</td><td class="num">${money(d.stated_total)}</td><td>${stateBadge(d.final_state)}</td>` +
      `<td>${(d.exceptions || "").split("|").filter(Boolean).map((c) => `<span class="chip">${esc(c)}</span>`).join("") || "—"}</td>` +
      `<td>${esc(d.route_queue || "—")}</td></tr>`).join("")
      : `<tr><td colspan="7" class="muted">No invoices match these filters.</td></tr>`) + "</tbody>";
  const end = Math.min(state.offset + PAGE, state.total);
  $("pageInfo").textContent = state.total ? `${state.offset + 1}–${end} of ${state.total.toLocaleString()}` : "0 results";
  $("prev").disabled = state.offset === 0;
  $("next").disabled = end >= state.total;
}

// ---------------------------------------------------------------- detail
async function openInvoice(id) {
  const x = await api(`/api/invoices/${encodeURIComponent(id)}?dataset=${state.dataset}`);
  const d = x.decision;
  $("drawerTitle").textContent = d.invoice_id;
  const kv = [
    ["State", stateBadge(d.final_state)], ["Match status", esc(d.match_status)],
    ["Vendor", `${esc(d.vendor_name)} (${esc(d.vendor_id)}, ${esc(d.vendor_status)})`],
    ["PO", esc(d.po_id || "non-PO")], ["Vendor invoice no.", esc(d.vendor_invoice_number)],
    ["Invoice / received", `${esc(d.invoice_date)} / ${esc(d.received_date)}`],
    ["Stated / computed total", `${money(d.stated_total)} / ${money(d.computed_total)}`],
    ["Route queue", esc(d.route_queue || "—")], ["Duplicate of", esc(d.duplicate_of || "—")],
    ["Approval", d.approval_roles ? `Tier ${esc(d.approval_tier)}: ${esc(d.approval_roles.replace(/\|/g, " → "))}` : "—"],
    ["Payment", d.payment_ready === "true" ? `Scheduled ${esc(d.scheduled_payment_date)} via ${esc(d.payment_method)}` : "Not payable"],
  ];
  $("drawerBody").innerHTML = `
    <div class="why"><b>Why:</b> ${esc(d.explanation)}</div>
    <h3>Decision</h3><div class="kv">${kv.map(([a, b]) => `<div>${esc(a)}</div><div>${b}</div>`).join("")}</div>
    ${x.exceptions.length ? `<h3>Exceptions</h3><table><thead><tr><th>Code</th><th>Line</th><th>Expected</th><th>Actual</th><th class="num">At risk</th></tr></thead><tbody>
      ${x.exceptions.map((e) => `<tr><td>${esc(e.code)}</td><td>${esc(e.line_ref || "header")}</td><td>${esc(e.expected)}</td><td>${esc(e.actual)}</td><td class="num">${money(e.value_at_risk)}</td></tr>`).join("")}
      </tbody></table>` : ""}
    <h3>Extracted lines</h3><table><thead><tr><th>#</th><th>SKU</th><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th>Tax</th><th class="num">Amount</th></tr></thead><tbody>
      ${x.lines.map((l) => `<tr><td>${esc(l.line_number)}</td><td>${esc(l.sku)}</td><td>${esc(l.description)}</td><td class="num">${esc(l.quantity)}</td><td class="num">${money(l.unit_price)}</td><td>${esc(l.tax_code)}</td><td class="num">${money(l.line_amount)}</td></tr>`).join("")}
      </tbody></table>
    ${x.allocations.length ? `<h3>Matched goods receipts</h3><table><thead><tr><th>Invoice line</th><th>PO line</th><th>Receipt line</th><th class="num">Qty</th></tr></thead><tbody>
      ${x.allocations.map((a) => `<tr><td>${esc(a.invoice_line_number)}</td><td>${esc(a.po_line_id)}</td><td>${esc(a.grn_line_id)}</td><td class="num">${esc(a.quantity)}</td></tr>`).join("")}
      </tbody></table>` : ""}
    <h3>Audit trail</h3><ul class="timeline">
      ${x.events.map((e) => `<li><b>${esc(e.to_state)}</b> <span class="muted small">${esc(e.event_time)} · ${esc(e.actor)}</span><br><span class="small">${esc(e.reason)}</span></li>`).join("")}
    </ul>
    ${x.document ? `<h3>Original document (${esc(x.document.channel)})</h3><pre class="doc">${esc(x.document.content)}</pre>` : ""}`;
  $("drawer").classList.remove("hidden");
  $("scrim").classList.remove("hidden");
}

function closeDrawer() {
  $("drawer").classList.add("hidden");
  $("scrim").classList.add("hidden");
}

// ---------------------------------------------------------------- wiring
async function refreshAll() {
  try {
    showBanner("");
    await Promise.all([loadSummary(), loadQueues(), loadAnalysis()]);
    await loadInvoices();
  } catch (err) {
    showBanner(err.message);
  }
}

async function init() {
  const sets = await api("/api/datasets").catch(() => []);
  const sel = $("dataset");
  sel.innerHTML = sets.map((s) => `<option value="${esc(s.name)}">${esc(s.name)} (${s.invoices ?? "?"} invoices)</option>`).join("");
  if (!sets.length) {
    showBanner("No pipeline output yet. Click “Run pipeline” to generate data and process invoices.");
    return;
  }
  state.dataset = (sets.find((s) => s.name === "full") || sets[0]).name;
  sel.value = state.dataset;
  await refreshAll();
}

let searchTimer;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.offset = 0; loadInvoices().catch((e) => showBanner(e.message)); }, 250);
});
["stateFilter", "queueFilter"].forEach((id) => $(id).addEventListener("change", () => {
  state.offset = 0; loadInvoices().catch((e) => showBanner(e.message));
}));
$("dataset").addEventListener("change", (e) => { state.dataset = e.target.value; state.offset = 0; refreshAll(); });
$("prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE); loadInvoices(); });
$("next").addEventListener("click", () => { state.offset += PAGE; loadInvoices(); });
$("invoices").addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-id]");
  if (row) openInvoice(row.dataset.id).catch((err) => showBanner(err.message));
});
$("closeDrawer").addEventListener("click", closeDrawer);
$("scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
$("runBtn").addEventListener("click", async () => {
  const btn = $("runBtn");
  const name = state.dataset || "starter";
  const scale = name === "full" ? 1.0 : 0.1;
  btn.disabled = true; btn.textContent = "Running…";
  try {
    await api("/api/pipeline/run", { method: "POST", headers: { "Content-Type": "application/json" },
                                     body: JSON.stringify({ name, scale }) });
    await init();
  } catch (err) {
    showBanner("Run failed: " + err.message);
  } finally {
    btn.disabled = false; btn.textContent = "Run pipeline";
  }
});

init();
