// SubTrack web interface. Plain JavaScript; every number comes from the HTTP API
// (the same services the desktop app uses), so nothing is calculated twice.

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  subs: [],
  spent: new Map(),
  settings: null,
  enums: { Currency: [], BillingCycle: [], Category: [] },
  sort: { key: "name", dir: 1 },
  editing: null,
};

// ---- API ----------------------------------------------------------------------------

const KEY_STORAGE = "subtrack-api-key";

function storedKey() {
  try { return localStorage.getItem(KEY_STORAGE) || ""; } catch { return ""; }
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const key = storedKey();
  if (key) headers["X-API-Key"] = key;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    await askForKey(Boolean(key));
    return api(path, options);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail
        : (body.detail || []).map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join("; ") || detail;
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response;
}

function askForKey(wasWrong) {
  return new Promise((resolve) => {
    const dialog = $("#key-dialog");
    $("#key-error").hidden = !wasWrong;
    $("#key-form").onsubmit = () => {
      try { localStorage.setItem(KEY_STORAGE, $("#key-form").key.value.trim()); } catch { /* private mode */ }
      $("#forget-key").hidden = false;
      resolve();
    };
    if (!dialog.open) dialog.showModal();
  });
}

// ---- formatting ----------------------------------------------------------------------

const label = (value) => value ? value[0].toUpperCase() + value.slice(1) : "";
const money = (value, currency) => `${Number(value).toFixed(2)} ${currency}`;
const today = () => new Date().toISOString().slice(0, 10);

function niceDate(iso, withWeekday = false) {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { ...(withWeekday && { weekday: "short" }), day: "2-digit", month: "short", year: "numeric" });
}

const PALETTE = ["#e53935", "#d81b60", "#8e24aa", "#5e35b1", "#3949ab", "#1e88e5", "#039be5", "#00897b",
                 "#43a047", "#7cb342", "#f4511e", "#6d4c41", "#546e7a", "#c0ca33", "#fb8c00", "#00acc1"];

function badge(name) {
  let hash = 0;
  for (const ch of name.trim().toLowerCase()) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  const words = name.replace(/\+/g, " ").split(/\s+/).filter((w) => /^[\p{L}\p{N}]/u.test(w));
  const initials = !words.length ? "?" : words.length === 1 ? words[0][0].toUpperCase()
    : (words[0][0] + words[1][0]).toUpperCase();
  const span = document.createElement("span");
  span.className = "badge";
  span.style.background = PALETTE[hash % PALETTE.length];
  span.textContent = initials;
  span.setAttribute("aria-hidden", "true");
  return span;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function toast(message, isError = false) {
  const node = el("div", { class: `toast${isError ? " error" : ""}`, role: isError ? "alert" : "status" }, message);
  $("#toasts").append(node);
  setTimeout(() => node.remove(), 3600);
}

async function run(action, success) {
  try {
    const result = await action();
    if (success) toast(success);
    await refresh();
    return result;
  } catch (error) {
    toast(error.message, true);
  }
}

// ---- loading -------------------------------------------------------------------------

async function loadEnums() {
  const spec = await api("/openapi.json");
  for (const name of Object.keys(state.enums)) state.enums[name] = spec.components.schemas[name].enum;
}

async function refresh() {
  const [subs, spent, summary, settings] = await Promise.all([
    api("/subscriptions?include_cancelled=true"),
    api("/stats/spent"),
    api("/stats/summary"),
    api("/settings"),
  ]);
  state.subs = subs;
  state.spent = new Map(spent.map((s) => [s.subscription_id, s.spent]));
  state.settings = settings;
  $("#totals").replaceChildren(
    "Monthly ", el("b", {}, money(summary.monthly_total, summary.base_currency)),
    "  ·  Yearly ", el("b", {}, money(summary.yearly_total, summary.base_currency)),
  );
  renderFilters();
  renderSubscriptions();
  await renderPage(currentPage());
}

// ---- pages ---------------------------------------------------------------------------

const PAGES = ["subscriptions", "dashboard", "reminders", "settings"];
const currentPage = () => (PAGES.includes(location.hash.slice(1)) ? location.hash.slice(1) : "subscriptions");

async function showPage(page) {
  for (const p of PAGES) $(`#page-${p}`).hidden = p !== page;
  for (const tab of $$(".tabs button")) tab.setAttribute("aria-selected", String(tab.dataset.page === page));
  await renderPage(page);
}

async function renderPage(page) {
  try {
    if (page === "dashboard") await renderDashboard();
    if (page === "reminders") await renderReminders();
    if (page === "settings") renderSettings();
    await updateDueCount();
  } catch (error) {
    toast(error.message, true);
  }
}

async function updateDueCount() {
  const due = await api("/reminders/due");
  $("#due-count").textContent = due.length;
  $("#due-count").hidden = due.length === 0;
}

// ---- subscriptions -------------------------------------------------------------------

function renderFilters() {
  const category = $("#filter-category");
  if (category.options.length === 1) {
    for (const c of state.enums.Category) category.append(el("option", { value: c }, label(c)));
  }
  const method = $("#filter-method");
  const chosen = method.value;
  const methods = [...new Set(state.subs.map((s) => s.payment_method).filter(Boolean))].sort();
  method.replaceChildren(el("option", { value: "" }, "All payment methods"),
    ...methods.map((m) => el("option", { value: m }, m)));
  method.value = methods.includes(chosen) ? chosen : "";
  method.hidden = methods.length === 0;
  $("#methods").replaceChildren(...methods.map((m) => el("option", { value: m })));
}

const toBase = (amount, currency) => {
  if (!state.settings) return Number(amount);
  const rate = (c) => (c === "RON" ? 1 : Number(state.settings.rates_in_ron[c] || 1));
  return Number(amount) * rate(currency) / rate(state.settings.base_currency);
};

const SORT_KEYS = {
  name: (s) => s.name.toLowerCase(),
  category: (s) => s.category,
  price: (s) => toBase(s.price, s.currency),
  cycle: (s) => ["weekly", "monthly", "quarterly", "yearly"].indexOf(s.billing_cycle),
  monthly: (s) => toBase(s.monthly_cost, s.currency),
  next: (s) => (s.active ? s.next_payment : "9999"),
  spent: (s) => Number(state.spent.get(s.id) ?? -1),
};

function visibleSubs() {
  const words = $("#search").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const category = $("#filter-category").value;
  const method = $("#filter-method").value;
  const showCancelled = $("#show-cancelled").checked;
  const { key, dir } = state.sort;
  return state.subs
    .filter((s) => showCancelled || s.active)
    .filter((s) => !category || s.category === category)
    .filter((s) => !method || s.payment_method === method)
    .filter((s) => {
      const haystack = `${s.name} ${s.category} ${s.notes} ${s.payment_method}`.toLowerCase();
      return words.every((w) => haystack.includes(w));
    })
    .sort((a, b) => {
      const x = SORT_KEYS[key](a), y = SORT_KEYS[key](b);
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
}

function tagsFor(s) {
  const tags = [];
  if (s.in_trial) tags.push(["trial"]);
  if (s.shared_with > 1) tags.push([`split ${s.shared_with} ways`]);
  if (s.paused) tags.push([s.paused_from === s.paused_until ? `skipping ${niceDate(s.paused_from)}` : `paused until ${niceDate(s.paused_until)}`]);
  if (s.cancel_by) tags.push([`cancel by ${niceDate(s.cancel_by)}`, "warn"]);
  if (s.rarely_used) tags.push(["rarely used"]);
  if (!s.active) tags.push(["cancelled"]);
  return el("span", { class: "tags" }, tags.map(([t, kind]) => el("span", { class: `tag${kind ? " " + kind : ""}` }, t)));
}

function priceCell(s) {
  if (s.promo_active) {
    return [money(s.promo_price, s.currency), " ", el("span", { class: "tag" }, `intro until ${niceDate(s.promo_until)}`)];
  }
  const change = s.price_change_percent === null ? 0 : Number(s.price_change_percent);
  return [money(s.price, s.currency), change ? el("span", { class: change > 0 ? "up" : "down" }, ` ${change > 0 ? "▲" : "▼"}${Math.abs(change)}%`) : null];
}

function renderSubscriptions() {
  const rows = visibleSubs();
  const base = state.settings?.base_currency || "";
  const tbody = $("#subs-table tbody");
  tbody.replaceChildren(...rows.map((s) => el("tr", { class: s.active ? "" : "cancelled" },
    el("td", {}, el("div", { class: "name-cell" }, badge(s.name),
      el("div", {}, el("div", {}, s.name), tagsFor(s)))),
    el("td", { "data-label": "Category" }, label(s.category)),
    el("td", { class: "num", "data-label": "Price", title: s.price_history.length ? `Was ${money(s.price_history[0].old_price, s.price_history[0].old_currency)} until ${niceDate(s.price_history[0].changed_on)}` : null }, priceCell(s)),
    el("td", { "data-label": "Cycle" }, label(s.billing_cycle)),
    el("td", { class: "num", "data-label": "Per month", title: s.shared_with > 1 ? `Your share of ${money(s.price, s.currency)}` : null }, money(s.monthly_cost, s.currency)),
    el("td", { "data-label": "Next payment" }, s.active ? niceDate(s.next_payment) : "—"),
    el("td", { class: "num", "data-label": "Spent so far" }, state.spent.has(s.id) ? money(state.spent.get(s.id), base) : "—"),
    el("td", {}, el("div", { class: "actions" },
      el("button", { onclick: () => openEditor(s), title: "Edit" }, "Edit"),
      s.active && el("button", {
        onclick: () => run(() => api(`/subscriptions/${s.id}/${s.paused ? "resume" : "skip-next"}`, { method: "POST" }),
          s.paused ? `${s.name} resumed` : `Skipping ${s.name}'s next payment`),
      }, s.paused ? "Resume" : "Skip next"),
      el("button", {
        onclick: () => run(() => api(`/subscriptions/${s.id}/${s.active ? "cancel" : "reactivate"}`, { method: "POST" }),
          s.active ? `${s.name} marked cancelled` : `${s.name} reactivated`),
      }, s.active ? "Cancel" : "Reactivate"),
      el("button", {
        class: "danger", title: "Delete",
        onclick: () => confirm(`Delete "${s.name}"? This cannot be undone.`)
          && run(() => api(`/subscriptions/${s.id}`, { method: "DELETE" }), `${s.name} deleted`),
      }, "✕"),
    )),
  )));
  $("#subs-empty").hidden = state.subs.length > 0;

  const filtering = $("#search").value.trim() || $("#filter-category").value || $("#filter-method").value;
  const active = rows.filter((s) => s.active);
  const total = active.reduce((sum, s) => sum + toBase(s.monthly_cost, s.currency), 0);
  $("#filter-summary").textContent = filtering
    ? `Showing ${active.length} of ${state.subs.filter((s) => s.active).length} · ${total.toFixed(2)} ${base}/month` : "";

  for (const th of $$("#subs-table th[data-sort]")) {
    th.setAttribute("aria-sort", th.dataset.sort === state.sort.key ? (state.sort.dir > 0 ? "ascending" : "descending") : "none");
  }
}

// ---- add / edit ----------------------------------------------------------------------

const GROUPS = {
  trial: ["trial_end_date"],
  contract: ["contract_end_date", "notice_days"],
  pause: ["paused_from", "paused_until"],
  promo: ["promo_price", "promo_until"],
};
let templates = [];

function fillSelect(select, values) {
  if (select.options.length) return;
  for (const v of values) select.append(el("option", { value: v }, v.length <= 3 ? v : label(v)));
}

function setGroup(form, group, on) {
  $(`[data-toggle="${group}"]`, form).checked = on;
  for (const field of GROUPS[group]) form.elements[field].disabled = !on;
}

function openEditor(sub = null) {
  const form = $("#edit-form");
  state.editing = sub;
  form.reset();
  fillSelect(form.currency, state.enums.Currency);
  fillSelect(form.billing_cycle, state.enums.BillingCycle);
  fillSelect(form.category, state.enums.Category);
  $("#edit-title").textContent = sub ? `Edit ${sub.name}` : "Add subscription";
  $("#edit-error").hidden = true;

  const values = sub || { currency: state.settings?.base_currency || "RON", billing_cycle: "monthly", category: "other",
                          first_payment_date: today(), shared_with: 1, notice_days: 0 };
  for (const [name, value] of Object.entries(values)) {
    const field = form.elements[name];
    if (!field || value === null || value === undefined) continue;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value;
  }
  setGroup(form, "trial", Boolean(sub?.trial_end_date));
  setGroup(form, "contract", Boolean(sub?.contract_end_date));
  setGroup(form, "pause", Boolean(sub?.paused_from));
  setGroup(form, "promo", sub?.promo_price !== null && sub?.promo_price !== undefined);
  for (const name of ["trial_end_date", "contract_end_date", "paused_from", "paused_until", "promo_until"]) {
    if (!form.elements[name].value) form.elements[name].value = today();
  }
  $("#more-options").open = Boolean(sub && (sub.payment_method || sub.contract_end_date || sub.paused_from || sub.promo_price !== null));

  const history = $("#price-history");
  history.hidden = !sub?.price_history?.length;
  if (sub?.price_history?.length) {
    history.textContent = "Price changes: " + sub.price_history.slice().reverse().map((c) =>
      `${niceDate(c.changed_on)}: ${Number(c.old_price).toFixed(2)} → ${money(c.new_price, c.new_currency)}`).join(" · ");
  }
  updateShare();
  $("#edit-dialog").showModal();
  form.elements.name.focus();
}

function updateShare() {
  const form = $("#edit-form");
  const people = Number(form.shared_with.value) || 1;
  const price = Number(form.price.value) || 0;
  $("#share-preview").textContent = people > 1 ? `your share: ${(price / people).toFixed(2)} ${form.currency.value} per payment` : "";
}

function applyTemplate() {
  const form = $("#edit-form");
  if (state.editing) return;
  const match = templates.find((t) => t.name.toLowerCase() === form.elements.name.value.trim().toLowerCase());
  if (!match) return;
  form.elements.name.value = match.name;
  form.category.value = match.category;
  form.billing_cycle.value = match.billing_cycle;
}

function formBody() {
  const form = $("#edit-form");
  const v = (name) => form.elements[name].value;
  const on = (group) => $(`[data-toggle="${group}"]`, form).checked;
  return {
    name: v("name"), price: v("price"), currency: v("currency"), billing_cycle: v("billing_cycle"),
    category: v("category"), first_payment_date: v("first_payment_date"),
    trial_end_date: on("trial") ? v("trial_end_date") : null,
    rarely_used: form.rarely_used.checked, notes: v("notes"),
    active: state.editing ? state.editing.active : true,
    shared_with: Number(v("shared_with")) || 1, payment_method: v("payment_method"),
    contract_end_date: on("contract") ? v("contract_end_date") : null,
    notice_days: on("contract") ? Number(v("notice_days")) || 0 : 0,
    paused_from: on("pause") ? v("paused_from") : null,
    paused_until: on("pause") ? v("paused_until") : null,
    promo_price: on("promo") ? v("promo_price") || "0" : null,
    promo_until: on("promo") ? v("promo_until") : null,
  };
}

async function saveEditor(event) {
  event.preventDefault();
  const sub = state.editing;
  try {
    await api(sub ? `/subscriptions/${sub.id}` : "/subscriptions", { method: sub ? "PUT" : "POST", json: formBody() });
    $("#edit-dialog").close();
    toast(sub ? "Saved" : "Added");
    await refresh();
  } catch (error) {
    $("#edit-error").textContent = error.message;
    $("#edit-error").hidden = false;
  }
}

// ---- dashboard -----------------------------------------------------------------------

async function renderDashboard() {
  const [summary, months, categories, upcoming] = await Promise.all([
    api("/stats/summary"), api("/stats/monthly"), api("/stats/by-category"), api("/stats/upcoming?days=30"),
  ]);
  const base = summary.base_currency;
  $("#stat-monthly").textContent = money(summary.monthly_total, base);
  $("#stat-yearly").textContent = money(summary.yearly_total, base);
  $("#stat-upcoming").textContent = money(upcoming.reduce((s, p) => s + Number(p.amount), 0), base);

  const top = Math.max(1, ...months.map((m) => Number(m.amount)));
  $("#chart-months").replaceChildren(...months.map((m, i) => {
    const d = new Date(m.month + "T00:00:00");
    const tick = d.toLocaleDateString(undefined, { month: "short" }) + (d.getMonth() === 0 || i === 0 ? ` ${String(d.getFullYear()).slice(2)}` : "");
    return el("div", { class: `bar${m.is_forecast ? " forecast" : ""}`, title: `${d.toLocaleDateString(undefined, { month: "long", year: "numeric" })}: ${money(m.amount, base)}${m.is_forecast ? " (forecast)" : ""}` },
      el("div", { class: "fill", style: `height:${(Number(m.amount) / top) * 100}%` }),
      i % 2 === 0 ? el("span", { class: "tick" }, tick) : null);
  }));

  const biggest = Math.max(1, ...categories.map((c) => Number(c.monthly)));
  $("#chart-categories").replaceChildren(...(categories.length ? categories.map((c) => el("div", { class: "hbar" },
    el("span", {}, label(c.category)),
    el("div", { class: "track" }, el("span", { style: `width:${(Number(c.monthly) / biggest) * 100}%` })),
    el("span", { class: "num" }, money(c.monthly, base)))) : [el("p", { class: "muted" }, "Nothing yet.")]));

  $("#upcoming").replaceChildren(...(upcoming.length ? upcoming.map((p) => el("tr", {},
    el("td", {}, niceDate(p.due_date, true)),
    el("td", {}, el("div", { class: "name-cell" }, badge(p.name), p.name)),
    el("td", { class: "num" }, money(p.amount, base)))) : [el("tr", {}, el("td", { class: "muted" }, "No payments in the next 30 days."))]));
}

// ---- reminders -----------------------------------------------------------------------

async function renderReminders() {
  const [due, timeline] = await Promise.all([api("/reminders/due"), api("/reminders/timeline")]);
  $("#due-card").hidden = due.length === 0;
  $("#due-list").replaceChildren(...due.map((r) => el("li", {},
    badge(r.name),
    el("div", { class: "text" }, el("div", { class: "title" }, r.title), el("div", { class: "muted" }, r.message)),
    ["payment", "payment_due", "payment_missed"].includes(r.kind) && el("button", {
      class: "primary", onclick: () => run(() => api(`/payments/${r.subscription_id}/${r.due_date}`, { method: "PUT" }), "Marked as paid"),
    }, "Mark as paid"),
    el("button", { onclick: () => snooze(r, "1h") }, "In 1 hour"),
    el("button", { onclick: () => snooze(r, "tomorrow") }, "Tomorrow"),
  )));

  const now = today();
  $("#timeline").replaceChildren(...timeline.map((e) => el("tr", { class: e.date < now ? "past" : e.date === now ? "today" : "" },
    el("td", {}, niceDate(e.date, true)),
    el("td", {}, el("div", { class: "name-cell" }, badge(e.name), e.name)),
    el("td", {}, e.event),
    el("td", { class: `status-${e.status.toLowerCase().replace(/[^a-z]+/g, "-").replace(/-$/, "")}` }, e.status + (e.detail ? ` ${e.detail}` : "")),
    el("td", { class: "num" },
      e.can_mark_paid && el("button", { onclick: () => run(() => api(`/payments/${e.subscription_id}/${e.date}`, { method: "PUT" }), "Marked as paid") }, "Mark paid"),
      e.status === "Paid" && el("button", { onclick: () => run(() => api(`/payments/${e.subscription_id}/${e.date}`, { method: "DELETE" }), "Undone") }, "Undo")),
  )));
}

function snooze(reminder, option) {
  return run(() => api("/reminders/snooze", { method: "POST", json: {
    subscription_id: reminder.subscription_id, kind: reminder.kind, due_date: reminder.due_date, option,
  } }), option === "1h" ? "Reminding you in an hour" : "Reminding you tomorrow at 09:00");
}

// ---- settings ------------------------------------------------------------------------

function renderSettings() {
  const form = $("#settings-form");
  const s = state.settings;
  fillSelect(form.base_currency, state.enums.Currency);
  form.base_currency.value = s.base_currency;
  form.rate_EUR.value = s.rates_in_ron.EUR;
  form.rate_USD.value = s.rates_in_ron.USD;
  form.reminder_days_before.value = s.reminder_days_before;
  $("#rates-note").textContent = s.rates_updated_on
    ? `Rates last updated online on ${niceDate(s.rates_updated_on)} (in the desktop app).` : "Rates typed in by hand.";
  $("#server-info").textContent = location.host;
  $("#forget-key").hidden = !storedKey();
}

async function saveSettings(event) {
  event.preventDefault();
  const form = $("#settings-form");
  await run(() => api("/settings", { method: "PATCH", json: {
    base_currency: form.base_currency.value,
    rates_in_ron: { EUR: form.rate_EUR.value, USD: form.rate_USD.value },
    reminder_days_before: Number(form.reminder_days_before.value),
  } }), "Settings saved");
}

async function exportFile(format) {
  try {
    const response = await api(`/export/${format}`);
    const blob = await response.blob();
    const name = (response.headers.get("content-disposition") || "").match(/filename="?([^"]+)"?/)?.[1] || `subtrack.${format}`;
    const link = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  } catch (error) {
    toast(error.message, true);
  }
}

async function importFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  const result = await run(() => api("/import", { method: "POST", body }));
  if (result) toast(`Imported ${result.imported}${result.skipped_duplicates ? `, skipped ${result.skipped_duplicates} you already have` : ""}`);
  event.target.value = "";
}

// ---- wiring --------------------------------------------------------------------------

function wire() {
  for (const tab of $$(".tabs button")) tab.addEventListener("click", () => { location.hash = tab.dataset.page; });
  window.addEventListener("hashchange", () => showPage(currentPage()));

  for (const id of ["#search", "#filter-category", "#filter-method", "#show-cancelled"]) {
    $(id).addEventListener("input", renderSubscriptions);
  }
  for (const th of $$("#subs-table th[data-sort]")) {
    th.addEventListener("click", () => {
      state.sort = { key: th.dataset.sort, dir: state.sort.key === th.dataset.sort ? -state.sort.dir : 1 };
      renderSubscriptions();
    });
  }
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f" && currentPage() === "subscriptions") {
      e.preventDefault();
      $("#search").focus();
    }
  });

  const form = $("#edit-form");
  $("#add-button").addEventListener("click", () => openEditor());
  $("#edit-cancel").addEventListener("click", () => $("#edit-dialog").close());
  form.addEventListener("submit", saveEditor);
  form.elements.name.addEventListener("change", applyTemplate);
  for (const name of ["price", "shared_with", "currency"]) form.elements[name].addEventListener("input", updateShare);
  for (const toggle of $$("[data-toggle]", form)) {
    toggle.addEventListener("change", () => setGroup(form, toggle.dataset.toggle, toggle.checked));
  }

  $("#settings-form").addEventListener("submit", saveSettings);
  for (const button of $$("[data-export]")) button.addEventListener("click", () => exportFile(button.dataset.export));
  $("#import-file").addEventListener("change", importFile);
  $("#forget-key").addEventListener("click", () => {
    try { localStorage.removeItem(KEY_STORAGE); } catch { /* ignore */ }
    toast("API key forgotten on this device");
    $("#forget-key").hidden = true;
  });
}

async function start() {
  wire();
  try {
    await loadEnums();
    templates = await api("/templates");
    $("#templates").replaceChildren(...templates.map((t) => el("option", { value: t.name })));
    await refresh();
    await showPage(currentPage());
  } catch (error) {
    toast(`Could not load SubTrack: ${error.message}`, true);
  }
}

start();
