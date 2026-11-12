"use strict";
// Postings are untrusted, so everything is built as DOM nodes with text content, never as HTML strings.

const $ = (id) => document.getElementById(id);
let state = null;
// When this browser kept the state on screen, while that's the copy from last time rather than the server's latest.
let keptAt = null;
let openJobId = null;
// The address before a job's panel took it over, as #job-56, which closing the panel puts back.
let hashBeforeJob = "";
let refreshWatch = null;
// Whatever had focus before the job panel opened, so closing it puts you back where you were.
let drawerOpener = null;
// The longest text each box takes, as server.py refuses longer: a note with an update, your notes and the next step.
const LIMITS = { note: 2000, notes: 5000, nextStep: 300 };
// The demo starts no runs, so every button that would start one is disabled up front and says why, rather than
// being pressed and then refused.
const DEMO_NO_RUNS = "Not in the demo, which starts no runs.";
const inDemo = () => Boolean(state && state.demo);
const demoTitle = () => (inDemo() ? DEMO_NO_RUNS : null);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "onclick") el.addEventListener("click", value);
    else if (key === "style") el.setAttribute("style", value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

const fill = (el, ...children) => { el.replaceChildren(...children.flat().filter(Boolean)); return el; };

const safeHref = (url) => (/^https?:\/\//i.test(url || "") ? url : null);

// A bare date means that calendar day. new Date() would read it as midnight UTC, which is the day before anywhere west of Greenwich.
const toDate = (iso) => new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso);

function ago(iso) {
  if (!iso) return "";
  const hours = (Date.now() - toDate(iso).getTime()) / 3.6e6;
  if (hours < 1 / 60) return "just now";
  if (hours < 1) return `${Math.floor(hours * 60)}m ago`;
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

const shortDate = (iso) => (iso ? toDate(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: toDate(iso).getFullYear() === new Date().getFullYear() ? undefined : "numeric" }) : "");

function daysAgo(days) {
  if (days === null || days === undefined) return "";
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return days < 60 ? `${days}d ago` : `${Math.round(days / 30)}mo ago`;
}

const pill = (tone, label, why) => h("span", { class: `pill ${tone}`, title: why }, label);

// Each status's icon from the fire assay, as the funnel names them. Every one is drawn at 24 and 48 px by art/icons/build.py.
const STAGE_ICONS = {
  new: "pan", shortlisted: "anvil", needs_fix: "anvil", ready: "streak", applied: "furnace", responded: "crucible",
  interviewing: "balance", offer: "cupel", rejected: "tarnished", ghosted: "tarnished", withdrawn: "tarnished", passed: "tarnished", closed: "tarnished",
};
// Decoration only: the words beside it always say the same, so it has no alt text.
const stageIcon = (name, size = 24, extra = "") => (name
  ? h("img", { class: `stage-icon${extra ? ` ${extra}` : ""}`, src: `/static/icons/${name}-${size}.png`, alt: "", width: size, height: size }) : null);
// A view with nothing in it: the icon of what would be here, and a line saying why it's empty.
const emptyState = (icon, text, tag = "div", attrs = {}) => h(tag, { ...attrs, class: "empty-state" }, stageIcon(icon, 48), h("span", {}, text));
const capitalized = (text) => text.charAt(0).toUpperCase() + text.slice(1);

// Long text cut to fit a card or a table cell, at the end of a word. The job panel always shows all of it.
function clip(text, limit) {
  if (!text || text.length <= limit) return text || "";
  return `${text.slice(0, limit).replace(/\s+\S*$/, "").replace(/[,;:]$/, "")}…`;
}

// Text with `backticked` words, such as a command to run, shown with those words as code. The rest stays plain text.
function withCode(text) {
  return String(text || "").split(/(`[^`\n]+`)/).filter(Boolean)
    .map((part) => (/^`[^`]+`$/.test(part) ? h("code", {}, part.slice(1, -1)) : part));
}

// Markdown as Claude writes it in notes.md: headings, lists, tables, quotes and paragraphs, with bold, italic, code and
// links inside them. It's built from elements and text, never parsed as HTML, so nothing in the file can add markup or
// script, and a link goes only to an http or https address.
const MD_INLINE = /(`[^`\n]+`)|\*\*(.+?)\*\*|__(.+?)__|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])|\[([^\]\n]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()]*[^\s<>().,;:!?'"*_])/g;

function mdInline(text) {
  const nodes = [];
  let at = 0;
  for (const m of String(text).matchAll(MD_INLINE)) {
    if (m.index > at) nodes.push(text.slice(at, m.index));
    const [whole, code, bold, bold2, em, em2, label, href, bare] = m;
    if (code) nodes.push(h("code", {}, code.slice(1, -1)));
    else if (bold || bold2) nodes.push(h("strong", {}, mdInline(bold || bold2)));
    else if (em || em2) nodes.push(h("em", {}, mdInline(em || em2)));
    else if (label) nodes.push(safeHref(href) ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, mdInline(label)) : whole);
    else if (bare) nodes.push(h("a", { href: bare, target: "_blank", rel: "noopener noreferrer" }, bare));
    at = m.index + whole.length;
  }
  if (at < text.length) nodes.push(text.slice(at));
  return nodes;
}

const mdCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
const MD_LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const MD_TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function markdown(text) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  const startsBlock = (n) => !lines[n].trim() || /^(#{1,6}\s|>|```)/.test(lines[n]) || MD_LIST.test(lines[n])
    || /^\s*([-*_])(\s*\1){2,}\s*$/.test(lines[n]) || (lines[n].includes("|") && MD_TABLE_RULE.test(lines[n + 1] || ""));
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const heading = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (heading) {
      // The panel already has an h3 over the notes, so the file's levels start one below it.
      blocks.push(h(`h${Math.min(6, heading[1].length + 3)}`, {}, mdInline(heading[2])));
      i += 1;
    } else if (/^```/.test(line)) {
      const code = [];
      for (i += 1; i < lines.length && !/^```/.test(lines[i]); i += 1) code.push(lines[i]);
      blocks.push(h("pre", {}, h("code", {}, code.join("\n"))));
      i += 1;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push(h("hr"));
      i += 1;
    } else if (line.includes("|") && MD_TABLE_RULE.test(lines[i + 1] || "")) {
      const head = mdCells(line);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim(); i += 1) rows.push(mdCells(lines[i]));
      blocks.push(h("div", { class: "md-table" }, h("table", {},
        h("thead", {}, h("tr", {}, head.map((cell) => h("th", {}, mdInline(cell))))),
        h("tbody", {}, rows.map((row) => h("tr", {}, head.map((_, n) => h("td", {}, mdInline(row[n] || "")))))))));
    } else if (/^>/.test(line)) {
      const quote = [];
      for (; i < lines.length && /^>/.test(lines[i]); i += 1) quote.push(lines[i].replace(/^>\s?/, ""));
      blocks.push(h("blockquote", {}, markdown(quote.join("\n"))));
    } else if (MD_LIST.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items = [];
      for (; i < lines.length; i += 1) {
        const item = lines[i].match(MD_LIST);
        if (item) items.push(item[3]);
        // A line indented under an item carries on that item.
        else if (lines[i].trim() && /^\s+/.test(lines[i]) && items.length) items[items.length - 1] += ` ${lines[i].trim()}`;
        else break;
      }
      blocks.push(h(ordered ? "ol" : "ul", {}, items.map((item) => h("li", {}, mdInline(item)))));
    } else {
      const para = [line.trim()];
      for (i += 1; i < lines.length && !startsBlock(i); i += 1) para.push(lines[i].trim());
      blocks.push(h("p", {}, mdInline(para.join(" "))));
    }
  }
  return blocks;
}

// A company or title as a table cell shows it: three lines at most, however long a board made it. The panel has all of it.
const clamped = (text) => h("span", { class: "clamp" }, text);

// Pay as a table can show it: "$255,850.00-361,200.00 USD" reads as $256k–$361k, and "$45 - $60 an hour" as $45–$60/hr.
// Anything it can't read is shown as the posting wrote it.
function shortPay(comp) {
  const text = (comp || "").trim();
  const amount = String.raw`((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s?([kKmM](?![a-z]))?`;
  const found = text.match(new RegExp(String.raw`(?<![A-Za-z])([A-Z]{1,2})?([$€£])\s?${amount}(?:\s*(?:-|–|—|to)\s*(?:[A-Z]{1,2})?[$€£]?\s?${amount})?`));
  if (!found) return text;
  const [, country, symbol, low, lowScale, high, highScale] = found;
  // US$ is the plain dollar. CA$ and A$ stay as they are.
  const prefix = country && country !== "US" ? country : "";
  const scale = { k: 1e3, m: 1e6 };
  const value = (digits, unit, other) => Number(digits.replace(/,/g, "")) * (scale[(unit || other || "").toLowerCase()] || 1);
  // "$150-200k" means thousands at both ends.
  const values = [value(low, lowScale, highScale), ...(high ? [value(high, highScale, lowScale)] : [])];
  const per = /\b(hour|hourly|hr)\b|\/\s*h(?:ou)?r\b/i.test(text) ? "/hr"
    : /\b(week|weekly|wk)\b/i.test(text) ? "/wk" : /\b(month|monthly|mo)\b/i.test(text) ? "/mo" : "";
  const code = (text.match(/\b(USD|CAD|AUD|NZD|EUR|GBP|CHF|SGD|INR|JPY)\b/) || [])[1];
  const brief = (n, unit) => `${n < 10 ? n.toFixed(1).replace(/\.0$/, "") : Math.round(n)}${unit}`;
  const money = (n) => `${prefix}${symbol}${n >= 1e6 ? brief(n / 1e6, "M") : n >= 1e3 ? brief(n / 1e3, "k")
    : Number.isInteger(n) ? n : n.toFixed(2)}`;
  const shown = [...new Set(values.map(money))].join("–");
  // A dollar amount in another country's dollars says which. A euro or pound sign already does.
  return `${shown}${per}${symbol === "$" && !prefix && code && code !== "USD" ? ` ${code}` : ""}`;
}

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  let data;
  try {
    data = await res.json();
  } catch (err) {
    throw new Error(`The server gave no usable answer (${res.status}).`);
  }
  if (!res.ok) {
    // 428 means the change needs a code: data says what for. The caller decides what to do with it.
    const err = new Error(data.error || (res.status === 428 ? "This change needs a code." : `Request failed (${res.status})`));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// A change that loosens the fact check needs a code Pyrite sends to this computer's notifications. `send` sends the
// change again with a request id and code (both null to ask for a fresh code), and `cancelled` puts the form back.
let codePrompts = 0;
function codePrompt(first, send, cancelled) {
  let current = first;
  const digits = (value) => value.replace(/\D/g, "");
  const list = h("ul", { class: "code-changes" });
  const note = h("p", {});
  const fallback = h("p", { class: "muted" });
  const id = `code-input-${++codePrompts}`;
  const input = h("input", { id, class: "code-input", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "7",
    placeholder: "000 000" });
  const error = h("p", { class: "error", role: "alert" });
  const ok = h("button", { class: "btn primary", type: "button", disabled: true }, "Confirm");
  // Windows labels the notification with the app that shows it, Windows PowerShell, so say so, and where it goes.
  const where = /Windows/.test(navigator.userAgent)
    ? " It pops up in the corner of the screen, from Windows PowerShell. If it's gone, Windows key + N shows it again."
    : "";
  const show = (fresh) => {
    current = fresh;
    fill(list, current.changes.map((change) => h("li", {}, `It will ${change}.`)));
    note.textContent = current.sent
      ? `Pyrite just sent a 6-digit code to this computer's notifications.${where} Type it in the box below and choose Confirm. It works once, for this change only, for 2 minutes.`
      : "The notification didn't go through. Run `pyrite code` in a terminal on this computer to see the code, then type it in the box below and choose Confirm. It works once, for this change only, for 2 minutes.";
    fallback.textContent = current.sent ? "No notification? Run `pyrite code` in a terminal on this computer to see the code." : "";
    fallback.hidden = !current.sent;
    input.value = "";
    ok.disabled = true;
  };
  const restart = async () => {
    try {
      await send(null, null);
    } catch (err) {
      if (err.status !== 428) throw err;
      show(err.data);
    }
  };
  input.addEventListener("input", () => { ok.disabled = digits(input.value).length !== 6; });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !ok.disabled) ok.click();
    if (e.key === "Escape") cancel.click();
  });
  ok.addEventListener("click", async () => {
    error.textContent = "";
    ok.disabled = true;
    try {
      await send(current.request_id, digits(input.value));
    } catch (err) {
      if (err.status === 428) show(err.data);
      error.textContent = err.message;
      ok.disabled = digits(input.value).length !== 6;
      input.focus();
    }
  });
  const resend = h("button", { class: "btn", type: "button", onclick: async () => {
    error.textContent = "";
    try {
      show(await api("/api/profile/code", { action: "resend", request_id: current.request_id }));
    } catch (err) {
      // That code had ended, so make the change again for a new one.
      try {
        await restart();
      } catch (again) {
        error.textContent = again.message;
      }
    }
    input.focus();
  } }, "Send a new code");
  const cancel = h("button", { class: "btn", type: "button", onclick: async () => {
    try {
      await api("/api/profile/code", { action: "cancel", request_id: current.request_id });
    } catch (err) {
      // Nothing was waiting. Either way, nothing was changed.
    }
    cancelled();
  } }, "Cancel");
  show(first);
  setTimeout(() => input.focus(), 0);
  return h("div", { class: "code-prompt", role: "group", "aria-label": "Confirm with a code" },
    h("p", { class: "code-title" }, "This change lets drafts say more, so it needs a code"), list, note,
    h("label", { class: "code-label", for: id }, "Code from the notification"),
    h("div", { class: "part-actions" }, input, ok, resend, cancel), fallback, error);
}

// ---- Top of page ----

// Mail is checked with the boards and listed with them on the Sources tab, but a failing inbox is named apart.
const isMail = (source) => /^inbox:/.test(source.source_key || "");
// How many failing sources the status popover names before it says how many more.
const FAILING_NAMED = 3;
// A source as the popover names it: the company, the kind of board, and what went wrong, cut short.
const sourceLabel = (source) => {
  const kind = (source.source_key || "").split(":")[0];
  return `${source.company || source.source_key}${kind ? ` (${capitalized(kind)})` : ""}: ${clip(source.last_error, 120)}`;
};
const openSourcesLink = () => h("button", { class: "linkish", type: "button",
  onclick: () => { toggleStatus(false); showTab("sources"); } }, "Open Sources");

function renderSweep() {
  const run = state.last_run;
  const failed = state.sources.filter((s) => s.last_error && !isMail(s));
  const mailFailed = state.sources.some((s) => s.last_error && isMail(s));
  const parts = [];
  if (run) {
    const reposted = run.stats.reposted ? `, ${run.stats.reposted} reposted` : "";
    parts.push(`Boards checked ${ago(run.finished_at)}: ${run.stats.postings.toLocaleString()} postings read across ${run.stats.sources} sources, ${run.stats.new} new${reposted}.`);
    // A sweep after an update that changed scoring rescores prospects first. What it dropped is named, as nothing else of it is left.
    const r = run.stats.rescored;
    if (r) parts.push(`Scoring changed, so ${plural(r.kept, "prospect")} got new scores${r.dropped ? ` and ${r.dropped} that no longer pass ${r.dropped === 1 ? "was" : "were"} dropped: ${r.removed.join("; ")}` : ""}.`);
  } else {
    parts.push("The boards haven't been checked yet.");
  }
  const nodes = [parts.join(" ")];
  if (run && Date.now() - toDate(run.finished_at).getTime() > 30 * 3.6e6) nodes.push(" ", h("span", { class: "alert" }, "This is out of date, so check the Pyrite Sweep task."));
  if (failed.length) {
    // Named here, so a failing board doesn't take a trip to the Sources tab to find. The tab has them all.
    const named = failed.slice(0, FAILING_NAMED).map(sourceLabel);
    const more = failed.length > FAILING_NAMED ? `, and ${failed.length - FAILING_NAMED} more` : "";
    nodes.push(" ", h("span", { class: "alert" }, `${plural(failed.length, "source")} failing: ${named.join("; ")}${more}.`), " ", openSourcesLink());
  }
  if (mailFailed) {
    nodes.push(" ", h("span", { class: "alert" }, "Mail couldn't be checked: see the Sources tab."));
    if (!failed.length) nodes.push(" ", openSourcesLink());
  }
  fill($("sweep"), nodes);
}

// A board check you started reports the same numbers as the line above once it's done, so it isn't said twice.
const sweepShownAbove = (task) => Boolean(task.state === "done" && state.last_run && state.last_run.finished_at
  && toDate(state.last_run.finished_at).getTime() >= toDate(task.started_at).getTime());

// The key numbers, on one line beside To do. Each one's detail is in its tooltip.
function renderKpis() {
  const s = state.stats;
  const stat = (value, label, sub, hot) => h("span", { class: `stat${hot ? " hot" : ""}`, title: sub }, h("b", {}, value), label);
  fill($("kpis"),
    stat(s.ready, "ready to send", ["Passed the fact check, with the posting still up",
      s.ready_recheck ? `${s.ready_recheck} to check again, as ${s.ready_recheck === 1 ? "its" : "their"} files changed since` : "",
      s.ready_closed ? `${s.ready_closed} more whose posting came down` : ""].filter(Boolean).join(". ") + ".", s.ready > 0),
    stat(s.applied, "applied", `${s.applied_week} in the last 7 days`),
    stat(s.awaiting, "awaiting reply", s.follow_ups ? `${s.follow_ups} follow-up${s.follow_ups > 1 ? "s" : ""} due` : "No follow-ups due", s.follow_ups > 0),
    // Replies only: a rejection is counted beside it, not inside it, so the rate isn't flattering.
    stat(s.reply_rate === null || s.reply_rate === undefined ? "–" : `${s.reply_rate}%`, "reply rate",
      s.applied ? [`${s.replied} of ${s.applied} replied`, s.rejected ? `${s.rejected} rejected` : "", s.ghosted ? `${s.ghosted} ghosted` : "",
        s.median_days_to_reply !== null ? `median ${s.median_days_to_reply}d` : ""].filter(Boolean).join(", ") : "Nothing sent yet"),
    stat(s.interviews, s.interviews === 1 ? "interview" : "interviews", "Reached interview stage"));
}

// The report names jobs as they stood when it was written. Once you've applied or passed since, fold it away and say so.
function renderBriefing() {
  const b = state.briefing;
  if (!b) return fill($("briefing"));
  const since = b.since || {};
  const moved = [since.applied ? `applied to ${plural(since.applied, "job")}` : "", since.passed ? `passed on ${since.passed}` : ""].filter(Boolean);
  if (!moved.length) return fill($("briefing"), h("span", { class: "when" }, `Field report, ${ago(b.ts)}`), b.body);
  return fill($("briefing"), h("details", { class: "stale-report" },
    h("summary", {}, `Field report from ${ago(b.ts)} is out of date: since then you ${moved.join(" and ")}. The list below is current.`),
    h("p", {}, b.body)));
}

// Checking again rebuilds the documents, which can take a minute each, so it runs one at a time and says how far it's got.
let recheckProgress = "";

async function recheckAll(ids) {
  for (const [index, id] of ids.entries()) {
    recheckProgress = ids.length > 1 ? `Checking ${index + 1} of ${ids.length}…` : "Checking…";
    renderOrders();
    try {
      await api(`/api/job/${id}/action`, { action: "recheck" });
    } catch (err) {
      runError = `Couldn't check a draft again: ${err.message}`;
      break;
    }
  }
  recheckProgress = "";
  await refresh();
}

// A draft flagged after you answered a gap it lists: keep it as it is.
async function gapSeen(id, button) {
  button.disabled = true;
  try {
    await api(`/api/job/${id}/action`, { action: "gap_seen" });
    await refresh();
  } catch (err) {
    button.disabled = false;
    toast(err.message);
  }
}

// A group you fold or open stays that way in this browser. Storage can be switched off, so a failed read or write is
// ignored and each group starts as it would.
const INBOX_STORE = "pyrite.inbox-folds";
// A group longer than this starts folded, so a busy morning shows each kind of thing once.
const INBOX_OPEN_UP_TO = 3;

function inboxFolds() {
  try {
    return JSON.parse(localStorage.getItem(INBOX_STORE) || "{}") || {};
  } catch (err) {
    return {};
  }
}

function foldGroup(kind, folded) {
  const folds = inboxFolds();
  folds[kind] = folded;
  try { localStorage.setItem(INBOX_STORE, JSON.stringify(folds)); } catch (err) { /* Then it isn't remembered. */ }
  renderOrders();
  // The list is drawn again, so the heading you pressed takes focus back.
  const toggle = [...document.querySelectorAll("#orders .group-toggle")].find((el) => el.dataset.kind === kind);
  if (toggle) toggle.focus();
}

// A copy of the page an older Pyrite kept has no groups, so each item is a group of its own until the server answers.
const inboxGroups = () => state.inbox || state.orders.map((o) => ({ kind: o.kind, cause: null, action: o.action || null, orders: [o] }));

// The jobs on the list as it's laid out, each once, for J and K to walk in the job panel.
const inboxJobIds = () => [...new Set(inboxGroups().flatMap((g) => g.orders.map((o) => o.job_id)).filter(Boolean))];

// The jobs a group names, as a folded group sums them up.
function groupNames(orders) {
  const names = [...new Set(orders.map((o) => o.text.split(": ")[0]))];
  if (names.length > 3) return `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;
  return names.length < 3 ? names.join(" and ") : `${names[0]}, ${names[1]} and ${names[2]}`;
}

function renderOrders() {
  renderBriefing();
  const kindClass = (kind) => `kind kind-${kind.toLowerCase().replace(/\s+/g, "-")}`;
  const groups = inboxGroups();
  const sluiceIds = inboxJobIds();
  const folds = inboxFolds();
  const checkButton = (ids, label) => h("button", { class: "btn dismiss", type: "button", disabled: Boolean(recheckProgress),
    title: "Rebuilds the documents and runs the assay again. Takes up to a minute each.", onclick: () => recheckAll(ids) }, recheckProgress || label);
  // In a group of several, the kind and what they share are said once over them, so each line keeps only its own words.
  const item = (o, grouped) => {
    const why = grouped && o.own !== undefined ? o.own : o.detail;
    return h("li", {},
      // A job opens its drawer, and a setup item opens the Profile section or tab that fixes it. One with nowhere to
      // go is fixed in a file, so it's text, not a button that does nothing.
      h(o.job_id || o.tab ? "button" : "div", { class: "order", type: o.job_id || o.tab ? "button" : null,
        title: o.tab ? `Opens the ${o.tab[0].toUpperCase()}${o.tab.split("/")[0].slice(1)} tab` : null,
        onclick: () => (o.job_id ? openJob(o.job_id, sluiceIds) : o.tab ? showTab(o.tab, true) : null) },
        grouped ? null : h("span", { class: kindClass(o.kind) }, o.kind),
        // A scam warning may name no job. Its sender and subject are the mail's own words, kept as text.
        h("span", {}, h("span", { class: "what" }, o.text), why ? h("span", { class: "why" }, why) : null)),
      o.alert_id ? h("button", { class: "btn dismiss", type: "button", onclick: () => dismissAlert(o.alert_id) }, "Dismiss") : null,
      o.action === "recheck" && !state.demo ? checkButton([o.job_id], "Check again") : null,
      o.action === "gap_seen" && !state.demo ? h("button", { class: "btn dismiss", type: "button", title: "Keeps this draft as it is and takes it off the list.",
        onclick: (e) => gapSeen(o.job_id, e.currentTarget) }, "Got it") : null);
  };
  const items = groups.map((group, index) => {
    if (group.orders.length === 1) return item(group.orders[0], false);
    const folded = folds[group.kind] ?? group.orders.length > INBOX_OPEN_UP_TO;
    const id = `inbox-group-${index}`;
    const recheck = group.action === "recheck" && !state.demo ? group.orders.map((o) => o.job_id) : [];
    return h("li", { class: `order-group${folded ? " folded" : ""}` },
      h("div", { class: "group-head" },
        h("button", { class: "order group-toggle", type: "button", "aria-expanded": String(!folded), "aria-controls": id, "data-kind": group.kind,
          title: folded ? "Shows each of them" : "Folds them into this line", onclick: () => foldGroup(group.kind, !folded) },
          h("span", { class: kindClass(group.kind) }, group.kind, h("span", { class: "group-count" }, String(group.orders.length))),
          h("span", {}, h("span", { class: "what" }, folded ? groupNames(group.orders) : group.cause || `${group.orders.length} of these`),
            folded && group.cause ? h("span", { class: "why" }, group.cause) : null),
          h("span", { class: "group-chevron", "aria-hidden": "true" })),
        recheck.length ? checkButton(recheck, `Check all ${recheck.length} again`) : null),
      h("ol", { class: "group-items", id, hidden: folded }, group.orders.map((o) => item(o, true))));
  });
  fill($("orders"), items.length ? items : emptyState("mark", "Nothing needs you right now.", "li"));
}

// The rail's counts, and each pipeline stage under Pipeline with how many jobs are at it now, each counted once. A
// stage opens the board at its column.
function renderRail() {
  const count = (id, value, tone = "", why = null) => {
    const el = $(id);
    el.textContent = value ? value.toLocaleString() : "";
    el.className = `rail-count${tone ? ` ${tone}` : ""}`;
    el.title = why || "";
  };
  count("count-todo", state.orders.length, "hot", "Things that need you");
  count("count-radar", state.stats.to_triage, "", `${state.stats.fresh} new, ${plural(state.stats.possible_ghosts, "possible ghost")}`);
  const closed = (state.closed || []).reduce((sum, c) => sum + c.count, 0);
  count("count-archive", closed, "", closedLine());
  const failing = state.sources.filter((s) => s.last_error).length;
  count("count-sources", failing, failing ? "bad" : "", failing ? `${plural(failing, "source")} failing` : null);
  // While a new workspace is set up, Profile shows how many of its required sections are set.
  profileRailCount(state.guide);
  if (state.guide && state.guide.finished) profileDone = true;
  // The funnel's first stage is Prospects, which has its own place in the rail. The rest line up with the board's columns.
  const stages = state.funnel.filter((f) => f.stage !== "Prospects");
  fill($("rail-stages"), stages.map((f, index) => h("button", {
    class: `rail-stage${f.count ? "" : " none"}`, type: "button", title: `${f.stage}: ${f.count}`,
    onclick: () => { showTab("pipeline"); showColumn(index); } },
  stageIcon(f.icon), h("span", { class: "rail-label" }, f.stage), h("span", { class: "rail-count" }, f.count.toLocaleString()))));
}

function showColumn(index) {
  const column = document.querySelector(`#board .column[data-column="${index}"]`);
  if (column) column.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// The top bar's one line of status: what's running, else when the boards were last read and how many things are wrong.
// The paragraphs it sums up, and the run buttons, open from it.
function renderStatus(error = "") {
  const tasks = state ? state.tasks || {} : {};
  const busy = Object.keys(RUNS).find((kind) => tasks[kind] && tasks[kind].state === "running");
  const problems = $("status-pop").querySelectorAll(".alert").length + (error ? 1 : 0);
  const run = state && state.last_run;
  let text;
  // The kept copy's runs and problems are as they were then, so it says only what it is.
  const kept = keptAt ? `This is what was here ${ago(keptAt)}.` : "";
  if (error) text = kept ? `${error} ${kept}` : error;
  else if (kept) text = `Loading the latest. ${kept}`;
  else if (busy) text = RUNS[busy].busy;
  else text = run ? `Boards checked ${ago(run.finished_at)}` : "Boards not checked yet";
  if (!error && !kept && !busy && problems) text += ` · ${plural(problems, "problem")}`;
  $("status-text").textContent = text;
  $("status-icon").src = `/static/icons/${busy === "sweep" ? "pan" : busy ? "anvil" : problems ? "tarnished" : "pan"}-24.png`;
  $("status").classList.toggle("problem", Boolean(problems) && !busy);
  $("status").title = problems ? "Something needs a look. Click for the details." : "Click for the details and the run buttons.";
}

function toggleStatus(open = $("status-pop").hidden) {
  $("status-pop").hidden = !open;
  $("status").setAttribute("aria-expanded", String(open));
}

// Jobs that left the pipeline, so the stages above don't hide where the rest went.
function closedLine() {
  const closed = state.closed || [];
  return closed.length ? `Closed: ${closed.map((c) => `${c.count} ${c.label}`).join(", ")}.` : "Nothing closed yet.";
}

// ---- Pipeline ----

const COLUMNS = [
  { title: "Being tailored", statuses: ["shortlisted", "needs_fix"], hint: "Claude writes these on the next run, or now with the button", batch: true },
  { title: "Ready to send", statuses: ["ready"], hint: "Read, then apply on the company's site" },
  { title: "Waiting to hear", statuses: ["applied"], hint: "Applied, nothing back yet" },
  { title: "Replied", statuses: ["responded"] },
  { title: "Interviewing", statuses: ["interviewing"] },
  { title: "Offer", statuses: ["offer"] },
];

// `hints` adds the weakest signal, the Workday "-1" link, which only the Prospects table and the job panel have room for.
function freshnessPills(job, hints = true) {
  const pills = [];
  if ((job.scam_signs || []).length && !job.applied_at) pills.push(pill("bad", "Possible scam", `The posting itself: ${job.scam_signs.join("; ").toLowerCase()}. Real employers don't.`));
  if (job.is_new && !job.applied_at) pills.push(pill("good", "New", `Posted ${daysAgo(job.age_days)} and never reposted`));
  if (!job.applied_at) for (const name of job.promoted) pills.push(pill("info", name, "A city or industry you asked to rank higher. It raises priority, not the score."));
  if (job.reposts) pills.push(pill(job.reposts > 1 ? "bad" : "warn", `Reposted ${job.reposts}×`, "The same job came back under a new listing, or after being taken down"));
  if (job.redates) pills.push(pill("warn", `Re-dated ${job.redates}×`, "The board moved this listing's posted date forward"));
  if (job.ghost_risk) pills.push(pill("bad", "Possible ghost", `${capitalized(job.ghost_reason)}. A prompt to look closer, not proof.`));
  if (job.unconfirmed && !job.applied_at) pills.push(pill("warn", "Not rechecked", "The last pan didn't see this listing: its board failed, left your watch list or didn't answer. It may be down."));
  if (job.may_be_repost && hints) pills.push(pill("muted", "May be a repost", "This Workday link ends in -1 or similar, which often means the requisition has more than one posting. A hint only."));
  return [...pills, ...judgedPills(job, hints)];
}

// Pay, rarity and asks nobody could meet: Pyrite's read of what the posting is worth, before you've sent it.
// `hints` adds the quietest of them, a wide pay range, which only the Prospects table and the job panel have room for.
function judgedPills(job, hints = true) {
  if (job.applied_at) return [];
  const pills = [];
  for (const sign of job.pay_signs || []) {
    if (sign.tone !== "muted" || hints) pills.push(pill(sign.tone, sign.label, sign.detail));
  }
  if (job.rare) pills.push(pill("info", "Rare near you", `${capitalized(job.rare_reason)}. There may not be another soon.`));
  const impossible = (job.skill_asks || []).filter((ask) => ask.impossible);
  if (impossible.length) {
    pills.push(pill("info", "Asks the impossible", `${impossible.map((ask) => ask.said).join("\n")}\n\nNot your gap: nobody has that much. Whoever screens it is looking for the skill.`));
  }
  return pills;
}

const FIT_TONE = { strong: "good", good: "good", stretch: "warn", skip: "bad" };
// How much of a fit reason a card's tooltip and the Closed table show. The job panel shows all of it.
const CARD_REASON = 300;
const TABLE_REASON = 160;
const NOT_SENT = ["new", "shortlisted", "needs_fix", "ready"];
const dayName = (iso) => toDate(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

// When the posting stops taking applications. Only worth showing until you've sent one.
function deadlinePill(job) {
  const days = job.days_to_deadline;
  if (days === null || days === undefined || !NOT_SENT.includes(job.status)) return null;
  const on = shortDate(job.deadline);
  if (days < 0 && job.deadline_firm === false) {
    return pill(job.decide_soon ? "warn" : "muted", "May close any day", `It took applications at least until ${dayName(job.deadline)}. That's a floor, not a closing date, so it's still open, but not for long.`);
  }
  if (days < 0) return pill("muted", `Deadline ${on} passed`, "The posting's stated deadline has passed, so the next pan passes on it. Undo the pass if it's still up.");
  const label = days === 0 ? "Apply today" : days === 1 ? "Apply by tomorrow" : `Apply by ${on}`;
  // Red when it's urgent, amber while there's still time to tailor before it closes, which is when to decide.
  return pill(days <= 2 ? "bad" : job.decide_soon ? "warn" : "muted", label,
    `The posting gives ${dayName(job.deadline)} as its deadline${job.decide_soon ? ". Decide now: tailor it or pass." : ""}`);
}

// What you've already sent this employer, so a second listing of the same job or one application too many is caught before it goes out.
function historyPills(job) {
  if (job.applied_at) return [];
  const pills = [];
  const same = job.same_title_applied;
  if (same) pills.push(pill("bad", "Same title sent", `You applied for ${same.title} here on ${shortDate(same.applied_at)}. This may be another listing of it.`));
  if (job.applied_here) {
    pills.push(pill(job.applied_here >= job.company_limit ? "warn" : "muted", `${job.applied_here} sent here`,
      `Applications already sent to ${job.company}. Your limit is ${job.company_limit} at a time.`));
  }
  return pills;
}

// A thing to settle before applying, as its short label. The job's panel has the whole reason.
const blockerLabel = (job, blocker) => (job.blocker_labels || {})[blocker] || blocker;
const blockerPill = (job) => ((job.blockers || []).length
  ? pill("bad", "Check first", `From the notes, before you apply:\n- ${job.blockers.map((b) => blockerLabel(job, b)).join("\n- ")}`) : null);

const urgentPills = (job) => [deadlinePill(job), blockerPill(job), ...historyPills(job)].filter(Boolean);

// A card shows what you'd act on. Once a job is sent, its score, fit and listing history no longer matter, so only the exceptions stay.
function cardMeta(job) {
  const sent = !NOT_SENT.includes(job.status);
  const meta = [...urgentPills(job)];
  if (job.possible_reply) meta.push(pill("warn", "Possible reply"));
  if (job.scam_alert) meta.push(pill("bad", "Possible scam", `Mail naming this company looked like a scam: ${job.scam_alert.reasons.join("; ")}`));
  if (job.priority && !sent) meta.push(pill("info", "Your pick", "You asked for this one next"));
  if (job.score && !sent) meta.push(h("span", { class: "score", title: "Filter score, out of 100" }, `Score ${job.score}`));
  if (job.fit && !sent) meta.push(pill(FIT_TONE[job.fit] || "muted", job.fit === "skip" ? "Skip" : `${capitalized(job.fit)} fit`, clip(job.fit_reason, CARD_REASON)));
  if (job.refresh && job.refresh.state === "running") meta.push(pill("info", "Refreshing resume"));
  if (job.prep && job.prep.state === "running") meta.push(pill("info", "Writing interview prep"));
  if (job.status === "needs_fix") meta.push(pill("bad", "Failed assay"));
  if (job.changed_since_check && job.changed_since_check.length) meta.push(pill("bad", "Changed since checked", "Its files changed after the assay passed it"));
  if (job.changed_after_sending && job.changed_after_sending.length) meta.push(pill("bad", "Changed after sending", `${job.changed_after_sending.join(", ")} no longer match the sent copy`));
  if (job.posting_closed_at) meta.push(pill("bad", "Posting down"));
  if (job.follow_up_due) meta.push(pill("warn", job.next_action === "Follow up" ? "Follow up" : "Next step due", job.next_action));
  if (job.quiet) meta.push(pill("warn", "Gone quiet"));
  if (job.reached_out && sent) meta.push(pill("info", "Reached out"));
  if (job.days_since_applied !== null && job.status === "applied") meta.push(h("span", {}, `Applied ${daysAgo(job.days_since_applied)}`));
  if (job.location_kind === "local") meta.push(h("span", {}, "Local"));
  if (job.location_kind === "remote") meta.push(h("span", {}, "Remote"));
  (job.flags || []).forEach((flag) => meta.push(pill("warn", flag)));
  return [...meta, ...(sent ? [] : freshnessPills(job, false))];
}

// Sent jobs wait oldest first, since those are the next to need a follow-up. Everything else keeps the server's order.
const columnOrder = (col, jobs) => (col.statuses.includes("applied")
  ? [...jobs].sort((a, b) => (a.applied_at || "").localeCompare(b.applied_at || "")) : jobs);

function renderBoard() {
  fill($("board"), COLUMNS.map((col) => {
    const jobs = columnOrder(col, state.jobs.filter((j) => col.statuses.includes(j.status)));
    const task = (state.tasks || {}).tailor;
    const busy = Boolean(task && task.state === "running");
    // An empty column shrinks to its heading, so the columns with work in them get the room.
    return h("div", { class: `column${jobs.length || busy ? "" : " empty"}`, "data-column": COLUMNS.indexOf(col) },
      h("h3", {}, stageIcon(STAGE_ICONS[col.statuses[0]]), h("span", { class: "column-title" }, col.title), h("span", { class: "column-count" }, jobs.length)),
      col.hint ? h("div", { class: "column-hint" }, col.hint) : null,
      col.batch && (jobs.length || busy) ? h("div", { class: "row" }, h("button", {
        id: "run-tailor", class: "btn primary", type: "button", disabled: busy || state.demo || Boolean(notReady("tailor")),
        title: state.demo ? DEMO_NO_RUNS
          : notReady("tailor") || "Have Claude write every draft in this column now, stretch jobs included. Uses your Claude plan.",
        onclick: () => startRun("tailor") }, busy ? RUNS.tailor.busy : RUNS.tailor.idle)) : null,
      h("div", { class: "cards" }, jobs.map((job) => h("button", { class: "card", type: "button", onclick: () => openJob(job.id, jobs.map((j) => j.id)) },
        h("span", { class: "co clamp" }, job.company), h("span", { class: "ti clamp" }, job.title), h("span", { class: "meta" }, cardMeta(job))))));
  }));
}

// ---- Radar ----

const byDeadline = (job) => (job.days_to_deadline === null || job.days_to_deadline === undefined || job.days_to_deadline < 0 ? Infinity : job.days_to_deadline);
const RADAR_SORTS = {
  priority: (a, b) => b.rank - a.rank,
  deadline: (a, b) => byDeadline(a) - byDeadline(b) || b.rank - a.rank,
  newest: (a, b) => (a.age_days ?? Infinity) - (b.age_days ?? Infinity) || b.rank - a.rank,
  score: (a, b) => b.score - a.score || b.rank - a.rank,
};
const RADAR_SHOWS = {
  "": () => true,
  unseen: (j) => !j.seen,
  new: (j) => j.is_new,
  promoted: (j) => j.promoted.length,
  clean: (j) => !j.reposts && !j.redates,
  "no-ghost": (j) => !j.ghost_risk && !j.unconfirmed && !(j.scam_signs || []).length,
};

// The Prospects filters you last used, kept in this browser only. Storage can be switched off, so a failed read or write is ignored.
const RADAR_FILTERS = ["radar-track", "radar-place", "radar-show", "radar-sort"];
const RADAR_STORE = "pyrite.radar-filters";

function restoreRadarFilters() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(RADAR_STORE) || "{}") || {};
  } catch (err) {
    return;
  }
  for (const id of RADAR_FILTERS) {
    const value = saved[id];
    if (typeof value !== "string") continue;
    // The track list is built from the jobs, so it has no options until the first render, which picks this up.
    if (id === "radar-track") $(id).dataset.saved = value;
    else if ([...$(id).options].some((o) => o.value === value)) $(id).value = value;
  }
}

function saveRadarFilters() {
  try {
    localStorage.setItem(RADAR_STORE, JSON.stringify(Object.fromEntries(RADAR_FILTERS.map((id) => [id, $(id).value]))));
  } catch (err) {
    // Nothing to do: the filters just won't be remembered.
  }
}

// The filters that leave postings out, with the word the count line uses for each. Sorting hides nothing.
const RADAR_NARROWING = [["radar-search", "search"], ["radar-track", "track"], ["radar-place", "location"], ["radar-show", "listing"]];

function showAllProspects() {
  RADAR_NARROWING.forEach(([id]) => { $(id).value = ""; });
  saveRadarFilters();
  renderRadar();
}

function renderRadar() {
  const tracks = [...new Set(state.jobs.map((j) => j.track).filter(Boolean))].sort();
  const trackSel = $("radar-track");
  const picked = trackSel.value || trackSel.dataset.saved || "";
  delete trackSel.dataset.saved;
  fill(trackSel, h("option", { value: "" }, "Any track"), tracks.map((t) => h("option", { value: t }, t)));
  trackSel.value = tracks.includes(picked) ? picked : "";

  const query = $("radar-search").value.trim().toLowerCase();
  const place = $("radar-place").value;
  const prospects = state.jobs.filter((j) => j.status === "new");
  const rows = prospects.filter((j) => (!query || `${j.company} ${j.title} ${j.location || ""}`.toLowerCase().includes(query))
    && (!trackSel.value || j.track === trackSel.value)
    && (!place || j.location_kind === place)
    && RADAR_SHOWS[$("radar-show").value](j))
    .sort(RADAR_SORTS[$("radar-sort").value]);
  const shown = rows.slice(0, 300);
  const ids = shown.map((j) => j.id);
  const unseen = prospects.filter((j) => !j.seen).length;
  // A remembered filter outlives the visit that set it, so the count says when one is hiding postings, and which.
  const narrowing = RADAR_NARROWING.filter(([id]) => $(id).value.trim());
  RADAR_NARROWING.forEach(([id]) => $(id).classList.toggle("filtered", Boolean($(id).value.trim())));
  const total = rows.length < prospects.length ? `${rows.length} of ${plural(prospects.length, "posting")}` : plural(rows.length, "posting");
  const count = rows.length > shown.length ? `Showing ${shown.length} of ${total}` : total;
  const by = narrowing.length ? `, filtered by ${listed(narrowing.map(([, name]) => name))}` : "";
  fill($("radar-count"), `${count}${by}.${unseen ? ` ${unseen} not looked at yet.` : ""}`,
    narrowing.length ? [" ", h("button", { class: "btn small", type: "button", onclick: showAllProspects }, "Show all")] : null);
  // Tailor and Pass act straight from the row, so a quick no never needs the panel.
  const quick = (j, label, action, cls) => h("button", { class: cls, type: "button",
    onclick: (e) => {
      e.stopPropagation();
      const button = e.currentTarget;
      button.disabled = true;
      triage(j, action, false).finally(() => { button.disabled = false; });
    } }, label);
  fill($("radar"),
    h("thead", {}, h("tr", {},
      h("th", { class: "num", title: "Score plus points for a recent posting and for a preferred city or industry, minus a penalty for each repost" }, "Priority"),
      h("th", { class: "num", title: "Filter score, out of 100" }, "Score"),
      ["Company", "Title", "Location", "Track", "Pay", "Posted", "Signals"].map((c) => h("th", {}, c)),
      h("th", {}, h("span", { class: "visually-hidden" }, "Actions")))),
    h("tbody", {}, shown.length ? shown.map((j) => h("tr", { "data-id": j.id, class: j.seen ? "" : "unseen", onclick: () => openJob(j.id, ids) },
      h("td", { class: "num" }, j.rank),
      h("td", { class: "num muted" }, j.score),
      h("td", {}, clamped(j.company)),
      h("td", {}, h("button", { class: "linkish clamp", type: "button", title: j.seen ? null : "You haven't opened this one yet" }, j.title)),
      h("td", {}, h("span", { class: "place", title: j.location || "" }, shortPlace(j.location))),
      h("td", {}, j.track),
      payCell(j.comp),
      h("td", { class: "nowrap", title: shortDate(j.first_posted_at || j.posted_at) }, daysAgo(j.age_days) || "Unknown"),
      h("td", {}, h("span", { class: "signals" }, urgentPills(j), freshnessPills(j))),
      h("td", { class: "row-actions" }, quick(j, "Tailor", "tailor_next", "btn small"), quick(j, "Pass", "pass", "btn small"))))
      : h("tr", {}, emptyState("pan", "No prospects match.", "td", { colspan: 10 }))));
}

// Compact where it can be read, and as the posting wrote it in the tooltip either way.
function payCell(comp) {
  const pay = shortPay(comp);
  return h("td", { class: pay !== (comp || "").trim() ? "nowrap" : null, title: comp || null }, pay);
}

// A posting can list dozens of places. Show the first few and keep the rest in the tooltip.
function shortPlace(location) {
  if (!location) return "Not stated";
  const places = [...new Set(location.split(/\s*[|;]\s*/).filter(Boolean))];
  if (places.length <= 3) return places.join(" | ");
  return `${places.slice(0, 3).join(" | ")} and ${places.length - 3} more`;
}

const CLOSED_LABELS = { rejected: "Rejected", ghosted: "Ghosted", withdrawn: "Withdrew", passed: "Passed", closed: "Posting closed" };

// Why a job closed, as noted when it did. A pass with no note of its own falls back to the fit reason, which is often why.
const closingNote = (job) => job.closing_note || (job.status === "passed" ? job.fit_reason || "" : "");

function renderArchive() {
  const all = state.jobs.filter((j) => CLOSED_LABELS[j.status]);
  const outcome = $("archive-outcome").value;
  const query = $("archive-search").value.trim().toLowerCase();
  const rows = all.filter((j) => (!outcome || j.status === outcome)
    && (!query || `${j.company} ${j.title} ${closingNote(j)}`.toLowerCase().includes(query)))
    .sort((a, b) => (b.closed_out_at || b.status_changed_at || "").localeCompare(a.closed_out_at || a.status_changed_at || ""));
  const ids = rows.map((j) => j.id);
  $("archive-count").textContent = rows.length < all.length ? `${rows.length} of ${plural(all.length, "job")}.` : `${plural(all.length, "job")}.`;
  fill($("archive"),
    h("thead", {}, h("tr", {}, ["Outcome", "Company", "Title", "Applied", "Closed", "Note"].map((c) => h("th", {}, c)))),
    h("tbody", {}, rows.length ? rows.map((j) => {
      const note = closingNote(j);
      return h("tr", { "data-id": j.id, onclick: () => openJob(j.id, ids) },
        h("td", { class: "nowrap" }, CLOSED_LABELS[j.status]), h("td", {}, clamped(j.company)),
        h("td", {}, h("button", { class: "linkish clamp", type: "button" }, j.title)),
        h("td", { class: "nowrap" }, j.applied_at ? shortDate(j.applied_at) : "No"),
        h("td", { class: "nowrap" }, shortDate(j.closed_out_at || j.status_changed_at)),
        h("td", { title: note.length > TABLE_REASON ? note : null }, clip(note, TABLE_REASON)));
    })
      : h("tr", {}, emptyState("tarnished", all.length ? "None match." : "Nothing closed yet.", "td", { colspan: 6 }))));
}

function renderSources() {
  fill($("manual-list"), state.manual_check.map((m) => h("li", {},
    safeHref(m.url) ? h("a", { href: m.url, target: "_blank", rel: "noopener noreferrer" }, m.name) : m.name,
    h("span", { class: "muted" }, ` ${m.why}`))));
  const rows = [...state.sources].sort((a, b) => (b.last_error ? 1 : 0) - (a.last_error ? 1 : 0) || (a.company || "").localeCompare(b.company || ""));
  const failing = rows.filter((r) => r.last_error).length;
  $("source-summary").textContent = rows.length
    ? `${rows.length - failing} of ${rows.length} sources working. A failing source is reported here rather than quietly returning nothing.`
    : "The boards haven't been checked yet.";
  fill($("sources"),
    h("thead", {}, h("tr", {}, ["State", "Company", "Source", "Postings", "Last good read"].map((c) => h("th", {}, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {},
      h("td", {}, h("span", { class: `pill ${r.last_error ? "bad" : "good"}` }, r.last_error ? "Failing" : "Working")),
      h("td", {}, r.company),
      h("td", {}, r.last_error ? `${r.source_key}: ${r.last_error}` : r.source_key),
      h("td", { class: "num" }, r.last_count),
      h("td", {}, ago(r.last_ok) || "Never")))));
  renderUsage();
}

function renderUsage() {
  const usage = state.usage;
  // 999,600 rounds to 1000k, so the cut to millions is where the rounding would reach it.
  const tokens = (n) => (n >= 999.5e3 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));
  // A run stopped before Claude Code reported its cost isn't in the cost, so the cost is a floor.
  const cost = (t) => t.uncosted
    ? h("span", { title: `${plural(t.uncosted, "run")} stopped before Claude Code reported a cost, so this leaves ${t.uncosted === 1 ? "it" : "them"} out.` }, `$${t.cost_usd.toFixed(2)}+`)
    : `$${t.cost_usd.toFixed(2)}`;
  const row = (label, t) => h("tr", {},
    h("td", {}, label),
    h("td", { class: "num" }, t.failed ? `${t.runs} (${t.failed} failed)` : t.runs),
    h("td", { class: "num" }, `${t.minutes} min`),
    h("td", { class: "num" }, tokens(t.input_tokens)),
    h("td", { class: "num" }, tokens(t.output_tokens)),
    h("td", { class: "num" }, cost(t)));
  const counted = "Every Claude run Pyrite starts is counted: the daily run, judging postings, Refresh resume, Interview prep, checking mail, industry outlooks, employer research and skill ages. A Claude Code session of your own isn't.";
  $("usage-summary").textContent = usage.all.runs
    ? `${counted} Cost is Claude Code's own estimate at API prices, which isn't a bill if you're on a Claude plan.`
    : `No Claude runs have been started from here yet. ${counted}`;
  $("usage-wrap").hidden = !usage.all.runs;
  fill($("usage"),
    h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", { class: "num" }, "Runs"), h("th", { class: "num" }, "Time"),
      h("th", { class: "num", title: "Everything Claude read, including text it had cached" }, "Tokens in"),
      h("th", { class: "num" }, "Tokens out"), h("th", { class: "num" }, "Est. cost"))),
    h("tbody", {}, row("Last 7 days", usage.week), row("All time", usage.all),
      usage.kinds.map((kind) => row(`${kind.label}, all time`, kind))));
}

// ---- Settings ----
// Settings has a menu of its own. Its first sections say how Pyrite runs: Claude, mail, the daily run and the
// dashboard, each drawn from the list the server sends. The last holds the cities and industries to see first.
// Every section is drawn when the tab loads and only the one picked shows, so edits you haven't saved in one are
// still there after a look at another.
// Each panel saves by itself. A save sends only that panel's part, so half-finished edits in another panel are
// never written by accident.

let settings = null;
// The section on show, as the address names it. "" is the first one.
let settingsAt = "";
const SETTINGS_RANKING = { id: "ranking", label: "Cities and industries" };
const MODEL_ALIASES = ["fable", "opus", "sonnet", "haiku"];
const dirtyParts = new Set();
const settingsRedraw = [];
// Where each section shows whether its connection is working, by the name the server gives it.
const settingsStatusBoxes = {};

const settingsLines = (text) => text.split("\n").map((line) => line.trim()).filter(Boolean);
const settingsNumber = (input) => (input.value.trim() === "" ? null : Number(input.value));
const onRadar = (name) => (state ? state.jobs.filter((j) => j.status === "new" && j.promoted.includes(name)).length : 0);
const plural = (count, one, many) => `${count} ${count === 1 ? one : many || `${one}s`}`;
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// What's saved, with the defaults a brand new search.toml hasn't written yet.
function savedPromote() {
  return { city_points: 10, industry_points: 10, mentions_needed: 3, cities: [], industry: [], ...JSON.parse(JSON.stringify(settings.promote || {})) };
}

// What a city or industry with no points of its own gets: the default as typed in Points, or as saved if that's empty.
function defaultPoints(key) {
  const input = $(`default-${key}`);
  const typed = input ? settingsNumber(input) : null;
  return typed !== null && Number.isFinite(typed) ? typed : savedPromote()[key];
}

// A row's own points, or the default it falls back to.
const effectivePoints = (input, key) => settingsNumber(input) ?? defaultPoints(key);

function settingsField(label, input, hint) {
  return h("label", {}, label, input, hint ? h("span", { class: "muted hint" }, hint) : null);
}

function numberInput(value, placeholder) {
  return h("input", { type: "number", min: "0", max: "50", step: "1", value: value ?? "", placeholder });
}

// One panel that saves by itself: its Save button, its status, and whether it has unsaved edits.
// `request` returns where to send the panel's part and what to send, and throws to say why it can't be sent.
function settingsPart(root, request, afterSave) {
  const save = h("button", { class: "btn primary", type: "button", disabled: true }, "Save");
  const status = h("span", { class: "muted part-status", role: "status" });
  const error = h("p", { class: "error", role: "alert" });
  const part = { save, status, error };
  part.touch = () => {
    dirtyParts.add(part);
    save.disabled = false;
    status.textContent = "Unsaved changes";
    error.textContent = "";
  };
  part.clean = (text = "") => {
    dirtyParts.delete(part);
    save.disabled = true;
    status.textContent = text;
  };
  part.send = async (how = request) => {
    status.textContent = "Saving…";
    error.textContent = "";
    try {
      const [path, body] = how();
      settings = await api(path, body);
    } catch (err) {
      status.textContent = "Not saved";
      error.textContent = err.message;
      return false;
    }
    part.clean("Saved");
    await refresh();
    if (afterSave) afterSave();
    settingsRedraw.forEach((redraw) => redraw());
    return true;
  };
  root.addEventListener("input", part.touch);
  save.addEventListener("click", () => part.send());
  return part;
}

// A panel of the cities and industries. `change` is handed a copy of what's saved and puts this panel's part into
// it, and part.edit(change) sends some other change the same way.
function promotePart(root, change, afterSave) {
  const request = (edit) => () => {
    const promote = savedPromote();
    edit(promote);
    return ["/api/settings", { version: settings.version, promote }];
  };
  const part = settingsPart(root, request(change), afterSave);
  part.edit = (edit) => part.send(request(edit));
  return part;
}

// ---- How Pyrite runs ----

const savedOption = (id) => settings.options.sections.flatMap((section) => section.panels)
  .flatMap((panel) => panel.fields).find((field) => field.id === id);

// One setting's control, and read(), which gives its value as the server takes it: null means left to the default.
function optionControl(field) {
  const hint = field.hint ? h("span", { class: "muted hint" }, field.hint) : null;
  if (field.kind === "switch") {
    const box = h("input", { type: "checkbox", checked: field.value === true });
    return { node: h("label", { class: "check" }, box, h("span", {}, field.label, hint)), read: () => box.checked };
  }
  if (field.kind === "choice") {
    const select = h("select", {}, field.unset ? h("option", { value: "" }, field.unset) : null,
      field.choices.map(([value, label]) => h("option", { value, selected: value === field.value }, label)));
    return { node: h("label", {}, field.label, select, hint), read: () => select.value || null };
  }
  if (field.kind === "number") {
    const input = h("input", { type: "number", min: field.min, max: field.max, step: "1", value: field.value ?? "", placeholder: field.unset ? `${field.unset} (default)` : null });
    return { node: h("label", {}, field.label, input, hint), read: () => settingsNumber(input) };
  }
  const input = h("input", { type: "text", value: field.value ?? "", placeholder: field.unset, list: "model-options", spellcheck: "false", autocomplete: "off" });
  return { node: h("label", {}, field.label, input, hint), read: () => input.value.trim() || null };
}

// A panel of settings. Its save sends only the ones you changed, so one you left alone is never written to the file.
function optionsPanel(panel) {
  const root = h("div", { class: "panel" });
  const controls = panel.fields.map((field) => ({ id: field.id, ...optionControl(field) }));
  const part = settingsPart(root, () => {
    const values = {};
    for (const control of controls) {
      const value = control.read();
      if (value !== savedOption(control.id).value) values[control.id] = value;
    }
    if (!Object.keys(values).length) throw new Error("Nothing here differs from what's saved.");
    return ["/api/settings/options", { version: settings.options.version, values }];
  }, () => loadSettingsStatus());  // What was saved may be what a connection hangs on, such as where mail is read from.
  // fill, since append would write a missing hint out as the word "null".
  return fill(root, h("h2", {}, panel.title),
    panel.hint ? h("p", { class: "muted hint" }, panel.hint) : null,
    h("div", { class: "option-fields" }, controls.map((control) => control.node)),
    h("div", { class: "part-actions" }, part.save, part.status), part.error);
}

// Whether a section's connection is working: Claude Code for the Claude section, the mail reader for Mail.
function drawSettingsStatus(status, error) {
  for (const [name, box] of Object.entries(settingsStatusBoxes)) {
    const found = status ? status[name] : null;
    const again = h("button", { class: "btn small", type: "button", onclick: () => loadSettingsStatus(true) }, "Check again");
    if (!found) {
      fill(box, h("p", { class: error ? "error" : "muted" }, error || "Checking…"), error ? again : null);
      continue;
    }
    const [tone, label] = found.ok === true ? ["good", "Working"] : found.ok === false ? ["bad", "Needs you"] : ["", "Not set up"];
    fill(box,
      h("p", { class: "what" }, pill(tone, label), h("span", {}, found.what)),
      found.fix ? h("p", { class: "fix muted" }, withCode(found.fix)) : null,
      found.last_ok ? h("p", { class: "muted hint" }, `Mail was last read without trouble ${ago(found.last_ok)}.`) : null,
      again);
  }
}

async function loadSettingsStatus(fresh = false) {
  if (fresh) drawSettingsStatus(null);
  try {
    drawSettingsStatus(await api(`/api/settings/status${fresh ? "?fresh=1" : ""}`));
  } catch (err) {
    drawSettingsStatus(null, err.message);
  }
}

// ---- When the daily runs start ----
// Asked of Task Scheduler when Daily run is drawn, since asking takes a second or two. Each change is confirmed here
// first: it adds or takes away a task on this computer, though it changes no file and lets no draft say more.

function scheduleRun(run, redraw) {
  const time = h("input", { type: "time", value: run.time || run.default, "aria-label": `Time for ${run.label.toLowerCase()}` });
  const error = h("p", { class: "error", role: "alert" });
  const send = async (action, button) => {
    const at = time.value;
    const asked = action === "remove"
      ? `Remove “${run.name}” from Windows Task Scheduler? ${run.label} stops starting by itself until you set it up again.`
      : run.set ? `Move “${run.name}” in Windows Task Scheduler to ${at} every day?`
        : `Set up “${run.name}” in Windows Task Scheduler, to start every day at ${at}?`;
    if (!window.confirm(asked)) return;
    error.textContent = "";
    button.disabled = true;
    try {
      redraw(await api("/api/settings/schedule", { run: run.id, action, time: at }));
    } catch (err) {
      error.textContent = err.message;
      button.disabled = false;
    }
  };
  const setUp = h("button", { class: `btn small${run.set ? "" : " primary"}`, type: "button" }, run.set ? "Change time" : "Set up");
  setUp.addEventListener("click", () => {
    if (!/^\d\d:\d\d$/.test(time.value)) {
      error.textContent = "Pick a time of day first.";
      return;
    }
    send("set", setUp);
  });
  // Change time waits for a new time, unless the task runs another copy of Pyrite, which it would bring here.
  const sync = () => { setUp.disabled = run.set && !run.other_copy && time.value === run.time; };
  time.addEventListener("input", sync);
  sync();
  const remove = run.set ? h("button", { class: "btn small", type: "button" }, "Remove") : null;
  if (remove) remove.addEventListener("click", () => send("remove", remove));
  const state = run.set ? (run.disabled ? pill("bad", "Turned off") : pill("good", "Set up")) : pill("", "Not set up");
  const said = run.set
    ? (run.disabled ? "Turned off in Task Scheduler, so it doesn't start." : `Starts every day at ${run.time || "the time Task Scheduler has"}.`)
    : "Doesn't start by itself.";
  return h("div", { class: "schedule-run" },
    h("p", { class: "what" }, state, h("span", {}, run.label), h("span", { class: "muted" }, said)),
    h("p", { class: "muted hint" }, run.does),
    run.other_copy ? h("p", { class: "muted hint" }, "It runs another copy of Pyrite. Change time sets it up for this one.") : null,
    run.elsewhere.map((task) => h("p", { class: "fix muted" },
      `Task Scheduler also has “${task.name}”${task.time ? ` at ${task.time}` : ""}, which does the same and wasn't set up `
      + `here, so Pyrite leaves it alone. ${run.set ? "With both, it runs twice" : "If you set it up here too, it runs "
      + "twice"}: keep one, and delete the other in Task Scheduler itself.`)),
    h("div", { class: "part-actions" }, time, setUp, remove),
    error);
}

function schedulePanel() {
  const box = h("div", { class: "schedule", "aria-live": "polite" });
  const again = () => h("button", { class: "btn small", type: "button", onclick: () => load() }, "Check again");
  const draw = (found) => {
    fill(box,
      found.why_not ? h("p", { class: found.error ? "error" : "fix muted" }, found.why_not) : null,
      found.available ? found.runs.map((run) => scheduleRun(run, draw)) : null,
      found.available ? h("p", { class: "muted hint" }, "Each runs as you, while you're signed in to Windows, with no "
        + "window. A run missed while the computer was off or asleep starts once it's back. Pyrite changes only these "
        + "two tasks. On another system, docs/schedule.md says how to schedule them.") : null,
      again());
  };
  const load = async () => {
    fill(box, h("p", { class: "muted" }, "Asking Task Scheduler…"));
    try {
      draw(await api("/api/settings/schedule"));
    } catch (err) {
      fill(box, h("p", { class: "error" }, err.message), again());
    }
  };
  load();
  return h("div", { class: "panel" }, h("h2", {}, "When it runs"), box);
}

// ---- Local taxes at home, for Relocation ----
// Pyrite's table of city and county taxes to pick from, your own as a rate over a threshold, and a lookup with Claude
// that proposes yours with sources. Nothing a lookup finds is saved until you add it.

const localWords = (text) => text.toLowerCase().split(/[\s,]+/).filter(Boolean);
const matchesLocal = (tax, words) => {
  const text = [tax.key, tax.name, tax.state_name, tax.where, tax.note].join(" ").toLowerCase();
  return words.every((word) => text.includes(word) || word.toUpperCase() === tax.state);
};

function localTaxPanel() {
  const box = h("div", { class: "local-taxes", "aria-live": "polite" });
  const error = h("p", { class: "error", role: "alert" });
  let view = null;
  let watch = null;
  const search = h("input", { type: "search", placeholder: "A city, county or state", "aria-label": "Search Pyrite's local taxes" });
  const place = h("input", { type: "text", placeholder: "Town or county, ST", "aria-label": "Where you live, for the lookup", autocomplete: "off" });

  const send = async (named, own) => {
    error.textContent = "";
    try {
      view = await api("/api/settings/local-taxes", { version: view.version, home_local_taxes: named, own_local_taxes: own });
      draw();
    } catch (err) {
      error.textContent = err.message;
    }
  };
  const named = () => (view.named === null ? [...view.default] : [...view.named]);
  const own = () => view.own.map(({ said, ...entry }) => entry);
  const button = (label, onclick, extra = {}) => h("button", { class: "btn small", type: "button", disabled: !view.editable, onclick, ...extra }, label);

  const homeList = () => {
    const byKey = new Map(view.table.map((tax) => [tax.key, tax]));
    const rows = [
      ...named().map((key) => h("li", {}, h("strong", {}, byKey.get(key).name), ` · ${byKey.get(key).rate}`,
        view.named === null ? h("span", { class: "muted" }, ` · counted anywhere in ${byKey.get(key).state_name} until you choose`) : null, " ",
        button("Remove", () => send(named().filter((k) => k !== key), own())))),
      ...view.own.map((entry, at) => h("li", {}, h("strong", {}, entry.name), ` · ${entry.said} · your own `,
        button("Remove", () => send(named(), own().filter((_, i) => i !== at))))),
    ];
    return rows.length ? h("ul", { class: "local-list" }, rows)
      : h("p", { class: "muted" }, "None. Your pay at home is taxed by the federal government and your state only.");
  };

  const results = h("ul", { class: "local-list" });
  const drawResults = () => {
    const words = localWords(search.value);
    const found = words.length ? view.table.filter((tax) => matchesLocal(tax, words)) : [];
    fill(results, words.length && !found.length
      ? h("li", { class: "muted" }, "Not in Pyrite's table. Add it as your own below, or look it up with Claude.")
      : found.map((tax) => h("li", {}, h("strong", {}, tax.name), ` · ${tax.state_name} · ${tax.rate} (${tax.year})`,
        tax.where ? h("span", { class: "muted" }, ` · charged ${tax.where}`) : null, " ",
        named().includes(tax.key) ? h("span", { class: "muted" }, "Added")
          : button("Add", () => send([...named(), tax.key], own())))));
  };
  search.addEventListener("input", () => view && drawResults());

  const ownForm = () => {
    const name = h("input", { type: "text", placeholder: "Transit district tax", maxlength: "100" });
    const rate = h("input", { type: "number", min: "0", max: String(view.max_rate), step: "0.01", placeholder: "1.5" });
    const over = h("input", { type: "number", min: "0", step: "1", placeholder: "0" });
    const married = h("input", { type: "number", min: "0", step: "1", placeholder: "Same as single" });
    const base = h("select", {}, Object.entries(view.bases).map(([value, label]) => h("option", { value }, `Charged on ${label}`)));
    const number = (input) => (input.value === "" ? null : Number(input.value));
    return h("div", {},
      h("div", { class: "option-fields" },
        h("label", {}, "Name", name), h("label", {}, "Rate, percent", rate),
        h("label", {}, "Over, in dollars", over, h("span", { class: "muted hint" }, "Where it starts, for a single filer. 0 for the first dollar.")),
        h("label", {}, "Over, married", married), h("label", {}, "On", base)),
      h("div", { class: "part-actions" }, button("Add my own", () => send(named(), [...own(),
        { name: name.value, rate: number(rate), over: number(over), over_married: number(married), base: base.value }]))),
      h("p", { class: "muted hint" }, "A tax with two rates is two entries: the second is what it adds over its own threshold."));
  };

  const research = () => {
    const r = view.research || {};
    const report = r.report;
    const running = r.state === "running";
    const start = button(running ? "Looking…" : "Look up with Claude", async () => {
      error.textContent = "";
      try {
        view = await api("/api/settings/local-taxes/research", { place: place.value });
        draw();
      } catch (err) {
        error.textContent = err.message;
      }
    }, { disabled: !view.editable || running });
    const sources = report ? new Map(report.sources.map((s) => [s.n, s])) : new Map();
    const cite = (n) => {
      const source = sources.get(n);
      const href = source && safeHref(source.url);
      return href ? h("a", { class: "cite", href, target: "_blank", rel: "noopener noreferrer", title: source.title }, `[${n}]`) : null;
    };
    const ownNames = new Set(view.own.map((entry) => entry.name));
    let line = "Claude searches the web for the city, county and district taxes where you live, and every one it proposes cites its source. It uses your Claude plan for a few minutes.";
    if (running) line = `Looking up ${r.place}, started ${ago(r.started_at)}. You can leave this page meanwhile.`;
    else if (r.state === "failed") line = h("span", { class: "alert" }, `The last lookup didn't finish: ${r.detail}`);
    else if (report) line = `Looked up for ${report.place} ${ago(report.generated_at)}. Open each source before you add one.`;
    return h("div", {},
      h("div", { class: "part-actions" }, place, start), h("p", { class: "muted hint" }, line),
      report && report.none_found ? h("p", {}, `Claude found no local tax on wages or income in ${report.place}.`) : null,
      report && report.taxes.length ? h("ul", { class: "local-list" }, report.taxes.map((tax) => h("li", {},
        h("strong", {}, tax.name), ` · ${tax.said}${tax.year ? ` (${tax.year})` : ""}`,
        tax.who === "workers" ? h("span", { class: "muted" }, " · only on people who work there") : null,
        tax.note ? h("span", { class: "muted" }, ` · ${tax.note}`) : null, " ", tax.sources.map(cite), " ",
        ownNames.has(tax.name) ? h("span", { class: "muted" }, "Added")
          : button("Add", () => send(named(), [...own(), { name: tax.name, rate: tax.rate, over: tax.over ?? null,
            over_married: tax.over_married ?? null, base: tax.base }]))))) : null,
      report && report.sources.length ? h("details", { class: "outlook-sources" }, h("summary", {}, `Sources (${report.sources.length})`),
        h("ol", {}, report.sources.map((s) => h("li", { value: String(s.n) },
          safeHref(s.url) ? h("a", { href: safeHref(s.url), target: "_blank", rel: "noopener noreferrer" }, s.title) : s.title)))) : null);
  };

  const draw = () => {
    clearTimeout(watch);
    fill(box,
      view.editable ? null : h("p", { class: "muted" }, "This is the demo, so local taxes can't be saved or looked up here."),
      h("h3", {}, "Where you live"), homeList(),
      h("h3", {}, "Search Pyrite's table"), search, results,
      h("h3", {}, "Add your own"), ownForm(),
      h("h3", {}, "Look up where you live"), research(),
      error);
    drawResults();
    // A lookup in progress is checked on until it's done, while this panel is still on the page.
    if (view.research && view.research.state === "running") watch = setTimeout(() => box.isConnected && load(), 5000);
  };
  const load = async () => {
    try {
      view = await api("/api/settings/local-taxes");
      draw();
    } catch (err) {
      fill(box, h("p", { class: "error" }, err.message));
    }
  };
  fill(box, h("p", { class: "muted" }, "Loading…"));
  load();
  return h("div", { class: "panel" }, h("h2", {}, "Local taxes at home"),
    h("p", { class: "muted hint" }, "City, county and district income taxes you pay where you live, taken from your pay at home in every comparison."),
    box);
}

function optionsSection(section) {
  let connection = null;
  if (section.status) {
    settingsStatusBoxes[section.status] = h("div", { class: "connection", "aria-live": "polite" });
    connection = h("div", { class: "panel" }, h("h2", {}, "Connection"), settingsStatusBoxes[section.status]);
  }
  return [
    h("p", { class: "muted settings-lead" }, section.intro),
    connection,
    section.id === "run" ? schedulePanel() : null,
    section.panels.map(optionsPanel),
    section.id === "relocation" ? localTaxPanel() : null,
    (section.notes || []).map((note) => h("p", { class: "muted hint settings-note" }, note)),
  ];
}

// ---- Cities and industries ----

function pointsPanel() {
  const promote = savedPromote();
  const city = numberInput(promote.city_points);
  const industry = numberInput(promote.industry_points);
  const mentions = numberInput(promote.mentions_needed);
  city.id = "default-city_points";
  industry.id = "default-industry_points";
  // The cities and industries without points of their own show the default they get, so a change shows there at once.
  [city, industry].forEach((input) => input.addEventListener("input", () => settingsRedraw.forEach((redraw) => redraw())));
  const root = h("div", { class: "panel" });
  const part = promotePart(root, (p) => {
    p.city_points = settingsNumber(city);
    p.industry_points = settingsNumber(industry);
    p.mentions_needed = settingsNumber(mentions);
  });
  root.append(h("h2", {}, "Points"),
    h("div", { class: "settings-defaults" },
      settingsField("A preferred city adds", city),
      settingsField("A preferred industry adds", industry),
      settingsField("Mentions needed", mentions, "Times a posting must use an industry's words to count.")),
    h("div", { class: "part-actions" }, part.save, part.status), part.error);
  return root;
}

// ---- City lookup ----
// The places your own postings name, so a city is typed the way the job boards write it.

const cityOf = (place) => {
  const pieces = place.split(",").map((piece) => piece.trim()).filter(Boolean);
  return /^(us|usa|united states)$/i.test(pieces[0] || "") && pieces.length > 1 ? pieces[pieces.length - 1] : pieces[0] || "";
};

function knownPlaces() {
  const counts = new Map();
  for (const job of state ? state.jobs : []) {
    for (const piece of (job.location || "").split(/\s*[|;]\s*/)) {
      const place = piece.replace(/\s*\([^)]*\)\s*$/, "").trim();
      if (!place || /^\d+ locations?$/i.test(place) || /^remote\b/i.test(place)) continue;
      counts.set(place, (counts.get(place) || 0) + 1);
    }
  }
  return [...counts].sort((a, b) => b[1] - a[1]);
}

function placeOptions() {
  const byCity = new Map();
  for (const [place, count] of knownPlaces()) {
    const city = cityOf(place);
    if (!city) continue;
    const entry = byCity.get(city) || { count: 0, places: [] };
    entry.count += count;
    entry.places.push(place);
    byCity.set(city, entry);
  }
  return [...byCity].sort((a, b) => b[1].count - a[1].count).slice(0, 200)
    .map(([city, entry]) => h("option", { value: city, label: `${entry.places[0]} · ${plural(entry.count, "posting")}` }));
}

// What a city name would match right now, by the same whole-word rule the ranking uses, and the points it adds.
function cityFeedback(name, pattern, points) {
  if (!name) return "";
  if (pattern) return `Adds ${points} to ${plural(onRadar(name), "prospect")} with your pattern, as last saved`;
  let whole;
  try {
    whole = new RegExp(`(?<!\\w)${escapeRegExp(name)}(?!\\w)`, "i");
  } catch (err) {
    return "";
  }
  const prospects = state ? state.jobs.filter((j) => j.status === "new" && whole.test(j.location || "")).length : 0;
  const places = knownPlaces().filter(([place]) => whole.test(place)).map(([place]) => place);
  if (!places.length) return "No posting names this place yet";
  const seen = places.length > 1 ? ` Seen as ${places.slice(0, 3).join(" · ")}${places.length > 3 ? " and more" : ""}.` : "";
  return `Adds ${points} to ${plural(prospects, "prospect")}.${seen}`;
}

function citiesPanel() {
  const rows = new Set();
  const body = h("tbody", {});
  const root = h("div", { class: "panel" });
  const part = promotePart(root, (p) => {
    p.cities =[...rows].map((row) => row.collect()).filter((city) => city.name.trim() || city.match.trim());
  });
  const addRow = (city) => {
    const name = h("input", { value: city.name || "", list: "place-options", placeholder: "Start typing a city", "aria-label": "City name", autocomplete: "off" });
    const points = numberInput(city.points);
    points.setAttribute("aria-label", "Points");
    const match = h("input", { value: city.match || "", placeholder: "Optional", "aria-label": "Pattern", title: "A pattern to use when the name alone isn't enough, as when another state has a city with the same name" });
    const seen = h("td", { class: "muted city-seen" });
    const row = { collect: () => ({ name: name.value, points: settingsNumber(points), match: match.value }) };
    row.show = () => {
      points.placeholder = `${defaultPoints("city_points")} (default)`;
      seen.textContent = cityFeedback(name.value.trim(), match.value.trim(), effectivePoints(points, "city_points"));
    };
    const line = h("tr", {}, h("td", {}, name), h("td", {}, points), h("td", {}, match), seen,
      h("td", {}, h("button", { class: "btn danger", type: "button", "aria-label": "Remove this city", onclick: () => {
        rows.delete(row);
        line.remove();
        part.touch();
      } }, "Remove")));
    [name, points, match].forEach((input) => input.addEventListener("input", row.show));
    rows.add(row);
    body.append(line);
    row.show();
    return name;
  };
  settingsRedraw.push(() => rows.forEach((row) => row.show()));
  root.append(h("h2", {}, "Cities"),
    h("p", { class: "muted hint" }, "Postings in these cities rank higher. Type a few letters to pick from the places your postings name."),
    h("datalist", { id: "place-options" }, placeOptions()),
    h("div", { class: "table-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ["City", "Points", "Pattern", "Matches now", ""].map((c) => h("th", {}, c)))), body)),
    h("div", { class: "part-actions" },
      h("button", { class: "btn", type: "button", onclick: () => addRow({}).focus() }, "Add a city"), part.save, part.status),
    part.error);
  savedPromote().cities.forEach(addRow);
  return root;
}

function skillsSummary(match) {
  if (!match || !(match.have.length + match.gaps.length)) return null;
  return h("div", { class: "skills" },
    h("p", {}, h("strong", {}, `Your fact bank has ${match.have.length} of ${match.have.length + match.gaps.length}`),
      h("span", { class: "muted" }, " of the skills it wants, by word match.")),
    h("div", { class: "signals" }, match.have.map((name) => pill("good", name, "Found in your fact bank")),
      match.gaps.map((name) => pill("muted", name, "Not in your fact bank. If it's true of you, add it on the Facts tab."))));
}

// An industry is a card that opens to edit. Closed, it shows what's saved in one line.
function industryCard(industry, index, cards) {
  const card = { index };
  const name = h("input", { value: industry.name || "", placeholder: "For example: Robotics" });
  const points = numberInput(industry.points);
  const terms = h("textarea", { rows: "4" });
  terms.value = (industry.terms || []).join("\n");
  const companies = h("textarea", { rows: "4" });
  companies.value = (industry.companies || []).join("\n");
  const wants = h("textarea", { rows: "4" });
  wants.value = (industry.wants || []).map((w) => (w.match ? `${w.name}: ${w.match}` : w.name)).join("\n");
  const naics = h("input", { value: (industry.naics || []).join(", "), placeholder: "For example: 3332, 334413" });
  const anywhere = h("input", { type: "checkbox", checked: industry.anywhere === true });
  const collect = () => ({
    anywhere: anywhere.checked,
    name: name.value,
    points: settingsNumber(points),
    terms: settingsLines(terms.value),
    companies: settingsLines(companies.value),
    wants: settingsLines(wants.value).map((line) => {
      const split = line.indexOf(": ");
      return split < 0 ? { name: line } : { name: line.slice(0, split), match: line.slice(split + 2) };
    }),
    naics: naics.value.split(/[\s,;]+/).filter(Boolean),
  });
  const summary = h("summary", {});
  const skills = h("div", {});
  const root = h("details", { class: "panel industry", open: index === null });
  card.describe = () => {
    points.placeholder = `${defaultPoints("industry_points")} (default)`;
    const saved = card.index === null ? null : savedPromote().industry[card.index];
    const facts = saved && settings.skills[saved.name];
    fill(summary,
      h("span", { class: "industry-name" }, saved ? saved.name : "New industry"),
      h("span", { class: "muted" }, saved ? [
        plural((saved.terms || []).length, "word"), plural((saved.companies || []).length, "employer"),
        saved.anywhere ? "kept anywhere" : null,
        plural(onRadar(saved.name), "prospect"),
        facts && facts.have.length + facts.gaps.length ? `${facts.have.length} of ${facts.have.length + facts.gaps.length} skills` : null,
      ].filter(Boolean).join(" · ") : "Not saved yet"));
    fill(skills, saved ? skillsSummary(facts) : null);
  };
  const part = promotePart(root, (p) => {
    if (card.index === null) p.industry.push(collect());
    else p.industry[card.index] = collect();
  }, () => {
    if (card.index === null) card.index = savedPromote().industry.length - 1;
  });
  const remove = h("button", { class: "btn danger", type: "button", onclick: async () => {
    if (card.index === null) {
      dirtyParts.delete(part);
      cards.delete(card);
      root.remove();
      return;
    }
    if (!window.confirm(`Remove ${savedPromote().industry[card.index].name}? This is saved straight away.`)) return;
    const gone = card.index;
    if (!await part.edit((p) => { p.industry.splice(gone, 1); })) return;
    cards.delete(card);
    cards.forEach((other) => { if (other.index !== null && other.index > gone) other.index -= 1; });
    root.remove();
  } }, "Remove");
  root.append(summary,
    h("div", { class: "industry-head" }, settingsField("Name", name), settingsField("Points", points),
      settingsField("Industry codes (NAICS)", naics, "For the official numbers on the Industries tab.")),
    h("div", { class: "industry-lists" },
      settingsField("Words in a posting", terms, "One per line. Patterns work: \\b marks a word's edge."),
      settingsField("Employers", companies, "One per line. These always count."),
      settingsField("Skills it wants", wants, "One per line, to compare with your fact bank.")),
    h("label", { class: "check" }, anywhere, h("span", {}, "Keep jobs outside your area",
      h("span", { class: "muted hint" }, "When the employer is listed above, or one of the words is in the employer's name or the title. They're marked Outside your area, and the next pan finds them."))),
    skills,
    h("div", { class: "part-actions" }, part.save, part.status, remove), part.error);
  cards.add(card);
  settingsRedraw.push(() => { if (cards.has(card)) card.describe(); });
  card.describe();
  return root;
}

function rankingSection() {
  const cards = new Set();
  const industries = h("div", { class: "industries" });
  const addIndustry = (industry, index) => industries.append(industryCard(industry, index, cards));
  savedPromote().industry.forEach((industry, index) => addIndustry(industry, index));
  return [
    h("p", { class: "muted settings-lead" }, "Preferred cities and industries move postings up your prospects. They don't change what's kept or tailored."),
    h("details", { class: "more" }, h("summary", {}, "How this works"),
      h("p", { class: "muted" }, "A match adds points to a posting's priority, which only changes the order you and the daily run see things in. It can't bring back a posting the filters dropped: to accept a new city at all, add it under [location] in profile/search.toml too. An industry counts when the employer is listed, a word is in the employer's name or the title, or the words appear often enough in the description. Filters and everything else stay in profile/search.toml. Saving here writes the [promote] section of that file out again in its usual layout, so comments of your own in that section are replaced. A setting there that this section doesn't show stops the save instead of being lost.")),
    pointsPanel(),
    citiesPanel(),
    h("div", { class: "settings-heading-row" }, h("h2", { class: "settings-heading" }, "Industries"),
      h("button", { class: "btn", type: "button", onclick: () => {
        addIndustry({}, null);
        industries.lastChild.querySelector("input").focus();
      } }, "Add an industry")),
    industries,
  ];
}

// Shows the section the address names, or the first when it names none that exists. Returns the one on show.
function pickSettingsSection() {
  const sections = [...document.querySelectorAll("#settings-form .settings-section")];
  if (!sections.length) return settingsAt;
  const shown = sections.find((section) => section.dataset.section === settingsAt) || sections[0];
  sections.forEach((section) => { section.hidden = section !== shown; });
  document.querySelectorAll("#settings-form .subnav button").forEach((button) => {
    if (button.dataset.section === shown.dataset.section) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  settingsAt = shown === sections[0] ? "" : shown.dataset.section;
  return settingsAt;
}

// Called by showTab with whatever follows "settings/" in the address.
function settingsShow(at) {
  const moved = at !== settingsAt;
  settingsAt = at;
  const shown = pickSettingsSection();
  if (moved) window.scrollTo(0, 0);
  return shown;
}

function renderSettings() {
  dirtyParts.clear();
  settingsRedraw.length = 0;
  Object.keys(settingsStatusBoxes).forEach((name) => delete settingsStatusBoxes[name]);
  const sections = [...settings.options.sections.map((section) => ({ ...section, body: optionsSection(section) })),
    { ...SETTINGS_RANKING, body: rankingSection() }];
  fill($("settings-form"),
    h("div", { class: "subnav-row" },
      h("nav", { class: "subnav", "aria-label": "Settings sections" }, sections.map((section) => h("button", {
        type: "button", "data-section": section.id, onclick: () => showTab(`settings/${section.id}`),
      }, section.label))),
      h("button", { class: "btn small", type: "button", onclick: reloadSettings }, "Reload")),
    h("datalist", { id: "model-options" }, MODEL_ALIASES.map((name) => h("option", { value: name }))),
    sections.map((section) => h("div", { class: "settings-section", "data-section": section.id, hidden: true }, section.body)));
  pickSettingsSection();
  drawSettingsStatus(null);
  loadSettingsStatus();
}

async function loadSettings() {
  try {
    settings = await api("/api/settings");
    renderSettings();
    $("settings-error").textContent = "";
  } catch (err) {
    $("settings-error").textContent = err.message;
  }
}

function reloadSettings() {
  if (dirtyParts.size && !window.confirm("Discard the changes you haven't saved?")) return;
  loadSettings();
}

// ---- Facts ----
// What a resume may claim. One section is edited at a time, and the server keeps the file from before each save.

let facts = null;
let factsOpen = false;
const APPROVES_NOTHING = /^## (do not use|unsupported)/i;

// The top of the file, then one piece per "## " heading. Joined back together they are the file.
const factsPieces = (file) => (file.key === "facts" ? file.text.split(/^(?=## )/m) : [file.text]);

function factsEditor(file, initial, rebuild) {
  factsOpen = true;
  document.querySelectorAll(".facts-edit").forEach((button) => { button.disabled = true; });
  const area = h("textarea", { class: "facts-area", rows: String(Math.min(28, Math.max(5, initial.split("\n").length + 2))) });
  area.value = initial;
  const error = h("p", { class: "error", role: "alert" });
  const save = h("button", { class: "btn primary", type: "button", onclick: async () => {
    error.textContent = "";
    const body = { file: file.key, version: file.version, text: rebuild(area.value) };
    const saved = (data) => { facts = data; renderFacts(); };
    try {
      saved(await api("/api/facts", body));
    } catch (err) {
      if (err.status !== 428) {
        error.textContent = err.message;
        return;
      }
      // Approving a term or unlisting a "Do not use" item: confirm with the code before it's saved.
      save.disabled = true;
      area.readOnly = true;
      const prompt = codePrompt(err.data,
        async (requestId, code) => saved(await api("/api/facts", { ...body, request_id: requestId, code })),
        () => { prompt.remove(); save.disabled = false; area.readOnly = false; area.focus(); });
      box.append(prompt);
    }
  } }, "Save");
  const cancel = h("button", { class: "btn", type: "button", onclick: renderFacts }, "Cancel");
  const box = h("div", { class: "facts-editing" }, area, h("div", { class: "part-actions" }, save, cancel), error);
  setTimeout(() => area.focus(), 0);
  return box;
}

function factsSection(file, pieces, index) {
  const piece = pieces[index];
  const heading = (piece.match(/^## (.*)$/m) || [])[1];
  const text = (heading ? piece.replace(/^## .*\n?/, "") : piece).trim();
  const body = h("div", { class: "prose facts-text" }, text || "Nothing here yet.");
  const box = h("div", { class: "facts-section" });
  const edit = h("button", { class: "btn facts-edit", type: "button", onclick: () => {
    body.replaceWith(factsEditor(file, piece.trimEnd(), (changed) => {
      const next = [...pieces];
      next[index] = changed.trim() ? `${changed.trimEnd()}\n\n` : "";
      return next.join("");
    }));
  } }, "Edit");
  box.append(
    h("div", { class: "facts-head" },
      file.key === "facts" ? h("h3", {}, heading || "Top of the file") : null,
      APPROVES_NOTHING.test(piece) ? pill("warn", "Approves nothing", "The assay never treats this section as a source. To block one of these by name, it also has to be listed under [guard] in profile/search.toml.") : null,
      facts.editable ? edit : null),
    body);
  return box;
}

function factsPanel(file) {
  const pieces = factsPieces(file);
  const hint = file.key === "facts"
    ? "The source of truth for every draft. Numbers and terms a resume uses have to appear here."
    : "One per line: specialist terms that are true of you but aren't named in the fact bank. A line starting with # is a comment, which approves nothing.";
  const panel = h("div", { class: "panel facts-file" }, h("h2", {}, file.title), h("p", { class: "muted hint" }, `${file.path}. ${hint}`));
  pieces.forEach((piece, index) => { if (piece.trim() || pieces.length === 1) panel.append(factsSection(file, pieces, index)); });
  if (file.key === "facts" && facts.editable) {
    const add = h("button", { class: "btn facts-edit", type: "button", onclick: () => {
      add.replaceWith(factsEditor(file, "## New section\n- ", (changed) => `${file.text.trimEnd()}\n\n${changed.trimEnd()}\n`));
    } }, "Add a section");
    panel.append(add);
  }
  return panel;
}

function renderFacts() {
  factsOpen = false;
  fill($("facts-view"),
    h("p", { class: "muted" }, facts.editable
      ? "What a resume may claim. The assay reads these files as they stand each time it checks a draft, and History on the Profile tab keeps the version before each save, so it can be put back."
      : "What a resume may claim. This is the demo's fictional candidate, so it can't be changed here."),
    facts.files.map(factsPanel));
}

async function loadFacts() {
  try {
    facts = await api("/api/facts");
    renderFacts();
    $("facts-error").textContent = "";
  } catch (err) {
    $("facts-error").textContent = err.message;
  }
}

// ---- Runs you start yourself ----

const RUNS = {
  sweep: { button: "run-sweep", idle: "Check boards now", busy: "Checking boards…", name: "Board check" },
  claude: { button: "run-claude", idle: "Run Claude now", busy: "Claude is working…", name: "Claude run" },
  // Its button sits in the Being tailored column, so renderBoard draws it and renderRuns only reports on it.
  tailor: { button: "run-tailor", idle: "Tailor these now", busy: "Tailoring…", name: "Tailoring batch" },
};
const RUN_RESULT_SHOWN_FOR = 30 * 60e3;
let runWatch = null;
let runError = "";

// Why this workspace can't start this kind of run at all yet, such as facts.md still being the example's.
function notReady(kind) {
  return (state.not_ready || {})[kind] || "";
}

function renderRuns() {
  const tasks = state.tasks || {};
  const lines = runError ? [h("span", { class: "alert" }, runError)] : [];
  let running = false;
  for (const [kind, run] of Object.entries(RUNS)) {
    const task = tasks[kind];
    const busy = Boolean(task && task.state === "running");
    running = running || busy;
    const button = $(run.button);
    if (button) {
      // The demo starts no runs, and a workspace still holding the example's facts starts no Claude runs, so their
      // buttons say why rather than asking to spend your Claude plan and then refusing.
      const why = notReady(kind);
      if (!("idleTitle" in button.dataset)) button.dataset.idleTitle = button.title;
      button.disabled = busy || Boolean(state.demo) || Boolean(why);
      button.textContent = busy ? run.busy : run.idle;
      button.title = state.demo ? DEMO_NO_RUNS : why || button.dataset.idleTitle;
    }
    if (!task || (kind === "sweep" && sweepShownAbove(task))) continue;
    const ended = task.finished_at || task.started_at;
    if (busy) lines.push(h("span", {}, `${run.name}, started ${ago(task.started_at)}: ${task.detail}`));
    else if (task.state === "failed") {
      lines.push(h("span", { class: "alert" }, `${run.name} failed ${ago(ended)}: ${task.detail}`));
      if (task.problem && task.problem.kind === "profile_changed") lines.push(profileChangeAnswers(kind, task, tasks));
    } else if (task.state === "cleared") {
      if (Date.now() - toDate(task.cleared_at).getTime() < RUN_RESULT_SHOWN_FOR) {
        lines.push(h("span", {}, `${run.name} stopped ${ago(ended)} for a change to profile/ you said was yours.`));
      }
    } else if (Date.now() - toDate(ended).getTime() < RUN_RESULT_SHOWN_FOR) {
      lines.push(h("span", {}, `${run.name} finished ${ago(ended)}. ${kind === "claude" ? "Its field report is on the To do page." : task.detail}`));
    }
  }
  fill($("runs"), lines.flatMap((line, index) => (index ? [h("br"), line] : [line])));
  // The mark beside the title throws sparks while anything runs, and only glints now and then otherwise.
  $("mark").classList.toggle("working", running);
  // While something is running, look again soon so its progress and its results show up.
  clearTimeout(runWatch);
  if (running) runWatch = setTimeout(refresh, 5000);
}

const RUN_QUESTIONS = {
  claude: "Have Claude judge the new postings and tailor the best ones now?\n\nIt can take a while and uses your Claude plan. Each draft still has to pass the assay.",
  tailor: "Have Claude write every draft under Being tailored now, stretch jobs included?\n\nIt uses your Claude plan. Each draft still has to pass the assay.",
};

// A writing run stops when something under profile/ changes while Claude writes. When the change was yours, these say
// so: that one warning clears and the job's timeline keeps that you said it. Again also starts the same kind of run.
function profileChangeAnswers(kind, task, tasks) {
  const writing = ["claude", "tailor"].find((other) => tasks[other] && tasks[other].state === "running");
  const why = state.demo ? DEMO_NO_RUNS : notReady(kind)
    || (writing ? `${RUNS[writing].name} is going, and both write drafts, so this waits for it.` : "");
  return h("span", { class: "row run-answers" },
    h("button", { class: "btn small", type: "button", title: "Clear this warning. The job's timeline keeps that you said so.",
      onclick: () => acceptProfileChange(kind, task, false) }, "I made this change"),
    h("button", { class: "btn small", type: "button", disabled: Boolean(why),
      title: why || "Clear this warning and start the run again. Uses your Claude plan.",
      onclick: () => acceptProfileChange(kind, task, true) }, kind === "tailor" ? "I made it, tailor again" : "I made it, run Claude again"));
}

async function acceptProfileChange(kind, task, retry) {
  if (retry && !window.confirm(RUN_QUESTIONS[kind])) return;
  runError = "";
  try {
    await api("/api/run/accept", { id: task.id, retry });
  } catch (err) {
    runError = err.message;
  }
  await refresh();
}

async function startRun(kind) {
  if (RUN_QUESTIONS[kind] && !window.confirm(RUN_QUESTIONS[kind])) return;
  runError = "";
  try {
    await api("/api/run", { kind });
  } catch (err) {
    runError = err.message;
  }
  await refresh();
}

function render() {
  $("demo-tag").hidden = !state.demo;
  // The copy from last time can't say whether setup is still needed, so that waits for the server.
  if (!keptAt) offerSetup();
  // The to-do count shows in the browser tab, so a background tab says when something needs you.
  document.title = state.orders.length ? `(${state.orders.length}) Pyrite` : "Pyrite";
  renderSweep();
  renderRuns();
  renderStatus();
  renderKpis();
  renderOrders();
  renderRail();
  renderBoard();
  renderRadar();
  renderArchive();
  renderSources();
}

// The last state the server sent, kept in this browser so the next load shows it at once while the server works out the
// latest, which takes several seconds after a restart. Without storage the page waits for the server, as it always did.
const LAST_STATE = "pyrite.last-state";

function keepState() {
  try {
    localStorage.setItem(LAST_STATE, JSON.stringify({ at: new Date().toISOString(), state }));
  } catch (err) { /* Full or turned off: the next load waits for the server instead. */ }
}

function showKept() {
  try {
    const kept = JSON.parse(localStorage.getItem(LAST_STATE) || "null");
    if (!kept || !kept.state || !kept.at) return;
    state = kept.state;
    keptAt = kept.at;
    render();
  } catch (err) {
    // A copy an older Pyrite kept may not draw. Then the page waits for the server, as with none.
    state = null;
    keptAt = null;
    try { localStorage.removeItem(LAST_STATE); } catch (e) { /* Nothing more to do. */ }
  }
}

async function refresh() {
  try {
    state = await api("/api/state");
    keptAt = null;
    render();
    keepState();
  } catch (err) {
    // fetch throws a TypeError when nothing answered. Anything else is the server saying what's wrong.
    const said = err instanceof TypeError ? "Can't reach the server. Is Pyrite still running?" : err.message;
    $("sweep").textContent = said;
    renderStatus(said);
  }
}

// ---- Job drawer ----

// The panel's buttons stay disabled while a request is out, so a second click can't send it twice.
async function holdButtons(root, work) {
  const held = [...root.querySelectorAll("button:not(:disabled)")];
  held.forEach((button) => { button.disabled = true; });
  try {
    return await work();
  } finally {
    held.forEach((button) => { button.disabled = false; });
  }
}

// What you've typed into a job's panel and not saved, by job and field. Redrawing the panel, Next or Close
// would otherwise throw it away. It lives only as long as the page.
const drafts = new Map();

function keepDraft(id, field, el, saved, status) {
  const draft = drafts.get(id) || {};
  el.value = field in draft ? draft[field] : saved;
  const show = () => { if (status) status.textContent = el.value === saved ? "" : "Not saved yet"; };
  el.addEventListener("input", () => {
    const now = drafts.get(id) || {};
    if (el.value === saved) delete now[field];
    else now[field] = el.value;
    if (Object.keys(now).length) drafts.set(id, now);
    else drafts.delete(id);
    show();
  });
  show();
}

function forgetDraft(id, fields) {
  const draft = drafts.get(id);
  if (!draft) return;
  fields.forEach((field) => { delete draft[field]; });
  if (!Object.keys(draft).length) drafts.delete(id);
}

// `saves` names the draft fields this action stores, which are dropped once it succeeds.
async function act(id, body, saves = []) {
  await holdButtons($("drawer"), async () => {
    await api(`/api/job/${id}/action`, body);
    forgetDraft(id, saves);
    await refresh();
    await openJob(id);
  });
}

async function dismissAlert(id) {
  try {
    await api(`/api/alert/${id}/dismiss`, {});
    await refresh();
  } catch (err) {
    alert(err.message);
  }
}

// A button that fails says so in the panel. Otherwise a refused or timed-out action looks like nothing happened.
async function tryAct(id, body, what = "That didn't go through", saves = []) {
  try {
    await act(id, body, saves);
  } catch (err) {
    fill($("refresh-error"), h("div", { class: "callout bad" }, h("strong", {}, what), h("p", {}, err.message)));
    $("refresh-error").scrollIntoView({ block: "nearest" });
  }
}

const autofilling = (job) => Boolean(job.autofill && job.autofill.state === "running");

// Types the fill sheet into the Workday form in a browser window of its own. It stops before Submit, which stays yours.
async function startAutofill(job) {
  const question = "Fill this job's Workday form?\n\nA browser window opens on the posting. Sign in there if it asks, click Apply, then Apply Manually, and watch it type each page. It stops before the voluntary disclosures and never submits: you answer what it lists, read the review page and click Submit yourself.";
  if (!window.confirm(question)) return;
  try {
    await act(job.id, { action: "autofill" });
  } catch (err) {
    fill($("refresh-error"), h("div", { class: "callout bad" }, h("strong", {}, "Couldn't start filling the form"), h("p", {}, err.message)));
  }
}

function autofillButton(job) {
  if (!job.can_autofill) return null;
  return h("button", { class: "btn", type: "button", disabled: autofilling(job), onclick: () => startAutofill(job) },
    autofilling(job) ? "Filling the Workday form…" : "Fill Workday form");
}

function autofillBlock(job) {
  const result = job.autofill;
  if (!result) return null;
  const lines = (result.detail || "").split("\n").filter(Boolean);
  const log = job.autofill_log ? h("p", {}, h("a", { href: fileHref(job.autofill_log), target: "_blank", rel: "noopener" }, "The run's log")) : null;
  if (result.state === "running") {
    return h("div", { class: "callout" }, h("strong", {}, "Filling the Workday form"),
      h("p", {}, "A Chromium window opened on the posting, probably behind this one: look for it in the taskbar. Sign in there if asked, click Apply, then Apply Manually. It waits up to 15 minutes for the form. When it stops, finish the form there: answer what it lists, read the review page and click Submit yourself."));
  }
  if (result.state === "failed") {
    return h("div", { class: "callout bad" }, h("strong", {}, `The last fill failed, ${ago(result.at)}`), lines.map((line) => h("p", {}, line)), log);
  }
  return h("div", { class: "callout" }, h("strong", {}, `Workday form filled ${ago(result.at)}`),
    h("p", {}, lines[0] || ""), lines.length > 1 ? h("ul", {}, lines.slice(1).map((line) => h("li", {}, line))) : null,
    h("p", { class: "muted" }, "The browser window stays open for you to finish and submit. Nothing here submits."), log);
}

// The Workday paste sheet merged with this job's tailored role text, for you to fill the form from. Nothing submits.
const fillButton = (job) => (job.can_fill
  ? h("button", { class: "btn", type: "button", title: "Writes fill-sheet.md in the job's folder: the Workday paste sheet with this resume's role text",
    onclick: () => tryAct(job.id, { action: "fill_sheet" }, "Couldn't write the fill sheet") }, job.fill_sheet ? "Remake fill sheet" : "Make fill sheet")
  : null);

const recheckButton = (job) => (job.can_recheck
  ? h("div", { class: "row" }, h("button", { class: "btn", type: "button",
    onclick: () => tryAct(job.id, { action: "recheck" }, "Couldn't check this draft") }, "Check again"))
  : null);

// The pass covers the files as they were. If they've changed since, say so before anything is sent.
function changedBlock(job) {
  const changed = job.changed_since_check || [];
  if (!changed.length) return null;
  return h("div", { class: "callout bad" },
    h("strong", {}, "Changed since the assay passed it"),
    h("p", {}, `${changed.join(", ")} changed after this draft passed, so the pass no longer covers what's on file. Check it again before you send it.`),
    recheckButton(job));
}

// After sending, the folder is a record. Say so, link the sent copies, and shout if the record has drifted.
function frozenBlock(job) {
  if (!job.frozen) return null;
  const changed = job.changed_after_sending || [];
  const links = (job.sent_files || []).map((file) => h("a", { class: "btn", href: fileHref(file), target: "_blank", rel: "noopener" },
    `Sent ${file.split("/").pop().replace(/^.*?(?=Resume|Cover_Letter|resume|cover-letter)/, "").replace(/_/g, " ")}`));
  const known = job.acknowledged_changes || [];
  // Got it says the folder as it is now is fine, such as one kept as a model for later applications. The warning
  // comes back if the folder changes after that.
  const gotIt = changed.length ? h("button", { class: "btn", type: "button",
    title: "Stop showing this for the files as they are now. It shows again if they change.",
    onclick: () => tryAct(job.id, { action: "acknowledge_changes" }, "Couldn't save that") }, "Got it") : null;
  return h("div", { class: changed.length ? "callout bad" : "callout" },
    h("strong", {}, changed.length ? "Changed after sending" : `Frozen since you applied on ${shortDate(job.applied_at)}`),
    h("p", {}, changed.length
      ? `${changed.join(", ")} no longer match the copy kept when you applied. The sent copies below are the record; the files in the folder are not what the company has.`
      : links.length ? "The copies below are what went out. The folder's documents aren't rebuilt or refreshed any more; a new application gets a new job."
        : "No copy of the sent documents is on record for this job, so the folder's files may not match what the company has."),
    known.length ? h("p", { class: "muted" }, `${known.join(", ")} changed after sending, and you said that's fine. The sent copies are still the record.`) : null,
    gotIt ? h("div", { class: "row" }, gotIt) : null,
    links.length ? h("div", { class: "row" }, links) : null);
}

function stuckBlock(job) {
  if (job.status !== "needs_fix" || !job.fix_limit || job.fix_attempts < job.fix_limit) return null;
  return h("div", { class: "callout" },
    h("strong", {}, "The daily run has stopped retrying this draft"),
    h("p", {}, `It failed the assay ${job.fix_attempts} times. Fix the draft and check it again, or use Tailor this one first to give the daily run another set of tries.`));
}

function actionButtons(job, noteEl) {
  const note = () => noteEl.value.trim();
  const button = (label, body, cls = "btn") => h("button", {
    class: cls, type: "button", onclick: () => tryAct(job.id, { ...body, note: note() }, undefined, ["update"]),
  }, label);
  const status = (s) => ({ action: "status", status: s });
  const heard = (kind) => ({ action: "heard_back", kind });
  // Tailor and Pass move on to the next job in the list you opened this from, since that's what you'd click next anyway.
  const triageButton = (label, action, cls = "btn", key = "") => h("button", {
    class: cls, type: "button", title: key ? `Shortcut: ${key}` : null, onclick: () => triage(job, action, true, note()),
  }, label);
  switch (job.status) {
    case "new":
      return [triageButton("Tailor a resume next", "tailor_next", "btn primary", "T"), triageButton("Pass", "pass", "btn", "P")];
    case "shortlisted":
    case "needs_fix":
      return [triageButton("Tailor this one first", "tailor_next", "btn primary", "T"), triageButton("Pass", "pass", "btn", "P")];
    case "ready":
      return [h("button", { class: "btn primary", type: "button", onclick: () => confirmApplied(job, note()) }, "I applied"), triageButton("Pass", "pass")];
    case "applied":
      return [button("Got a reply", heard("reply"), "btn primary"), button("Interview", heard("interview")),
        button("Rejected", heard("rejected")), button("Ghosted", status("ghosted")), button("Withdraw", status("withdrawn"))];
    case "responded":
      return [button("Interview", heard("interview"), "btn primary"), button("Offer", heard("offer")),
        button("Rejected", heard("rejected")), button("Withdraw", status("withdrawn"))];
    case "interviewing":
      return [button("Offer", heard("offer"), "btn primary"), button("Rejected", heard("rejected")), button("Withdraw", status("withdrawn"))];
    case "offer":
      return [button("Withdraw or decline", status("withdrawn"))];
    default:
      return [job.can_unpass ? button("Undo pass", { action: "unpass" }, "btn primary") : button("Reopen", { action: "reopen" }, "btn primary")];
  }
}

// Applying freezes the folder as the record of what was sent, so it asks first, and says so plainly when the check no longer covers the files.
function confirmApplied(job, note) {
  const changed = job.changed_since_check || [];
  const question = changed.length
    ? `The fact check doesn't cover what's in the folder now: ${changed.join(", ")} changed after it passed.\n\nUse Check again first if you can. Record that you applied to ${job.company} anyway?`
    : `Record that you applied to ${job.company} today?\n\nThis keeps a read-only copy of the documents as what was sent, freezes the folder and sets a follow-up reminder.`;
  if (window.confirm(question)) tryAct(job.id, { action: "status", status: "applied", note }, undefined, ["update"]);
}

// ---- Triage: pass or tailor, then on to the next ----

let nav = [];
let toastTimer = null;

function toast(text, undo) {
  const box = $("toast");
  fill(box, h("span", {}, text), undo ? h("button", { class: "btn small", type: "button", onclick: async () => {
    box.hidden = true;
    try {
      await undo();
    } catch (err) {
      runError = err.message;
    }
    await refresh();
  } }, "Undo") : null);
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 10000);
}

function nextInList(id) {
  const at = nav.indexOf(id);
  return at < 0 ? null : nav[at + 1] ?? nav[at - 1] ?? null;
}

// Jobs with a pass or tailor still on its way, so a held-down key or a double click sends it once.
const triaging = new Set();

async function triage(job, action, fromPanel, note = "") {
  if (triaging.has(job.id)) return;
  triaging.add(job.id);
  try {
    await (fromPanel ? holdButtons($("drawer"), () => triageNow(job, action, true, note)) : triageNow(job, action, false, note));
  } finally {
    triaging.delete(job.id);
  }
}

async function triageNow(job, action, fromPanel, note) {
  const body = action === "pass" ? { action: "status", status: "passed", note } : { action: "tailor_next", note };
  const next = fromPanel ? nextInList(job.id) : null;
  try {
    await api(`/api/job/${job.id}/action`, body);
  } catch (err) {
    toast(`${job.company}: ${err.message}`);
    return;
  }
  forgetDraft(job.id, ["update"]);
  if (action === "pass") {
    toast(`Passed on ${job.company}: ${job.title}`, () => api(`/api/job/${job.id}/action`, { action: "unpass" }));
  } else {
    toast(`${job.company}: ${job.title} is queued for tailoring.`);
  }
  nav = nav.filter((id) => id !== job.id);
  await refresh();
  if (!fromPanel) return;
  if (next) await openJob(next);
  else closeDrawer();
}

// What could stop this application, gathered where you can't miss it: the deadline, the notes' warnings and what you've already sent there.
function beforeApplyBlock(job) {
  if (!NOT_SENT.includes(job.status)) return null;
  const lines = [];
  const days = job.days_to_deadline;
  if (days !== null && days !== undefined) {
    const on = dayName(job.deadline);
    lines.push(days < 0 && job.deadline_firm === false ? `It took applications at least until ${on}, so it may close any day.`
      : days < 0 ? `The posting's stated deadline, ${on}, has passed. Check it's still up before you spend time on it.`
        : days === 0 ? `Apply today. The posting gives ${on} as its deadline.`
          : `Apply by ${on}${days === 1 ? ", tomorrow" : `, in ${days} days`}.`);
  }
  const same = job.same_title_applied;
  if (same) lines.push(`You applied for ${same.title} here on ${shortDate(same.applied_at)}. This may be another listing of the same job.`);
  if (job.applied_here >= job.company_limit) lines.push(`You've sent ${job.company} ${job.applied_here} applications already, and your limit is ${job.company_limit}.`);
  const blockers = job.blockers || [];
  if (!lines.length && !blockers.length) return null;
  const urgent = (days !== null && days !== undefined && days >= 0 && days <= 2) || blockers.length || same;
  return h("div", { class: `callout${urgent ? " bad" : ""}` },
    h("strong", {}, "Before you apply"),
    h("ul", {}, lines.map((line) => h("li", {}, line)), blockers.map((line) => {
      // The label in bold, then the reason. A label written as the reason's own opening isn't said twice.
      // A label cut short with … is the reason's own start, so the reason alone says it.
      const label = blockerLabel(job, line);
      if (label === line || label.endsWith("…")) return h("li", {}, line);
      const rest = line.startsWith(label) ? line.slice(label.length).replace(/^[.:?!]\s*/, "") : line;
      return h("li", {}, rest ? [h("b", {}, label), " ", rest] : h("b", {}, label));
    })),
    blockers.length ? h("p", { class: "muted" }, "From this job's notes. The full reasoning is under Fit and interview notes.") : null);
}

// The sentences behind the pay, rarity and skill-age pills, plus the ages of the young skills it asks for, so the
// numbers can be checked. An ask the notes listed as something to settle first, which nobody could meet, is said here.
function readBlock(job) {
  const lines = [];
  for (const sign of job.pay_signs || []) lines.push(`${sign.label}: ${sign.detail}`);
  if (job.rare) lines.push(`Rare near you: ${job.rare_reason}.`);
  for (const ask of job.skill_asks || []) lines.push(`${ask.said} The posting says: "${ask.words}"`);
  for (const blocker of job.impossible_blockers || []) lines.push(`Left off Before you apply, since nobody could meet it: ${blocker}`);
  if (!lines.length) return null;
  return h("div", {}, h("h3", {}, "What Pyrite read into it"), h("ul", { class: "muted" }, lines.map((line) => h("li", {}, line))));
}

// For a job that asks you to move: what its pay is worth after taxes and prices there, against your pay now at home.
// relocate.py works it all out. This only lays it out: the break-even pay, then the range in home dollars, in each view.
const thousands = (n) => `$${Math.round(n / 1000).toLocaleString()}k`;
const signedPercent = (n) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(Math.round(n * 100))}%`;

function relocationBlock(job) {
  const r = job.relocation;
  if (!r) return null;
  const heading = h("h3", {}, "Moving for it");
  if (r.problem) return h("div", { class: "relocation" }, heading, h("p", { class: "muted" }, r.problem));
  const views = r.views;
  const rows = [h("tr", {}, h("td", {}, "Break-even pay"), views.map((v) => h("td", { class: "num" }, thousands(v.break_even))))];
  views[0].points.forEach((point, at) => rows.push(h("tr", {},
    h("td", {}, `${point.label} of range, ${thousands(point.pay)}`),
    views.map((v) => {
      const p = v.points[at];
      return h("td", { class: `num ${p.change >= 0 ? "up" : "down"}` }, `${thousands(p.worth)} (${signedPercent(p.change)})`);
    }))));
  const there = r.there;
  const local = there.local.length ? ` Local taxes there: ${there.local.join(", ")}.` : "";
  const taxRows = (lines) => h("ul", {}, lines.map((line) => h("li", {}, `${line.label}: ${thousands(line.amount)}`)));
  return h("div", { class: "relocation" },
    heading,
    h("p", {}, r.summary),
    h("div", { class: "table-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, h("th", {}, ""), views.map((v) => h("th", { class: "num" }, v.label)))),
      h("tbody", {}, rows))),
    h("p", { class: "info-note" }, `Home is ${r.home.name}, where your ${thousands(r.home.pay)} takes home ${thousands(r.home.net)}. `,
      `In ${there.name}, prices are ${signedPercent(r.prices.all - 1)} on everything and ${signedPercent(r.prices.housing - 1)} on housing, `,
      `and the same pay would take home ${thousands(there.same_pay_net)}.${local} The percents compare with your take-home now.`),
    h("details", { class: "relocation-taxes" }, h("summary", {}, "Taxes on each side"),
      h("p", { class: "muted" }, `Your ${thousands(r.home.pay)} at home, a year:`), taxRows(r.home.taxes),
      h("p", { class: "muted" }, `The same pay in ${there.name}:`), taxRows(there.same_pay_taxes)),
    h("ul", { class: "info-note" }, r.notes.map((note) => h("li", {}, note))));
}

const fileLabel = (file) => file.split("/").pop().replace(/^.*?(?=Resume|Cover_Letter)/, "").replace(/_/g, " ");
const fileLink = (file, label = fileLabel(file), cls = "btn") => h("a", { class: cls, href: fileHref(file), target: "_blank", rel: "noopener" }, label);
// Workday mangles a PDF's line breaks, so it gets the Word file. Everywhere else the PDF looks the same for every reader.
const uploadKind = (job) => (/workday/i.test(job.source_key || "") || /myworkdayjobs\.com/i.test(job.url || "") ? ".docx" : ".pdf");

// The posting and the one file of each kind to upload, with every other file a click away.
function applyRow(job, href) {
  const docs = job.files.filter((f) => /\.(pdf|docx|txt)$/.test(f));
  const kind = uploadKind(job);
  const pick = (name) => docs.find((f) => f.split("/").pop().includes(name) && f.endsWith(kind));
  const resume = pick("Resume");
  const letter = pick("Cover_Letter");
  const others = [...docs.filter((f) => f !== resume && f !== letter),
    ...[job.prep_file, job.fill_sheet].filter(Boolean)];
  const otherLabel = (file) => (file === job.prep_file ? "Interview prep brief" : file === job.fill_sheet ? "Fill sheet" : fileLabel(file));
  return h("div", { class: "stack" },
    h("div", { class: "row" },
      href ? h("a", { class: `btn${job.status === "ready" ? " primary" : ""}`, href, target: "_blank", rel: "noopener noreferrer" }, "Open posting") : null,
      resume ? fileLink(resume, `Resume (${kind})`) : null,
      letter ? fileLink(letter, `Cover letter (${kind})`) : null,
      typeof autofillButton === "function" ? autofillButton(job) : null),
    others.length ? h("details", { class: "more-files" }, h("summary", {}, `All files (${others.length + [resume, letter].filter(Boolean).length})`),
      h("div", { class: "row" }, others.map((file) => fileLink(file, otherLabel(file))))) : null);
}

// The tools that rewrite or prepare, which cost a Claude run or change files, kept apart from the path to sending.
function toolsRow(job) {
  const tools = [refreshButton(job), prepButton(job), typeof fillButton === "function" ? fillButton(job) : null].filter(Boolean);
  return tools.length ? h("div", {}, h("h3", {}, "Rewrite or prepare"), h("div", { class: "row" }, tools)) : null;
}

// A checklist you tick as you go. It isn't saved: it's there so nothing on it is skipped in a hurry.
function beforeSendBlock(job) {
  if (job.status !== "ready") return null;
  const items = ["Read it through: you'll be asked about every line.", ...state.before_send];
  return h("div", { class: "callout checklist" }, h("strong", {}, "Before you send"),
    h("ul", {}, items.map((item) => h("li", {}, h("label", {}, h("input", { type: "checkbox" }), " ", item)))));
}

function navBar(id) {
  const at = nav.indexOf(id);
  if (at < 0 || nav.length < 2) return null;
  const go = (to) => (to === undefined ? null : () => openJob(to));
  return h("div", { class: "row nav" },
    h("button", { class: "btn small", type: "button", disabled: at === 0, title: "Shortcut: K", onclick: go(nav[at - 1]) }, "‹ Previous"),
    h("span", { class: "muted" }, `${at + 1} of ${nav.length}`),
    h("button", { class: "btn small", type: "button", disabled: at === nav.length - 1, title: "Shortcut: J", onclick: go(nav[at + 1]) }, "Next ›"));
}

// The sender and subject come from whoever sent the mail, so they stay plain text.
function replyBlock(job) {
  const reply = job.possible_reply;
  if (!reply) return null;
  const more = reply.count > 1 ? ` This is the latest of ${reply.count} messages: the timeline has the rest.` : "";
  return h("div", { class: "callout" },
    h("strong", {}, "Possible reply"),
    h("p", { class: "reply-detail" }, reply.detail),
    h("p", {}, `An automatic match on the sender and company, which changes nothing by itself. Read the email, then update the status below if it's real.${more}`),
    h("div", { class: "row reply-actions" }, h("button", { class: "btn", type: "button",
      onclick: () => tryAct(job.id, { action: "dismiss_reply" }) }, "Dismiss")));
}

function checkBlock(job) {
  const result = job.check_result;
  if (!result) return null;
  const list = (items) => h("ul", {}, items.map((item) => h("li", {}, item)));
  const blocks = [];
  if (result.errors && result.errors.length) {
    blocks.push(h("div", { class: "callout bad" }, h("strong", {}, "The assay blocked this draft"), list(result.errors),
      job.status === "needs_fix" ? recheckButton(job) : null));
  }
  if (result.warnings && result.warnings.length) {
    blocks.push(h("div", { class: "callout" }, h("strong", {}, "Worth a look"), list(result.warnings)));
  }
  if (result.overlap && result.overlap.pct !== null) {
    const missing = result.overlap.missing.length ? ` Not on the resume: ${result.overlap.missing.join(", ")}.` : "";
    const pct = result.overlap.pct;
    // Once sent, the figure is a fact about what the company has, and advice to change it can't be acted on.
    const band = job.frozen ? ""
      : pct > 85 ? " That's high enough to read as copied from the posting, which screeners now mark down: aim for 60 to 80%."
      : pct < 40 ? " Below about 40%, a filter on skills may not pick it up." : "";
    const uses = job.frozen ? "The resume sent uses" : "The resume uses";
    blocks.push(h("p", { class: "muted" }, `${uses} ${pct}% of the skill terms in this posting.${job.frozen ? "" : missing}${band}`));
  }
  const built = result.sent_drafter || result.drafter;
  if (built && Object.keys(built).length) {
    const versions = [...new Set(Object.values(built))].sort().join(" and ");
    blocks.push(h("p", { class: "muted" }, job.frozen ? `Sent with drafter ${versions}. What was sent is the record, so it isn't rebuilt.`
      : `Documents built by drafter ${versions}.`));
  }
  return blocks;
}

const refreshing = (job) => Boolean(job.refresh && job.refresh.state === "running");
const prepping = (job) => Boolean(job.prep && job.prep.state === "running");
const researching = (job) => Boolean(job.culture && job.culture.state === "running");
const working = (job) => refreshing(job) || prepping(job) || researching(job);
const fileHref = (file) => `/files/${file.split("/").map(encodeURIComponent).join("/")}`;

async function startRefresh(job) {
  const question = "Have Claude rewrite this resume from the posting and your fact bank?\n\nIt takes a few minutes and uses your Claude plan. The new version only replaces this one if it passes the assay.";
  if (!window.confirm(question)) return;
  try {
    await act(job.id, { action: "refresh_resume" });
  } catch (err) {
    fill($("refresh-error"), h("div", { class: "callout bad" }, h("strong", {}, "Couldn't refresh this resume"), h("p", {}, err.message)));
  }
}

function refreshButton(job) {
  if (!job.can_refresh) return null;
  return h("button", { class: "btn", type: "button", disabled: refreshing(job) || inDemo(), title: demoTitle(), onclick: () => startRefresh(job) },
    refreshing(job) ? "Refreshing resume…" : "Refresh resume");
}

function refreshBlock(job) {
  const result = job.refresh;
  if (!result) return null;
  if (result.state === "running") {
    return h("div", { class: "callout" }, h("strong", {}, "Claude is rewriting this resume"),
      h("p", {}, "This usually takes a few minutes, and you can close this panel meanwhile. The current version stays until the new one passes the assay."));
  }
  if (result.state === "failed") {
    return h("div", { class: "callout bad" }, h("strong", {}, `Last refresh failed, ${ago(result.at)}`), h("p", {}, result.detail));
  }
  return h("div", { class: "callout" }, h("strong", {}, `Resume refreshed ${ago(result.at)}`), h("p", {}, result.detail),
    h("p", { class: "muted" }, "Read it through before you send it. The version before this one is in resume.previous.md in its folder."));
}

async function startPrep(job) {
  const replaces = job.prep_file ? " The brief you have now stays unless the new one passes." : "";
  const question = `Have Claude write an interview prep brief from the posting, your resume and your fact bank?\n\nIt takes a few minutes and uses your Claude plan. The brief is kept only if it passes the assay.${replaces}`;
  if (!window.confirm(question)) return;
  try {
    await act(job.id, { action: "interview_prep" });
  } catch (err) {
    fill($("refresh-error"), h("div", { class: "callout bad" }, h("strong", {}, "Couldn't write the interview prep"), h("p", {}, err.message)));
  }
}

function prepButton(job) {
  if (!job.can_prep) return null;
  return h("button", { class: "btn", type: "button", disabled: prepping(job) || inDemo(), title: demoTitle(), onclick: () => startPrep(job) },
    prepping(job) ? "Writing interview prep…" : job.prep_file ? "Redo interview prep" : "Interview prep");
}

function prepBlock(job) {
  const result = job.prep;
  if (!result) return null;
  const detail = (result.detail || "").split("\n").filter(Boolean).map((line) => h("p", {}, line));
  if (result.state === "running") {
    return h("div", { class: "callout" }, h("strong", {}, "Claude is writing your interview prep"),
      h("p", {}, "This usually takes a few minutes, and you can close this panel meanwhile. A brief is kept only if it passes the assay."));
  }
  if (result.state === "failed") {
    return h("div", { class: "callout bad" }, h("strong", {}, `Last interview prep failed, ${ago(result.at)}`), detail);
  }
  return h("div", { class: "callout" }, h("strong", {}, `Interview prep written ${ago(result.at)}`), detail,
    h("p", { class: "muted" }, "Read it against what you remember. The assay catches invented numbers and terms, not a true fact framed misleadingly."));
}

// What the web says about how the employer works, which every job there shares, and where to read reviews yourself.
// Built like an industry's outlook: every point links the source the research run found it in.
function culturePart(job) {
  const c = job.culture;
  const links = job.culture_links || [];
  if (!c && !links.length) return null;
  const report = c && c.report;
  const running = researching(job);
  const error = h("p", { class: "error", role: "alert" });
  const start = c ? h("button", { class: "btn", type: "button", disabled: running || inDemo(), title: demoTitle(), onclick: async () => {
    start.disabled = true;
    try {
      await api(`/api/job/${job.id}/culture`, {});
      await openJob(job.id);
    } catch (err) {
      error.textContent = err.message;
      start.disabled = false;
    }
  } }, running ? "Researching…" : report ? "Research again" : "Research with Claude") : null;
  let line;
  if (running) line = `Searching the web, started ${ago(c.started_at)}. This takes a few minutes, and you can close this panel meanwhile.`;
  else if (c && c.state === "failed") line = h("span", { class: "alert" }, `The last try didn't finish: ${c.detail}${report ? " The research below is the one before it." : ""}`);
  else if (report) line = `Researched ${ago(report.generated_at)}${c.stale ? ", so it may be out of date" : ""}. Every job at ${job.company} shares it, and tailoring sums it up in the notes.`;
  else if (c) line = "Claude searches the web for how this employer works: process, performance reviews, layoffs and its labor record. Every point links its source. Each run uses your Claude plan for a few minutes.";
  const sources = report ? new Map(report.sources.map((s) => [s.n, s])) : new Map();
  const cite = (n) => {
    const source = sources.get(n);
    const href = source && safeHref(source.url);
    return href ? h("a", { class: "cite", href, target: "_blank", rel: "noopener noreferrer", title: source.title }, `[${n}]`) : null;
  };
  const dropped = report ? report.dropped.points : 0;
  const empty = report ? report.nothing_found || [] : [];
  return h("div", { class: "outlook" },
    h("h3", {}, "Employer"),
    start ? h("div", { class: "outlook-head" }, start, h("span", { class: "muted" }, line)) : null,
    error,
    report ? [
      report.sections.map((section) => [
        h("h4", {}, section.heading),
        h("ul", {}, section.points.map((point) => h("li", {}, point.text, point.sources.map(cite)))),
      ]),
      empty.length ? h("p", { class: "info-note" }, `Found nothing on: ${empty.join(", ")}. That means nothing turned up, not that the record is clean.`) : null,
      report.sources.length ? h("details", { class: "outlook-sources" }, h("summary", {}, `Sources (${report.sources.length})`),
        h("ol", {}, report.sources.map((s) => h("li", { value: String(s.n) },
          safeHref(s.url) ? h("a", { href: safeHref(s.url), target: "_blank", rel: "noopener noreferrer" }, s.title) : s.title,
          [s.publisher, s.date].filter(Boolean).length ? h("span", { class: "muted" }, ` · ${[s.publisher, s.date].filter(Boolean).join(", ")}`) : null)))) : null,
      h("p", { class: "info-note" }, "Written by Claude from a web search. Pyrite kept only points whose sources came up in that search",
        dropped ? `, and dropped ${plural(dropped, "point")} that didn't` : "",
        ". It can't tell whether a page says what a point claims, so open the source before relying on it."),
    ] : null,
    links.length ? h("p", { class: "muted" }, "Read reviews yourself, since review sites don't allow automated reading: ",
      links.flatMap((link, i) => [i ? " · " : "", h("a", { href: safeHref(link.url), target: "_blank", rel: "noopener noreferrer" }, link.name)])) : null);
}

// Reopening would wipe anything being typed in the panel, so only do it once the result is in.
async function watchRefresh(id) {
  if (openJobId !== id) return;
  try {
    const job = await api(`/api/job/${id}`);
    if (!working(job)) {
      await refresh();
      if (openJobId === id) await openJob(id);
      return;
    }
  } catch (err) {
    // The dashboard may be restarting, so keep waiting.
  }
  refreshWatch = setTimeout(() => watchRefresh(id), 5000);
}

// Today in this computer's time zone, as a date input wants it.
function localToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// Logs a note or message about a sent application. Each one shows in the timeline, and the follow-up reminder moves to a week after it.
function outreachBlock(job) {
  if (!job.can_reach_out) return null;
  const today = localToday();
  const day = h("input", { type: "date", max: today, "aria-label": "Day you reached out" });
  keepDraft(job.id, "outreachDay", day, today);
  const to = h("input", { placeholder: "Who, such as the hiring manager (optional)", "aria-label": "Who you reached out to", maxlength: "120" });
  keepDraft(job.id, "outreachTo", to, "");
  const note = h("input", { placeholder: "What you sent or asked (optional)", "aria-label": "Note about reaching out", maxlength: String(LIMITS.note) });
  keepDraft(job.id, "outreachNote", note, "");
  const said = job.reached_out
    ? "Logged in the timeline. Log each note you send, such as a follow-up."
    : "A short note to the hiring manager within a few days of applying. Logging it moves the follow-up reminder to a week after it.";
  return h("div", {}, h("h3", {}, "Reaching out"), h("p", { class: "muted" }, said),
    h("div", { class: "stack" }, to, note, h("div", { class: "row" }, day,
      h("button", { class: "btn", type: "button",
        onclick: () => tryAct(job.id, { action: "reached_out", date: day.value, to: to.value, note: note.value }, "Couldn't log that",
          ["outreachDay", "outreachTo", "outreachNote"]) }, "Reached out"))));
}

// `list` is the order of the list it was opened from, for Previous, Next and moving on after a pass. Returns whether
// the job could be opened.
async function openJob(id, list) {
  let job;
  try {
    job = await api(`/api/job/${id}`);
  } catch (err) {
    return false;
  }
  if (list) nav = list;
  else if (!nav.includes(id)) nav = [];
  // What had focus is noted before marking the job seen, which redraws the list it was opened from.
  const wasOpen = !$("drawer").hidden;
  if (!wasOpen) {
    drawerOpener = document.activeElement;
    hashBeforeJob = tabAddress();
  }
  if (job.status === "new" && !job.seen && !state.demo) markSeen(id);
  openJobId = id;
  // The address names the job while its panel is open, so it can be bookmarked or linked from a note.
  if (location.hash !== `#job-${id}`) history.replaceState(null, "", `#job-${id}`);
  clearTimeout(refreshWatch);
  if (working(job)) refreshWatch = setTimeout(() => watchRefresh(id), 5000);
  const noteEl = h("input", { placeholder: "Add a note to this update (optional)", "aria-label": "Note for this update", style: "width:100%",
    maxlength: String(LIMITS.note) });
  keepDraft(id, "update", noteEl, "");
  const notesStatus = h("span", { class: "muted part-status", role: "status" });
  const notesEl = h("textarea", { rows: 3, "aria-label": "Your notes", maxlength: String(LIMITS.notes) });
  keepDraft(id, "notes", notesEl, job.notes || "", notesStatus);
  const nextStatus = h("span", { class: "muted part-status", role: "status" });
  const nextText = h("input", { placeholder: "e.g. Phone screen with the hiring manager", "aria-label": "Next step", maxlength: String(LIMITS.nextStep) });
  keepDraft(id, "nextText", nextText, job.next_action || "");
  const nextDate = h("input", { type: "date", "aria-label": "Next step date" });
  keepDraft(id, "nextDate", nextDate, job.next_action_date || "");
  // The text and the date save together, so either one unsaved shows on the one status.
  const nextUnsaved = () => {
    nextStatus.textContent = nextText.value !== (job.next_action || "") || nextDate.value !== (job.next_action_date || "") ? "Not saved yet" : "";
  };
  [nextText, nextDate].forEach((el) => el.addEventListener("input", nextUnsaved));
  nextUnsaved();
  const href = safeHref(job.url);

  const facts = [["Status", job.status.replaceAll("_", " ")], ["Location", job.location || "Not stated"], ["Pay", job.comp],
    ["Track", job.track], ["Fit", job.fit ? `${capitalized(job.fit)}: ${job.fit_reason}` : ""], ["Found", shortDate(job.first_seen)],
    ["Posted", job.posted_at ? shortDate(job.posted_at) : ""],
    ["First posted", job.first_posted_at && job.first_posted_at !== job.posted_at ? `${shortDate(job.first_posted_at)} (${daysAgo(job.age_days)})` : ""],
    ["Listed for", !job.first_posted_at || job.first_posted_at === job.posted_at ? (job.age_days === null ? "" : job.age_days === 0 ? "Posted today" : plural(job.age_days, "day")) : ""],
    ["Reposted", job.reposts ? `${job.reposts} time${job.reposts > 1 ? "s" : ""}${job.last_reposted_at ? `, last ${shortDate(job.last_reposted_at)}` : ""}` : ""],
    ["Re-dated", job.redates ? `${job.redates} time${job.redates > 1 ? "s" : ""}` : ""],
    ["Applied", job.applied_at ? `${shortDate(job.applied_at)} (${daysAgo(job.days_since_applied)})` : ""],
    ["Heard back", job.response_at ? shortDate(job.response_at) : ""]].filter(([, value]) => value);

  fill($("drawer"),
    h("div", { class: "drawer-head" },
      stageIcon(STAGE_ICONS[job.status], 48, "drawer-stage"),
      h("div", { class: "drawer-title" }, h("h2", {}, job.title), h("p", { class: "muted" }, job.company, " · ",
        h("span", { class: "job-number", title: `The number pyrite commands take, as in pyrite status ${job.id}` }, `Job ${job.id}`))),
      h("button", { class: "btn", type: "button", onclick: closeDrawer }, "Close")),
    navBar(id),
    // In the order you apply: what could stop you, the posting and the files to upload, whether the check still holds, then the buttons.
    beforeApplyBlock(job),
    job.posting_closed_at ? h("div", { class: "callout bad" }, `This posting came down around ${shortDate(job.posting_closed_at)}.`) : null,
    job.ghost_risk ? h("div", { class: "callout bad" }, h("strong", {}, "Possible ghost job"),
      h("p", {}, `${capitalized(job.ghost_reason)}. A prompt to look closer, not proof: some companies keep real openings up all year. Consider asking a recruiter whether it's actively being filled.`)) : null,
    applyRow(job, href),
    h("div", { id: "refresh-error" }),
    autofillBlock(job),
    replyBlock(job),
    frozenBlock(job),
    changedBlock(job),
    stuckBlock(job),
    beforeSendBlock(job),
    h("div", { class: "stack" }, noteEl, h("div", { class: "row" }, actionButtons(job, noteEl))),
    checkBlock(job),
    toolsRow(job),
    refreshBlock(job),
    prepBlock(job),
    job.may_be_repost ? h("div", { class: "callout" }, "This Workday link ends in -1 or similar, which often means the requisition has more than one posting. It may have been posted before. This is only a hint, and it doesn't affect priority.") : null,
    freshnessPills(job).length ? h("div", { class: "signals" }, freshnessPills(job)) : null,
    h("dl", { class: "facts" }, facts.flatMap(([key, value]) => [h("dt", {}, key), h("dd", {}, value)])),
    (job.flags.length ? h("div", { class: "callout" }, `Flagged: ${job.flags.join(", ")}`) : null),
    readBlock(job),
    relocationBlock(job),
    h("div", {}, h("h3", {}, "Next step"), h("div", { class: "stack" }, nextText,
      h("div", { class: "row" }, nextDate, h("button", { class: "btn", type: "button",
        onclick: () => tryAct(job.id, { action: "next_action", text: nextText.value, date: nextDate.value }, undefined, ["nextText", "nextDate"]) }, "Save"),
      nextStatus))),
    outreachBlock(job),
    h("div", {}, h("h3", {}, "Your notes"), h("div", { class: "stack" }, notesEl, h("div", { class: "row" },
      h("button", { class: "btn", type: "button", onclick: () => tryAct(job.id, { action: "note", notes: notesEl.value }, undefined, ["notes"]) }, "Save notes"),
      notesStatus))),
    job.notes_md ? h("div", {}, h("h3", {}, "Fit and interview notes"), h("div", { class: "prose markdown" }, markdown(job.notes_md))) : null,
    culturePart(job),
    job.score_reasons.length ? h("div", {}, h("h3", {}, `Why it scored ${job.score}`), h("p", { class: "muted" }, job.score_reasons.join(" · "))) : null,
    job.freshness_reasons.length ? h("div", {}, h("h3", {}, `Why its priority is ${job.rank}`), h("p", { class: "muted" }, [`Score ${job.score}`, ...job.freshness_reasons].join(" · "))) : null,
    job.description ? h("div", {}, h("h3", {}, "Posting"), h("div", { class: "prose" }, job.description)) : null,
    h("div", {}, h("h3", {}, "Timeline"), h("ul", { class: "timeline" }, job.events.map((e) => h("li", {},
      h("time", {}, shortDate(e.ts)), e.kind.replaceAll("_", " "), e.detail ? h("span", { class: "detail" }, e.detail) : null)))),
  );
  $("drawer").hidden = false;
  $("scrim").hidden = false;
  // The panel is a dialog: the page behind it can't be clicked or tabbed to until it closes.
  pageBehind().forEach((el) => { el.inert = true; });
  $("drawer").scrollTop = 0;
  // Focus goes into the panel so the keyboard shortcuts and Tab start there, not on the page behind it.
  if (!wasOpen || !$("drawer").contains(document.activeElement)) $("drawer").focus();
  return true;
}

// The first time you open a prospect. It's only a marker for the Prospects tab, so a failure is ignored.
function markSeen(id) {
  api(`/api/job/${id}/action`, { action: "seen" }).catch(() => {});
  const job = state.jobs.find((j) => j.id === id);
  if (job) {
    job.seen = true;
    renderRadar();
  }
}

// J and K step through the list, T tailors and P passes, as long as you aren't typing in a box.
function drawerKeys(e) {
  if (!openJobId || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  const key = e.key.toLowerCase();
  const at = nav.indexOf(openJobId);
  if ((key === "j" || key === "k") && at >= 0) {
    const to = nav[at + (key === "j" ? 1 : -1)];
    if (to !== undefined) openJob(to);
    e.preventDefault();
    return;
  }
  if (key !== "p" && key !== "t") return;
  const job = state.jobs.find((j) => j.id === openJobId);
  // Only before anything is written: a ready draft is passed on with the button, never a stray key.
  if (!job || !["new", "shortlisted", "needs_fix"].includes(job.status)) return;
  e.preventDefault();
  triage(job, key === "p" ? "pass" : "tailor_next", true);
}

// With no panel open, J and K move down and up the list on show: To do's items, the board's cards, or the rows of
// Prospects and Closed. Enter then opens the one you're on, as a click would.
const LIST_ITEMS = {
  todo: "#orders button.order",
  pipeline: "#board .card",
  radar: "#view-radar tr[data-id] .linkish",
  archive: "#view-archive tr[data-id] .linkish",
};

function listKeys(e) {
  const key = e.key.toLowerCase();
  if ((key !== "j" && key !== "k") || openJobId || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return false;
  const view = document.querySelector(".view:not([hidden])");
  const selector = view && LIST_ITEMS[view.id.replace("view-", "")];
  if (!selector) return false;
  // Only what can be seen: a folded group's items are skipped.
  const items = [...document.querySelectorAll(selector)].filter((el) => el.offsetParent !== null);
  if (!items.length) return false;
  const at = items.indexOf(document.activeElement);
  const to = at < 0 ? (key === "j" ? 0 : items.length - 1) : Math.min(Math.max(at + (key === "j" ? 1 : -1), 0), items.length - 1);
  e.preventDefault();
  items[to].focus();
  items[to].scrollIntoView({ block: "nearest" });
  return true;
}

// ---- Go to ----
// Ctrl+K, or ⌘K on a Mac, opens a box that finds a job, a view, a section of Profile or Settings, or one of the top
// bar's actions by a few letters of its name, and goes there.

const ON_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const PALETTE_SHOWN = 40;
let paletteHits = [];
let paletteAt = 0;
let paletteFrom = null;

const statusName = (status) => {
  const column = COLUMNS.find((c) => c.statuses.includes(status));
  if (column) return column.title;
  return status === "new" ? "Prospect" : capitalized(String(status || "").replaceAll("_", " "));
};

// Everything the box can go to. A button the top bar can't press now, such as a run that's going, is left out.
function paletteEntries() {
  const entries = tabs.map((tab) => ({ kind: "View", label: tab.querySelector(".rail-label").textContent, go: () => showTab(tabTarget(tab)) }));
  state.funnel.filter((f) => f.stage !== "Prospects").forEach((f, index) => entries.push({
    kind: "View", label: f.stage, where: `Pipeline, ${plural(f.count, "job")}`, go: () => { showTab("pipeline"); showColumn(index); } }));
  (state.places || []).forEach((p) => entries.push({ kind: "Section", label: p.label, where: p.where, go: () => showTab(p.tab) }));
  const actions = [["add-open"], ["run-sweep", "Reads the job boards and checks mail"], ["run-claude", "Judges new postings and tailors the best"],
    ["update-open"], ["setup-open"]];
  for (const [id, where] of actions) {
    const button = $(id);
    if (button && !button.hidden && !button.disabled) entries.push({ kind: "Action", label: button.textContent.trim(), where, go: () => button.click() });
  }
  entries.push({ kind: "Action", label: "Search prospects", where: "Or press /", go: () => { showTab("radar"); $("radar-search").focus(); } });
  // Jobs most worth your time first, so a short search lands on the one you mean.
  [...state.jobs].sort((a, b) => (b.rank || 0) - (a.rank || 0)).forEach((job) => entries.push({
    kind: "Job", label: `${job.company}: ${job.title}`, where: statusName(job.status), also: `${job.status} ${job.location || ""}`,
    job: job.id, go: () => openJob(job.id) }));
  return entries;
}

// Every word typed has to start a word of the entry's name or where it is, in any order: for a job, that's its stage,
// its status and its place. One that starts the name itself counts for most. With nothing typed, the views, sections
// and actions show, and jobs wait for a search.
function paletteMatch(entries, query) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return entries.filter((e) => e.kind !== "Job");
  const order = { View: 0, Section: 1, Action: 2, Job: 3 };
  const scored = [];
  entries.forEach((entry, index) => {
    const name = entry.label.toLowerCase();
    const starts = ` ${name} ${entry.where || ""} ${entry.also || ""}`.toLowerCase().replace(/[^a-z0-9\s]+/g, " ");
    if (!words.every((w) => starts.includes(` ${w}`) || name.includes(w))) return;
    const points = (name.startsWith(words[0]) ? 4 : 0) + words.filter((w) => ` ${name}`.includes(` ${w}`)).length;
    scored.push({ entry, points, index });
  });
  scored.sort((a, b) => b.points - a.points || order[a.entry.kind] - order[b.entry.kind] || a.index - b.index);
  return scored.map((s) => s.entry);
}

function renderPalette() {
  const query = $("palette-input").value;
  paletteHits = paletteMatch(paletteEntries(), query).slice(0, PALETTE_SHOWN);
  paletteAt = Math.min(paletteAt, Math.max(paletteHits.length - 1, 0));
  fill($("palette-list"), paletteHits.length ? paletteHits.map((entry, index) => h("li", {
    id: `palette-${index}`, role: "option", class: "palette-hit", "aria-selected": String(index === paletteAt), "data-index": String(index),
    onclick: () => paletteGo(index) },
  h("span", { class: `palette-kind kind-${entry.kind.toLowerCase()}` }, entry.kind),
  h("span", { class: "palette-label" }, entry.label),
  entry.where ? h("span", { class: "palette-where" }, entry.where) : null))
    : h("li", { class: "palette-none" }, `Nothing goes by “${query.trim()}”.`));
  markPalette();
}

function markPalette() {
  $("palette-list").querySelectorAll(".palette-hit").forEach((li, index) => li.setAttribute("aria-selected", String(index === paletteAt)));
  const active = $(`palette-${paletteAt}`);
  if (active) {
    $("palette-input").setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  } else $("palette-input").removeAttribute("aria-activedescendant");
}

function openPalette() {
  if (!state || document.querySelector("dialog[open]")) return;
  paletteFrom = document.activeElement;
  paletteAt = 0;
  $("palette-input").value = "";
  renderPalette();
  $("palette").showModal();
  $("palette-input").focus();
}

function paletteGo(index) {
  const entry = paletteHits[index];
  if (!entry) return;
  paletteFrom = null;
  $("palette").close();
  // A view or an action belongs to the page behind the job panel, so the panel closes first. A job opens in it.
  if (openJobId && !entry.job) closeDrawer();
  entry.go();
}

// What the job panel covers while it's open.
function pageBehind() {
  return [document.querySelector(".rail"), document.querySelector(".topbar"), document.querySelector("main")].filter(Boolean);
}

function closeDrawer() {
  const closed = openJobId;
  openJobId = null;
  $("drawer").hidden = true;
  $("scrim").hidden = true;
  pageBehind().forEach((el) => { el.inert = false; });
  // Back to the tab's own address, as it was before the panel opened.
  if (/^#job-\d+$/.test(location.hash)) history.replaceState(null, "", hashBeforeJob || location.pathname + location.search);
  hashBeforeJob = "";
  // A pass or a refresh may have redrawn the list it came from. Then the job's row in the redrawn list takes focus, if
  // it's still there, such as a prospect marked seen when it opened.
  const row = closed === null ? null : document.querySelector(`tr[data-id="${closed}"] .linkish`);
  if (drawerOpener && drawerOpener.isConnected) drawerOpener.focus();
  else if (row && drawerOpener && drawerOpener.closest("tr[data-id]")) row.focus();
  drawerOpener = null;
}

// ---- Industries ----
// What Pyrite has seen, the official numbers and Claude's sourced outlook, for each industry under [promote].

let industryData = null;
let industriesLoading = false;
let industriesWatch = null;
const industriesOpen = new Set();

const quarterName = (q) => (q ? q.replace("Q", " Q") : "");
const money = (n) => (n ? `$${n.toLocaleString()}` : "–");

function percent(n) {
  if (n === null || n === undefined) return h("span", { class: "muted" }, "–");
  const tone = n > 0 ? "up" : n < 0 ? "down" : "";
  return h("span", { class: tone }, `${n > 0 ? "+" : ""}${n.toFixed(1)}%`);
}

async function loadIndustries() {
  if (industriesLoading) return;
  industriesLoading = true;
  if (!industryData) fill($("industries-view"), h("p", { class: "muted" }, "Reading the official numbers. The first time takes a few seconds."));
  try {
    industryData = await api("/api/industries");
    renderIndustries();
    $("industries-error").textContent = "";
  } catch (err) {
    $("industries-error").textContent = err.message;
  } finally {
    industriesLoading = false;
  }
  // While an outlook is being written, look again now and then, until it's done or you've moved to another tab.
  clearTimeout(industriesWatch);
  if (industryData && industryData.industries.some((i) => i.outlook.state === "running")) {
    industriesWatch = setTimeout(() => { if (!$("view-industries").hidden) loadIndustries(); }, 8000);
  }
}

function seenPart(industry, since) {
  const s = industry.seen;
  const tile = (value, label, sub) => h("div", { class: "kpi" },
    h("span", { class: "value" }, value), h("span", { class: "label" }, label), h("span", { class: "sub" }, sub));
  const days = since ? Math.floor((Date.now() - toDate(since).getTime()) / 864e5) : null;
  return [
    h("h3", { class: "info-heading" }, "In your search"),
    h("div", { class: "info-tiles" },
      tile(s.recent, "Postings in 90 days", [`${s.by_month[0]} in the last 30 days`, s.share !== null ? `${s.share}% of all kept` : ""].filter(Boolean).join(", ")),
      tile(s.open, "Still listed", "Not yet taken down by the employer"),
      tile(`${s.local} / ${s.remote}`, "Local / remote", "Of the last 90 days"),
      tile(s.applied, "Applied", s.applied ? `${s.replied} replied, ${s.interviews} interviewed${s.offers ? `, ${s.offers} offered` : ""}` : "None yet")),
    s.employers.length ? h("div", { class: "info-row" }, h("span", { class: "muted" }, "Posting most:"),
      s.employers.map(([name, count]) => pill("info", count > 1 ? `${name} ×${count}` : name, `${plural(count, "posting")} in the last 90 days`))) : null,
    h("p", { class: "info-note" }, "Postings that passed your filters and count as this industry, judged the way your preferred industries are.",
      days !== null && days < 90 ? ` Pyrite has only been watching since ${shortDate(since)}, so the 90 days aren't full yet.` : ""),
  ];
}

function officialRow(area) {
  const name = h("td", {}, area.name);
  if (area.error) return h("tr", {}, name, h("td", { class: "gap", colspan: "7" }, area.error));
  const workplaces = area.estabs === undefined ? h("td", { class: "num gap" }, "–")
    : h("td", { class: "num" }, area.estabs.toLocaleString(),
      area.estabs_change ? h("span", { class: area.estabs_change > 0 ? "up" : "down" }, ` ${area.estabs_change > 0 ? "+" : ""}${area.estabs_change}`) : null);
  if (area.jobs === undefined || area.jobs === null) {
    return h("tr", {}, name, h("td", {}, quarterName(area.quarter)),
      h("td", { class: "gap", colspan: "2" }, area.withheld && area.withheld.length ? "Withheld" : "Not on record"),
      workplaces,
      h("td", { class: "gap", colspan: "3" }, area.withheld && area.withheld.length
        ? "Jobs and pay are withheld here, since they would reveal individual employers. Workplace counts are still published."
        : "None of these codes has a published figure here."));
  }
  return h("tr", {},
    name,
    h("td", {}, quarterName(area.quarter)),
    h("td", { class: "num" }, area.jobs.toLocaleString()),
    h("td", { class: "num" }, percent(area.jobs_change_pct)),
    workplaces,
    h("td", { class: "num" }, money(area.weekly_pay), " ", percent(area.pay_change_pct)),
    h("td", { class: "num" }, area.pay_vs_all ? `${area.pay_vs_all}%` : "–"),
    h("td", { class: "num" }, area.concentration ? area.concentration.toFixed(2) : "–"));
}

function officialPart(industry, about) {
  const heading = h("h3", { class: "info-heading" }, "Official numbers");
  if (!industry.codes.length) {
    return [heading, h("p", { class: "muted" }, "Add this industry's codes (NAICS) under Settings, in Cities and industries, to see official employment, pay and growth here. ",
      h("a", { href: "https://www.census.gov/naics/", target: "_blank", rel: "noopener" }, "Look up codes at census.gov"), ".")];
  }
  const partial = industry.official.filter((a) => a.jobs !== undefined && a.jobs !== null && ((a.withheld || []).length || (a.absent || []).length));
  return [
    heading,
    h("p", { class: "info-codes" }, "Counts ", industry.codes.map((c, i) => [i ? "; " : "", h("span", { class: "code" }, c.code), c.title ? ` ${c.title}` : ""])),
    industry.official.length ? h("div", { class: "table-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {},
        h("th", {}, "Area"), h("th", {}, "Quarter"),
        h("th", { class: "num", title: "Private-sector jobs in the last month of the quarter" }, "Jobs"),
        h("th", { class: "num", title: "Change in jobs from the same month a year before" }, "Over a year"),
        h("th", { class: "num", title: "Establishments: each work site counts once, so one employer can have several. The signed number is the change over a year." }, "Workplaces"),
        h("th", { class: "num", title: "Average weekly pay, and its change over a year. A first quarter includes annual bonuses." }, "Weekly pay"),
        h("th", { class: "num", title: "This industry's average pay as a share of the average for all private jobs in the same area" }, "Vs all jobs"),
        h("th", { class: "num", title: "Location quotient: above 1 means this industry is a bigger share of jobs here than across the country" }, "Concentration"))),
      h("tbody", {}, industry.official.map(officialRow)))) : null,
    partial.map((a) => h("p", { class: "info-note" }, `${a.name}: ${[
      (a.withheld || []).length ? `${a.withheld.join(", ")} withheld to protect individual employers` : "",
      (a.absent || []).length ? `no ${a.absent.join(", ")} employers on record` : "",
    ].filter(Boolean).join("; ")}, so the figures above leave them out.`)),
    industry.official.filter((a) => a.note).map((a) => h("p", { class: "info-note" }, `${a.name}: ${a.note}`)),
    h("p", { class: "info-note" }, "Private employers only, from the BLS ",
      h("a", { href: about, target: "_blank", rel: "noopener" }, "Quarterly Census of Employment and Wages"),
      ", which counts nearly every job from employers' unemployment insurance filings. It runs five to six months behind, and a metro area's industry detail comes out later than a state's. Industry codes are broad, so a code can include work well outside what you mean by the industry."),
  ];
}

function outlookPart(industry) {
  const o = industry.outlook;
  const running = o.state === "running";
  const report = o.report;
  const error = h("p", { class: "error", role: "alert" });
  const start = h("button", { class: "btn", type: "button", disabled: running || inDemo(), title: demoTitle(), onclick: async () => {
    start.disabled = true;
    try {
      await api("/api/industries/outlook", { name: industry.name });
      await loadIndustries();
    } catch (err) {
      error.textContent = err.message;
      start.disabled = false;
    }
  } }, running ? "Researching…" : report ? "Research again" : "Research with Claude");
  let line;
  if (running) line = `Searching the web, started ${ago(o.started_at)}. This takes a few minutes.`;
  else if (o.state === "failed") line = h("span", { class: "alert" }, `The last try didn't finish: ${o.detail}${report ? " The outlook below is the one before it." : ""}`);
  else if (report) line = `Researched ${ago(report.generated_at)}${report.area ? ` for ${[report.area.metro, report.area.state, report.area.country].filter(Boolean).join(", ")}` : ""}.`;
  else line = "Claude searches the web for this industry's news where you live, and every point links its source. Each run uses your Claude plan for a few minutes.";
  const sources = report ? new Map(report.sources.map((s) => [s.n, s])) : new Map();
  const cite = (n) => {
    const source = sources.get(n);
    const href = source && safeHref(source.url);
    return href ? h("a", { class: "cite", href, target: "_blank", rel: "noopener noreferrer", title: source.title }, `[${n}]`) : null;
  };
  const dropped = report ? report.dropped.points : 0;
  return h("div", { class: "outlook" },
    h("h3", { class: "info-heading" }, "Outlook"),
    h("div", { class: "outlook-head" }, start, h("span", { class: "muted" }, line)),
    error,
    report ? [
      report.sections.map((section) => [
        h("h4", {}, section.heading),
        h("ul", {}, section.points.map((point) => h("li", {}, point.text,
          point.scope ? pill("muted", point.scope, "Which area this point is about") : null,
          point.sources.map(cite)))),
      ]),
      h("details", { class: "outlook-sources" }, h("summary", {}, `Sources (${report.sources.length})`),
        h("ol", {}, report.sources.map((s) => h("li", { value: String(s.n) },
          safeHref(s.url) ? h("a", { href: safeHref(s.url), target: "_blank", rel: "noopener noreferrer" }, s.title) : s.title,
          [s.publisher, s.date].filter(Boolean).length ? h("span", { class: "muted" }, ` · ${[s.publisher, s.date].filter(Boolean).join(", ")}`) : null)))),
      h("p", { class: "info-note" }, "Written by Claude from a web search. Pyrite kept only points whose sources came up in that search",
        dropped ? `, and dropped ${plural(dropped, "point")} that didn't` : "",
        ". It can't tell whether a page says what a point claims, so open the source before relying on it."),
    ] : null);
}

function industrySummary(industry) {
  const s = industry.seen;
  const local = industry.official.find((a) => a.jobs_change_pct !== undefined && a.jobs_change_pct !== null);
  const o = industry.outlook;
  return [
    plural(s.recent, "posting") + " in 90 days",
    local ? `${local.name.replace(/ MSA$/, "")} jobs ${local.jobs_change_pct > 0 ? "+" : ""}${local.jobs_change_pct.toFixed(1)}% over a year` : null,
    o.state === "running" ? "Researching…" : o.report ? `Outlook from ${shortDate(o.report.generated_at)}` : null,
  ].filter(Boolean).join(" · ");
}

function renderIndustries() {
  const data = industryData;
  const view = $("industries-view");
  if (!data.industries.length) {
    return fill(view, h("p", { class: "muted" }, "You don't follow any industries yet. Add them under Settings, in Cities and industries, and they'll show here."));
  }
  const m = data.market;
  const place = [m.metro, m.state, m.us ? "the United States" : null].filter(Boolean).join(", ");
  fill(view,
    h("div", { class: "settings-intro" },
      h("p", { class: "muted" }, `How each industry you follow is doing${place ? ` in ${place}` : ""}: what Pyrite has seen, the official employment numbers, and an outlook Claude researches when you ask.`),
      h("button", { class: "btn", type: "button", onclick: loadIndustries }, "Reload")),
    data.problems.map((problem) => h("p", { class: "alert" }, problem)),
    m.us && !m.metro && !m.state ? h("p", { class: "muted" }, "To see local numbers beside the national ones, add your state and metro area under [market] in profile/search.toml.") : null,
    data.industries.map((industry, index) => {
      const root = h("details", { class: "panel industry", open: industriesOpen.has(industry.name) || (!industriesOpen.size && index === 0) },
        h("summary", {}, h("span", { class: "industry-name" }, industry.name), h("span", { class: "muted" }, industrySummary(industry))),
        seenPart(industry, data.watching_since),
        officialPart(industry, data.about),
        outlookPart(industry));
      if (root.open) industriesOpen.add(industry.name);
      root.addEventListener("toggle", () => { if (root.open) industriesOpen.add(industry.name); else industriesOpen.delete(industry.name); });
      return root;
    }));
}

// ---- Wiring ----

// The views are named in the rail. Each is still called a tab in the code and the address, as it was.
const tabs = [...document.querySelectorAll(".rail-nav button[data-tab]")];

// The tab you're on is in the address, so a reload or a bookmark comes back to it. On the Profile and Settings tabs
// so is the section, as #profile/achievements or #settings/mail.
function showTab(name, focus = false) {
  const [base, ...rest] = String(name || "").split("/");
  const tab = tabs.find((t) => t.dataset.tab === base) || tabs[0];
  tabs.forEach((b) => {
    if (b === tab) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  // A new view starts at its top, as a new page would.
  const arriving = Boolean(document.querySelector(`#view-${tab.dataset.tab}[hidden]`));
  if (arriving) window.scrollTo(0, 0);
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== `view-${tab.dataset.tab}`; });
  if (focus) tab.focus();
  const section = tab.dataset.tab === "profile" ? profileShow(rest.join("/"))
    : tab.dataset.tab === "settings" ? settingsShow(rest.join("/")) : "";
  const hash = tab === tabs[0] ? "" : `#${tab.dataset.tab}${section ? `/${section}` : ""}`;
  // While a job's panel is open the address is the job's, and the tab's waits for the panel to close.
  if (openJobId) hashBeforeJob = hash;
  else if (location.hash !== hash) history.replaceState(null, "", hash || location.pathname + location.search);
  // Settings loads when you come to it, not on each move between its sections, and never over edits you haven't saved.
  if (tab.dataset.tab === "settings" && !dirtyParts.size && (arriving || !settings)) loadSettings();
  if (tab.dataset.tab === "facts" && !factsOpen) loadFacts();
  if (tab.dataset.tab === "industries") loadIndustries();
}

// Coming back to the Profile or Settings tab returns to the section you left it on.
const tabTarget = (tab) => {
  const at = { profile: profileAt, settings: settingsAt }[tab.dataset.tab];
  return at ? `${tab.dataset.tab}/${at}` : tab.dataset.tab;
};

// The address of the tab on show, as showTab writes it, for when a job's panel closes over it.
function tabAddress() {
  const tab = tabs.find((t) => t.getAttribute("aria-current") === "page") || tabs[0];
  return tab === tabs[0] ? "" : `#${tabTarget(tab)}`;
}
tabs.forEach((tab) => tab.addEventListener("click", () => showTab(tabTarget(tab))));
// The arrow keys move up and down the rail, or along it where a narrow screen lays it across the top.
document.querySelector(".rail-nav").addEventListener("keydown", (e) => {
  const at = tabs.indexOf(document.activeElement);
  if (at < 0) return;
  const to = { ArrowDown: at + 1, ArrowRight: at + 1, ArrowUp: at - 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  tabs[(to + tabs.length) % tabs.length].focus();
});
$("status").addEventListener("click", () => toggleStatus());
// The status details close on Escape or a click anywhere else, as a menu would.
document.addEventListener("click", (e) => { if (!$("status-pop").hidden && !e.target.closest(".status-wrap")) toggleStatus(false); });
// #job-56 opens job 56's panel over the tab you're on. Anything else is a tab.
const jobInAddress = () => Number((location.hash.match(/^#job-(\d+)$/) || [])[1]) || null;

async function followAddress() {
  const id = jobInAddress();
  if (!id) {
    if (openJobId) closeDrawer();
    showTab(location.hash.slice(1));
  } else if (id !== openJobId && !await openJob(id)) {
    showTab("");  // No such job, so the address goes back to the first tab rather than naming it.
  }
}

window.addEventListener("hashchange", followAddress);
window.addEventListener("beforeunload", (e) => { if (dirtyParts.size || factsOpen || drafts.size || profilePending) e.preventDefault(); });
$("radar-search").addEventListener("input", renderRadar);
["archive-search", "archive-outcome"].forEach((id) => $(id).addEventListener("input", renderArchive));
RADAR_FILTERS.forEach((id) => $(id).addEventListener("input", () => { saveRadarFilters(); renderRadar(); }));
$("scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  // Go to opens from anywhere, a box you're typing in included, but never over another dialog.
  if ((ON_MAC ? e.metaKey : e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if ($("palette").open) $("palette").close();
    else openPalette();
    return;
  }
  // A dialog on top handles its own keys, Escape included.
  if (document.querySelector("dialog[open]")) return;
  if (listKeys(e)) return;
  if (e.key === "Escape" && openJobId) closeDrawer();
  else if (e.key === "Escape" && !$("status-pop").hidden) {
    toggleStatus(false);
    $("status").focus();
  } else if (e.key === "/" && !openJobId && !e.ctrlKey && !e.metaKey && !e.altKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) {
    e.preventDefault();
    showTab("radar");
    $("radar-search").focus();
    $("radar-search").select();
  } else drawerKeys(e);
});

$("palette-open").addEventListener("click", openPalette);
$("palette-keys").textContent = ON_MAC ? "⌘K" : "Ctrl K";
$("palette-open").title = `Find a job, a view or an action by name. ${ON_MAC ? "⌘K" : "Ctrl+K"} from anywhere`;
$("palette-open").setAttribute("aria-keyshortcuts", ON_MAC ? "Meta+K" : "Control+K");
$("palette-input").addEventListener("input", () => { paletteAt = 0; renderPalette(); });
$("palette-input").addEventListener("keydown", (e) => {
  const step = { ArrowDown: 1, ArrowUp: -1 }[e.key];
  if (step && paletteHits.length) {
    e.preventDefault();
    paletteAt = (paletteAt + step + paletteHits.length) % paletteHits.length;
    markPalette();
  } else if (e.key === "Enter") {
    e.preventDefault();
    paletteGo(paletteAt);
  }
});
// The pointer chooses as the arrow keys do.
$("palette-list").addEventListener("mousemove", (e) => {
  const hit = e.target.closest(".palette-hit");
  if (!hit || Number(hit.dataset.index) === paletteAt) return;
  paletteAt = Number(hit.dataset.index);
  markPalette();
});
// A click outside the box closes it, as Escape does. Closed without going anywhere, focus goes back where it was.
$("palette").addEventListener("click", (e) => { if (e.target === $("palette")) $("palette").close(); });
$("palette").addEventListener("close", () => {
  if (paletteFrom && paletteFrom.isConnected) paletteFrom.focus();
  paletteFrom = null;
});

$("run-sweep").addEventListener("click", () => startRun("sweep"));
$("run-claude").addEventListener("click", () => startRun("claude"));
$("add-open").addEventListener("click", () => { $("add-error").textContent = ""; $("add-dialog").showModal(); });
$("add-cancel").addEventListener("click", () => $("add-dialog").close());

// A link put in the Add a posting form is read for the posting it leads to. Only boxes still empty are filled, so
// nothing typed is replaced, and a link that can't be read just says so: the posting can still be added by hand.
const ADD_FILLS = ["company", "title", "location", "description"];
const listed = (names) => (names.length < 3 ? names.join(" and ") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);
let addReads = 0;  // Counts the reads asked for, so an answer to an earlier link is dropped.
let addLinkRead = "";  // The link last read, so leaving the box doesn't read it again.

async function readAddLink() {
  const url = $("add-url").value.trim();
  if (!/^https?:\/\/\S+$/i.test(url) || url === addLinkRead) return;
  addLinkRead = url;
  const mine = ++addReads;
  const note = $("add-read");
  note.textContent = "Reading the posting at that link…";
  try {
    const found = await api("/api/jobs/read", { url });
    if (mine !== addReads) return;
    const filled = ADD_FILLS.filter((name) => {
      const box = $(`add-${name}`);
      if (box.value.trim() || !found[name]) return false;
      box.value = found[name];
      return true;
    });
    const missing = ["company", "title"].filter((name) => !$(`add-${name}`).value.trim());
    note.textContent = (filled.length
      ? `Filled in the ${listed(filled)} from the link. Check ${filled.length === 1 ? "it" : "them"} before adding.`
      : "Read the link, and it had nothing for the boxes still empty.")
      + (missing.length ? ` The page doesn't name the ${listed(missing)}, so type ${missing.length === 1 ? "it" : "them"} in.` : "");
  } catch (err) {
    if (mine === addReads) note.textContent = err.message;
  }
}

function forgetAddLink() {
  addReads += 1;
  addLinkRead = "";
  $("add-read").textContent = "";
}

$("add-url").addEventListener("change", readAddLink);
// The pasted text isn't in the box until the paste has finished.
$("add-url").addEventListener("paste", () => setTimeout(readAddLink));
$("add-form").addEventListener("reset", forgetAddLink);
$("add-dialog").addEventListener("close", () => { if (!$("add-url").value.trim()) forgetAddLink(); });
// A form, so Enter in any one-line box adds the posting, and Company and Title are asked for before anything is sent.
$("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const field = (name) => $(`add-${name}`).value;
  const save = $("add-save");
  if (save.disabled) return;
  save.disabled = true;
  $("add-error").textContent = "";
  try {
    const { id, existing, status } = await api("/api/jobs", {
      company: field("company"), title: field("title"), url: field("url"), location: field("location"), description: field("description"),
    });
    $("add-form").reset();
    $("add-dialog").close();
    await refresh();
    await openJob(id);
    // A link already tracked opens that job rather than adding it again, which would tailor it a second time.
    if (existing) toast(`Already tracked at that link (${status}), so it wasn't added again. Here it is.`);
  } catch (err) {
    $("add-error").textContent = err.message;
  } finally {
    save.disabled = false;
  }
});

// Update available: shown when GitHub's main has code this copy of Pyrite lacks. The server asks GitHub at most once
// an hour, so asking it often costs nothing.
let updateInfo = null;
const UPDATED = "pyrite-updated";  // What an update said, kept across the reload onto the new code.
const commits = (n) => `${n} commit${n === 1 ? "" : "s"}`;

async function checkUpdate() {
  try {
    updateInfo = await api("/api/update");
  } catch (err) {
    return false;  // A check that failed shows nothing, and the next one tries again.
  }
  const button = $("update-open");
  button.hidden = !updateInfo.available;
  if (updateInfo.available) button.title = `GitHub's main has ${commits(updateInfo.behind)} this copy of Pyrite doesn't.`;
  return true;
}

let updateSwitches = false;  // Whether the update the dialog is offering switches the code folder to main first.
let updateGoing = false;  // Whether an update has been asked for and the page is still following it.

function showUpdate(info) {
  const span = `${info.current} to ${info.latest}`;
  const shown = info.changes.slice(0, 20);
  // Merges aren't listed, so a main that is ahead only by merging what this copy already has lists nothing.
  $("update-summary").textContent = shown.length
    ? `GitHub's main is ahead of this copy of Pyrite (${span}). What's new:`
    : `GitHub's main is ahead of this copy of Pyrite (${span}), but only by merges of work this copy already has.`;
  fill($("update-changes"), shown.map((subject) => h("li", {}, subject)),
    info.changes.length > shown.length ? h("li", { class: "muted" }, "and more") : null);
  $("update-changes").hidden = !shown.length;
  const does = "moves its code forward to match, installs its packages again if they changed, and restarts the dashboard";
  updateSwitches = Boolean(info.switch) && !info.why_not;
  let note = info.why_not || `Pyrite ${does}. Your workspace isn't touched.`;
  if (updateSwitches) {
    note = `Pyrite's code folder ${info.branch ? `is on the branch ${info.branch}` : "isn't on a branch"}, and everything there is already in GitHub's main. `
      + `Pyrite switches the folder to main, ${does}. ${info.branch ? `The branch ${info.branch} is kept, and your` : "Your"} workspace isn't touched.`;
  }
  $("update-note").textContent = note;
  // What stops the update is the one thing to read, so it isn't greyed like the description of a working one.
  $("update-note").classList.toggle("muted", !info.why_not);
  $("update-go").hidden = Boolean(info.why_not);
  $("update-go").disabled = false;
  $("update-go").textContent = updateSwitches ? "Switch to main and update" : "Update and restart";
  $("update-recheck").hidden = !info.why_not;
  $("update-recheck").disabled = false;
  $("update-cancel").disabled = false;
  $("update-cancel").textContent = info.why_not ? "Close" : "Not now";
  $("update-error").textContent = "";
}

// Opening the dialog, and Check again in it, read the code folder again, so neither shows a branch or an edit that has
// since gone. That takes a moment, so the last answer shows at once, with nothing to press until the new one is in.
async function openUpdate() {
  const dialog = $("update-dialog");
  if (!dialog.open && updateInfo && updateInfo.available) {
    showUpdate(updateInfo);
    dialog.showModal();
  }
  $("update-go").disabled = true;
  $("update-recheck").disabled = true;
  const answered = await checkUpdate();
  const info = updateInfo;
  if (info && info.available) {
    showUpdate(info);
    if (!dialog.open) dialog.showModal();
    if (!answered) $("update-error").textContent = "The dashboard didn't answer, so this is what it said last.";
    return;
  }
  if (dialog.open) dialog.close();
  if (info) toast(info.error || "Pyrite is up to date.");
}

// After an update, or setup making a workspace, the server stops and a new one starts. The page reloads once the new
// one answers, at `hash` if one is given. `what` says what was done, for when it doesn't come back.
async function waitForRestart(old, what = "The code was updated", hash = "") {
  const until = Date.now() + 60000;
  while (Date.now() < until) {
    await new Promise((resolve) => { setTimeout(resolve, 1000); });
    try {
      const { server } = await api("/api/alive");
      if (server !== old) {
        if (hash) history.replaceState(null, "", hash);
        location.reload();
        return;
      }
    } catch (err) {
      // Down between the old server and the new one.
    }
  }
  throw new Error(`${what}, but the dashboard hasn't come back after a minute. Run \`pyrite open\`, or Pyrite.cmd on Windows, to start it.`);
}

// ---- Setup: making a workspace, while nothing names one ----

const SETUP_LATER = "pyrite-setup-later";
const SETUP_DONE = "pyrite-setup-done";
let setupGoing = false;

function openSetup() {
  const info = state.setup;
  if (!info) return;
  const folder = $("setup-folder");
  if (!folder.value) folder.value = info.suggested;
  $("setup-folder-help").textContent = `Anywhere outside Pyrite's code folder, ${info.code_folder}. A folder that doesn't exist yet is made.`;
  const git = $("setup-git");
  git.disabled = !info.git;
  git.closest("label").title = info.git ? "" : "git isn't installed, or isn't on PATH, so this needs it first.";
  const dialog = $("setup-dialog");
  if (!dialog.open) dialog.showModal();
  if (!$("setup-name").value) $("setup-name").focus();
}

// Opens by itself on the first load, and again on a later one unless you chose to look around first.
function offerSetup() {
  $("setup-open").hidden = !state.setup;
  if (!state.setup || $("setup-dialog").open) return;
  let later = false;
  try { later = sessionStorage.getItem(SETUP_LATER) === "1"; } catch (err) { /* Then it just opens again. */ }
  if (!later) openSetup();
}

function saySetUp() {
  let said = null;
  try {
    said = sessionStorage.getItem(SETUP_DONE);
    sessionStorage.removeItem(SETUP_DONE);
  } catch (err) {
    return;
  }
  if (said) toast(said);
}

$("setup-open").addEventListener("click", openSetup);
$("setup-later").addEventListener("click", () => {
  try { sessionStorage.setItem(SETUP_LATER, "1"); } catch (err) { /* It opens again on the next load, which is fine. */ }
  $("setup-dialog").close();
});
// Escape doesn't close it while the workspace is being made, since the page still has to follow the restart.
$("setup-dialog").addEventListener("cancel", (e) => { if (setupGoing) e.preventDefault(); });
$("setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const start = document.querySelector("input[name='setup-start']:checked");
  const body = {
    name: $("setup-name").value.trim(),
    folder: $("setup-folder").value.trim(),
    start: start ? start.value : "blank",
    git: $("setup-git").checked && !$("setup-git").disabled,
  };
  setupGoing = true;
  $("setup-go").disabled = true;
  $("setup-later").disabled = true;
  $("setup-error").textContent = "";
  $("setup-note").textContent = "Making your workspace…";
  let done;
  try {
    done = await api("/api/setup", body);
  } catch (err) {
    setupGoing = false;
    $("setup-go").disabled = false;
    $("setup-later").disabled = false;
    $("setup-note").textContent = "";
    $("setup-error").textContent = err.message;
    return;
  }
  const said = `Made your workspace at ${done.folder}.`;
  // The copy kept from the old workspace isn't this one's, so the new one's first load waits for its own.
  try { localStorage.removeItem(LAST_STATE); } catch (err) { /* Then it shows until the new state comes. */ }
  if (!done.restarting) {
    $("setup-note").textContent = `${said} Restart the dashboard to open it.`;
    return;
  }
  $("setup-note").textContent = `${said} Opening it…`;
  try { sessionStorage.setItem(SETUP_DONE, `${said} The Profile tab lists what's left to set up.`); } catch (err) { /* A nicety. */ }
  try {
    // The Profile tab is where setup goes on: it lists what's left, most important first.
    await waitForRestart(done.server, "Your workspace was made", "#profile");
  } catch (err) {
    setupGoing = false;
    $("setup-error").textContent = err.message;
  }
});

$("update-open").addEventListener("click", openUpdate);
$("update-recheck").addEventListener("click", openUpdate);
$("update-cancel").addEventListener("click", () => $("update-dialog").close());
// Escape doesn't close it while an update is going, since the page still has to follow the restart.
$("update-dialog").addEventListener("cancel", (e) => { if (updateGoing) e.preventDefault(); });
$("update-go").addEventListener("click", async () => {
  updateGoing = true;
  $("update-go").disabled = true;
  $("update-cancel").disabled = true;
  $("update-error").textContent = "";
  $("update-note").textContent = "Updating. This takes a minute or so if packages need installing.";
  // Either way the update on offer is over, so the button for it goes and the dialog can be closed.
  const over = (note, error, recheck) => {
    updateGoing = false;
    $("update-note").textContent = note;
    $("update-error").textContent = error;
    $("update-go").hidden = true;
    $("update-recheck").hidden = !recheck;
    $("update-recheck").disabled = false;
    $("update-cancel").disabled = false;
    $("update-cancel").textContent = "Close";
  };
  let done;
  try {
    done = await api("/api/update", { switch: updateSwitches });
  } catch (err) {
    // What refused it may have changed what the update would do, so the way on is to check again, not to repeat it.
    over("", err.message, true);
    return;
  }
  const moved = done.switched ? "Pyrite's code folder was switched to main, and updated" : "Pyrite was updated";
  const said = `${moved} from ${done.from} to ${done.to}.${done.packages ? ` ${done.packages}` : ""}`;
  if (!done.restarting) {
    over(`${said} Restart the dashboard to run the new code.`, "", false);
    return;
  }
  $("update-note").textContent = `${said} Restarting the dashboard…`;
  try { sessionStorage.setItem(UPDATED, said); } catch (err) { /* The toast after the reload is a nicety. */ }
  try {
    await waitForRestart(done.server);
  } catch (err) {
    // The code has moved and no dashboard is answering, so there is nothing here to check again or repeat.
    over(said, err.message, false);
  }
});

function sayUpdated() {
  let said = null;
  try {
    said = sessionStorage.getItem(UPDATED);
    sessionStorage.removeItem(UPDATED);
  } catch (err) {
    return;
  }
  if (said) toast(said);
}

restoreRadarFilters();
sayUpdated();
saySetUp();
checkUpdate();
setInterval(() => { if (!document.hidden) checkUpdate(); }, 3600000);
// A job's address opens its panel once the page has loaded what the panel needs, over the first tab.
const startJob = jobInAddress();
if (!startJob) showTab(location.hash.slice(1));
showKept();
refresh().then(() => (startJob ? followAddress() : null));
// Pick up what the morning run does while the page sits open, and catch up at once when you come back to the tab.
setInterval(() => { if (!document.hidden) refresh(); }, 60000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
