"use strict";
// Postings are untrusted, so everything is built as DOM nodes with text content, never as HTML strings.

const $ = (id) => document.getElementById(id);
let state = null;
let openJobId = null;
// The address before a job's panel took it over, as #job-56, which closing the panel puts back.
let hashBeforeJob = "";
let refreshWatch = null;
// Whatever had focus before the job panel opened, so closing it puts you back where you were.
let drawerOpener = null;
// The longest text each box takes, as server.py refuses longer: a note with an update, your notes and the next step.
const LIMITS = { note: 2000, notes: 5000, nextStep: 300 };

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
function codePrompt(first, send, cancelled) {
  let current = first;
  const digits = (value) => value.replace(/\D/g, "");
  const list = h("ul", { class: "code-changes" });
  const note = h("p", { class: "muted" });
  const input = h("input", { class: "code-input", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "7",
    placeholder: "000 000", "aria-label": "Code from the notification" });
  const error = h("p", { class: "error", role: "alert" });
  const ok = h("button", { class: "btn primary", type: "button", disabled: true }, "Confirm");
  const show = (fresh) => {
    current = fresh;
    fill(list, current.changes.map((change) => h("li", {}, `It will ${change}.`)));
    note.textContent = current.sent
      ? "Pyrite sent a 6-digit code to this computer's notifications. It works once, for this change only, for 2 minutes. No notification? Run `pyrite code` in a terminal on this computer."
      : "The notification didn't go through. Run `pyrite code` in a terminal on this computer to see the code. It works once, for this change only, for 2 minutes.";
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
    h("p", { class: "code-title" }, "This change loosens the fact check"), list, note,
    h("div", { class: "part-actions" }, input, ok, resend, cancel), error);
}

// ---- Top of page ----

// Mail is checked with the boards and listed with them on the Sources tab, but a failing inbox is named apart.
const isMail = (source) => /^inbox:/.test(source.source_key || "");

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
  if (failed.length) nodes.push(" ", h("span", { class: "alert" }, `${plural(failed.length, "source")} failing.`));
  if (mailFailed) nodes.push(" ", h("span", { class: "alert" }, "Mail couldn't be checked: see the Sources tab."));
  fill($("sweep"), nodes);
}

// A board check you started reports the same numbers as the line above once it's done, so it isn't said twice.
const sweepShownAbove = (task) => Boolean(task.state === "done" && state.last_run && state.last_run.finished_at
  && toDate(state.last_run.finished_at).getTime() >= toDate(task.started_at).getTime());

function renderKpis() {
  const s = state.stats;
  const tile = (value, label, sub, hot) => h("div", { class: `kpi${hot ? " hot" : ""}` },
    h("span", { class: "value" }, value), h("span", { class: "label" }, label), h("span", { class: "sub" }, sub));
  fill($("kpis"),
    tile(s.ready, "Ready to send", "Passed the fact check", s.ready > 0),
    tile(s.applied, "Applied", `${s.applied_week} in the last 7 days`),
    tile(s.awaiting, "Awaiting reply", s.follow_ups ? `${s.follow_ups} follow-up${s.follow_ups > 1 ? "s" : ""} due` : "No follow-ups due", s.follow_ups > 0),
    // Replies only: a rejection is counted beside it, not inside it, so the rate isn't flattering.
    tile(s.reply_rate === null || s.reply_rate === undefined ? "–" : `${s.reply_rate}%`, "Reply rate",
      s.applied ? [`${s.replied} of ${s.applied} replied`, s.rejected ? `${s.rejected} rejected` : "", s.ghosted ? `${s.ghosted} ghosted` : "",
        s.median_days_to_reply !== null ? `median ${s.median_days_to_reply}d` : ""].filter(Boolean).join(", ") : "Nothing sent yet"),
    tile(s.interviews, "Interviews", "Reached interview stage"),
    tile(s.to_triage, "Prospects", `${s.fresh} new, ${s.possible_ghosts} possible ghost${s.possible_ghosts === 1 ? "" : "s"}`, s.fresh > 0));
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

function renderOrders() {
  renderBriefing();
  const kindClass = (kind) => `kind kind-${kind.toLowerCase().replace(/\s+/g, "-")}`;
  const recheck = state.demo ? [] : state.orders.filter((o) => o.action === "recheck").map((o) => o.job_id);
  const sluiceIds = state.orders.map((o) => o.job_id).filter(Boolean);
  const checkButton = (ids, label) => h("button", { class: "btn dismiss", type: "button", disabled: Boolean(recheckProgress),
    title: "Rebuilds the documents and runs the assay again. Takes up to a minute each.", onclick: () => recheckAll(ids) }, recheckProgress || label);
  // A scam warning may name no job. Its sender and subject are the mail's own words, kept as text.
  const items = state.orders.map((o) => h("li", {},
    // A job opens its drawer, and a setup item opens the tab that fixes it, where there is one.
    h("button", { class: "order", type: "button", title: o.tab ? `Opens the ${o.tab[0].toUpperCase()}${o.tab.split("/")[0].slice(1)} tab` : null,
      onclick: () => (o.job_id ? openJob(o.job_id, sluiceIds) : o.tab ? showTab(o.tab, true) : null) },
      h("span", { class: kindClass(o.kind) }, o.kind),
      h("span", {}, h("span", { class: "what" }, o.text), h("span", { class: "why" }, o.detail))),
    o.alert_id ? h("button", { class: "btn dismiss", type: "button", onclick: () => dismissAlert(o.alert_id) }, "Dismiss") : null,
    o.action === "recheck" && !state.demo ? checkButton([o.job_id], "Check again") : null,
    o.action === "gap_seen" && !state.demo ? h("button", { class: "btn dismiss", type: "button", title: "Keeps this draft as it is and takes it off the list.",
      onclick: (e) => gapSeen(o.job_id, e.currentTarget) }, "Got it") : null));
  const all = recheck.length > 1 ? h("li", { class: "order-batch" }, checkButton(recheck, `Check all ${recheck.length} again`)) : null;
  fill($("orders"), items.length ? [all, ...items] : emptyState("mark", "Nothing needs you right now.", "li"));
}

function renderFunnel() {
  const max = Math.max(1, ...state.funnel.map((f) => f.count));
  fill($("funnel"), state.funnel.map((f) => {
    const width = f.count ? Math.max(1, Math.sqrt(f.count / max) * 100) : 0;
    // An older server sends no icon, so its cell stays empty and the columns still line up.
    return h("div", { class: `funnel-row${f.count ? "" : " none"}`, title: `${f.stage}: ${f.count}` },
      stageIcon(f.icon) || h("span"),
      h("span", { class: "stage" }, f.stage),
      h("span", { class: "funnel-track" }, h("span", { class: `funnel-bar${f.count ? "" : " zero"}`, style: `width:${width}%` })),
      h("span", { class: "count" }, f.count.toLocaleString()));
  }), h("p", { class: "muted funnel-note funnel-closed" },
    (state.closed || []).length ? h("img", { class: "stage-icon", src: "/static/icons/tarnished-24.png", alt: "", width: 24, height: 24 }) : null,
    closedLine()),
  h("p", { class: "muted funnel-note" }, "Each job counts once, at the stage it's at now. Bars use a square-root scale so small stages stay visible."));
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
  { title: "Applied", statuses: ["applied"], hint: "Waiting to hear" },
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

const blockerPill = (job) => ((job.blockers || []).length
  ? pill("bad", "Check first", `From the notes, before you apply:\n- ${job.blockers.join("\n- ")}`) : null);

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
    return h("div", { class: `column${jobs.length || busy ? "" : " empty"}` },
      h("h3", {}, stageIcon(STAGE_ICONS[col.statuses[0]]), h("span", { class: "column-title" }, col.title), h("span", { class: "column-count" }, jobs.length)),
      col.hint ? h("div", { class: "column-hint" }, col.hint) : null,
      col.batch && (jobs.length || busy) ? h("div", { class: "row" }, h("button", {
        id: "run-tailor", class: "btn primary", type: "button", disabled: busy || state.demo || Boolean(notReady("tailor")),
        title: state.demo ? "Not in the demo, which starts no runs."
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

function renderRadar() {
  const tracks = [...new Set(state.jobs.map((j) => j.track).filter(Boolean))].sort();
  const trackSel = $("radar-track");
  const picked = trackSel.value || trackSel.dataset.saved || "";
  delete trackSel.dataset.saved;
  fill(trackSel, h("option", { value: "" }, "Any track"), tracks.map((t) => h("option", { value: t }, t)));
  trackSel.value = tracks.includes(picked) ? picked : "";

  const query = $("radar-search").value.trim().toLowerCase();
  const place = $("radar-place").value;
  const rows = state.jobs.filter((j) => j.status === "new"
    && (!query || `${j.company} ${j.title} ${j.location || ""}`.toLowerCase().includes(query))
    && (!trackSel.value || j.track === trackSel.value)
    && (!place || j.location_kind === place)
    && RADAR_SHOWS[$("radar-show").value](j))
    .sort(RADAR_SORTS[$("radar-sort").value]);
  const shown = rows.slice(0, 300);
  const ids = shown.map((j) => j.id);
  const unseen = state.jobs.filter((j) => j.status === "new" && !j.seen).length;
  const count = rows.length > shown.length ? `Showing ${shown.length} of ${plural(rows.length, "posting")}` : plural(rows.length, "posting");
  $("radar-count").textContent = unseen ? `${count}. ${unseen} not looked at yet.` : count;
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

function renderArchive() {
  const label = { rejected: "Rejected", ghosted: "Ghosted", withdrawn: "Withdrew", passed: "Passed", closed: "Posting closed" };
  const rows = state.jobs.filter((j) => label[j.status])
    .sort((a, b) => (b.status_changed_at || "").localeCompare(a.status_changed_at || ""));
  fill($("archive"),
    h("thead", {}, h("tr", {}, ["Outcome", "Company", "Title", "Applied", "Why"].map((c) => h("th", {}, c)))),
    h("tbody", {}, rows.length ? rows.map((j) => h("tr", { "data-id": j.id, onclick: () => openJob(j.id) },
      h("td", { class: "nowrap" }, label[j.status]), h("td", {}, clamped(j.company)),
      h("td", {}, h("button", { class: "linkish clamp", type: "button" }, j.title)),
      h("td", {}, j.applied_at ? shortDate(j.applied_at) : "No"), h("td", { title: (j.fit_reason || "").length > TABLE_REASON ? j.fit_reason : null }, clip(j.fit_reason, TABLE_REASON))))
      : h("tr", {}, emptyState("tarnished", "Nothing closed yet.", "td", { colspan: 5 }))));
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
  const tokens = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));
  const row = (label, t) => h("tr", {},
    h("td", {}, label),
    h("td", { class: "num" }, t.failed ? `${t.runs} (${t.failed} failed)` : t.runs),
    h("td", { class: "num" }, `${t.minutes} min`),
    h("td", { class: "num" }, tokens(t.input_tokens)),
    h("td", { class: "num" }, tokens(t.output_tokens)),
    h("td", { class: "num" }, `$${t.cost_usd.toFixed(2)}`));
  const counted = "Every Claude run Pyrite starts is counted: the daily run, Refresh resume, Interview prep and checking mail. A Claude Code session of your own isn't.";
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
// Each panel saves by itself. A save sends what's already saved with only that panel's part
// replaced, so half-finished edits in another panel are never written by accident.

let settings = null;
const dirtyParts = new Set();
const settingsRedraw = [];

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
// `change` is handed a copy of what's saved and puts this panel's part into it.
function settingsPart(root, change, afterSave) {
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
  part.send = async (edit) => {
    status.textContent = "Saving…";
    error.textContent = "";
    const promote = savedPromote();
    try {
      edit(promote);
      settings = await api("/api/settings", { version: settings.version, promote });
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
  save.addEventListener("click", () => part.send(change));
  return part;
}

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
  const part = settingsPart(root, (p) => {
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
  const part = settingsPart(root, (p) => {
    p.cities = [...rows].map((row) => row.collect()).filter((city) => city.name.trim() || city.match.trim());
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
  const collect = () => ({
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
        plural(onRadar(saved.name), "prospect"),
        facts && facts.have.length + facts.gaps.length ? `${facts.have.length} of ${facts.have.length + facts.gaps.length} skills` : null,
      ].filter(Boolean).join(" · ") : "Not saved yet"));
    fill(skills, saved ? skillsSummary(facts) : null);
  };
  const part = settingsPart(root, (p) => {
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
    if (!await part.send((p) => { p.industry.splice(gone, 1); })) return;
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
    skills,
    h("div", { class: "part-actions" }, part.save, part.status, remove), part.error);
  cards.add(card);
  settingsRedraw.push(() => { if (cards.has(card)) card.describe(); });
  card.describe();
  return root;
}

function renderSettings() {
  dirtyParts.clear();
  settingsRedraw.length = 0;
  const cards = new Set();
  const industries = h("div", { class: "industries" });
  const addIndustry = (industry, index) => industries.append(industryCard(industry, index, cards));
  fill($("settings-form"),
    h("div", { class: "settings-intro" },
      h("p", { class: "muted" }, "Preferred cities and industries move postings up your prospects. They don't change what's kept or tailored. Each panel saves by itself."),
      h("button", { class: "btn", type: "button", onclick: reloadSettings }, "Reload")),
    h("details", { class: "more" }, h("summary", {}, "How this works"),
      h("p", { class: "muted" }, "A match adds points to a posting's priority, which only changes the order you and the daily run see things in. It can't bring back a posting the filters dropped: to accept a new city at all, add it under [location] in profile/search.toml too. An industry counts when the employer is listed, a word is in the employer's name or the title, or the words appear often enough in the description. Filters and everything else stay in profile/search.toml. Saving writes the [promote] section of that file out again in its usual layout, so comments of your own in that section are replaced. A setting there that this tab doesn't show stops the save instead of being lost.")),
    pointsPanel(),
    citiesPanel(),
    h("div", { class: "settings-heading-row" }, h("h2", { class: "settings-heading" }, "Industries"),
      h("button", { class: "btn", type: "button", onclick: () => {
        addIndustry({}, null);
        industries.lastChild.querySelector("input").focus();
      } }, "Add an industry")),
    industries);
  savedPromote().industry.forEach((industry, index) => addIndustry(industry, index));
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
      button.title = state.demo ? "Not in the demo, which starts no runs." : why || button.dataset.idleTitle;
    }
    if (!task || (kind === "sweep" && sweepShownAbove(task))) continue;
    const ended = task.finished_at || task.started_at;
    if (busy) lines.push(h("span", {}, `${run.name}, started ${ago(task.started_at)}: ${task.detail}`));
    else if (task.state === "failed") lines.push(h("span", { class: "alert" }, `${run.name} failed ${ago(ended)}: ${task.detail}`));
    else if (Date.now() - toDate(ended).getTime() < RUN_RESULT_SHOWN_FOR) {
      lines.push(h("span", {}, `${run.name} finished ${ago(ended)}. ${kind === "claude" ? "Its field report is below." : task.detail}`));
    }
  }
  fill($("runs"), lines.flatMap((line, index) => (index ? [h("br"), line] : [line])));
  // The mark beside the title throws sparks while anything runs, and only glints now and then otherwise.
  $("mark").classList.toggle("working", running);
  // While something is running, look again soon so its progress and its results show up.
  clearTimeout(runWatch);
  if (running) runWatch = setTimeout(refresh, 5000);
}

async function startRun(kind) {
  const questions = {
    claude: "Have Claude judge the new postings and tailor the best ones now?\n\nIt can take a while and uses your Claude plan. Each draft still has to pass the assay.",
    tailor: "Have Claude write every draft under Being tailored now, stretch jobs included?\n\nIt uses your Claude plan. Each draft still has to pass the assay.",
  };
  if (questions[kind] && !window.confirm(questions[kind])) return;
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
  // The to-do count shows in the browser tab, so a background tab says when something needs you.
  document.title = state.orders.length ? `(${state.orders.length}) Pyrite` : "Pyrite";
  renderSweep();
  renderRuns();
  renderKpis();
  renderOrders();
  renderFunnel();
  renderBoard();
  renderRadar();
  renderArchive();
  renderSources();
}

async function refresh() {
  try {
    state = await api("/api/state");
    render();
  } catch (err) {
    // fetch throws a TypeError when nothing answered. Anything else is the server saying what's wrong.
    $("sweep").textContent = err instanceof TypeError ? "Can't reach the server. Is Pyrite still running?" : err.message;
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
    h("ul", {}, lines.map((line) => h("li", {}, line)), blockers.map((line) => h("li", {}, line))),
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
    const band = pct > 85 ? " That's high enough to read as copied from the posting, which screeners now mark down: aim for 60 to 80%."
      : pct < 40 ? " Below about 40%, a filter on skills may not pick it up." : "";
    blocks.push(h("p", { class: "muted" }, `The resume uses ${pct}% of the skill terms in this posting.${missing}${band}`));
  }
  if (result.drafter && Object.keys(result.drafter).length) {
    const versions = [...new Set(Object.values(result.drafter))].sort();
    blocks.push(h("p", { class: "muted" }, `Documents built by drafter ${versions.join(" and ")}.`));
  }
  return blocks;
}

const refreshing = (job) => Boolean(job.refresh && job.refresh.state === "running");
const prepping = (job) => Boolean(job.prep && job.prep.state === "running");
const working = (job) => refreshing(job) || prepping(job);
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
  return h("button", { class: "btn", type: "button", disabled: refreshing(job), onclick: () => startRefresh(job) },
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
  return h("button", { class: "btn", type: "button", disabled: prepping(job), onclick: () => startPrep(job) },
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
    h("div", {}, h("h3", {}, "Next step"), h("div", { class: "stack" }, nextText,
      h("div", { class: "row" }, nextDate, h("button", { class: "btn", type: "button",
        onclick: () => tryAct(job.id, { action: "next_action", text: nextText.value, date: nextDate.value }, undefined, ["nextText", "nextDate"]) }, "Save"),
      nextStatus))),
    outreachBlock(job),
    h("div", {}, h("h3", {}, "Your notes"), h("div", { class: "stack" }, notesEl, h("div", { class: "row" },
      h("button", { class: "btn", type: "button", onclick: () => tryAct(job.id, { action: "note", notes: notesEl.value }, undefined, ["notes"]) }, "Save notes"),
      notesStatus))),
    job.notes_md ? h("div", {}, h("h3", {}, "Fit and interview notes"), h("div", { class: "prose" }, job.notes_md)) : null,
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

// What the job panel covers while it's open.
function pageBehind() {
  return [document.querySelector("header.masthead"), document.querySelector("main")].filter(Boolean);
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
    return [heading, h("p", { class: "muted" }, "Add this industry's codes (NAICS) on the Settings tab to see official employment, pay and growth here. ",
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
  const start = h("button", { class: "btn", type: "button", disabled: running, onclick: async () => {
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
    return fill(view, h("p", { class: "muted" }, "You don't follow any industries yet. Add them on the Settings tab, and they'll show here."));
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

const tabs = [...document.querySelectorAll(".tabs button")];

// The tab you're on is in the address, so a reload or a bookmark comes back to it. On the Profile tab so is the
// section, as #profile/achievements.
function showTab(name, focus = false) {
  const [base, ...rest] = String(name || "").split("/");
  const tab = tabs.find((t) => t.dataset.tab === base) || tabs[0];
  tabs.forEach((b) => {
    b.setAttribute("aria-selected", String(b === tab));
    b.tabIndex = b === tab ? 0 : -1;
  });
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== `view-${tab.dataset.tab}`; });
  if (focus) tab.focus();
  const section = tab.dataset.tab === "profile" ? profileShow(rest.join("/")) : "";
  const hash = tab === tabs[0] ? "" : `#${tab.dataset.tab}${section ? `/${section}` : ""}`;
  // While a job's panel is open the address is the job's, and the tab's waits for the panel to close.
  if (openJobId) hashBeforeJob = hash;
  else if (location.hash !== hash) history.replaceState(null, "", hash || location.pathname + location.search);
  if (tab.dataset.tab === "settings" && !dirtyParts.size) loadSettings();
  if (tab.dataset.tab === "facts" && !factsOpen) loadFacts();
  if (tab.dataset.tab === "industries") loadIndustries();
}

// Coming back to the Profile tab returns to the section you left it on.
const tabTarget = (tab) => (tab.dataset.tab === "profile" && profileAt ? `profile/${profileAt}` : tab.dataset.tab);

// The address of the tab on show, as showTab writes it, for when a job's panel closes over it.
function tabAddress() {
  const tab = tabs.find((t) => t.getAttribute("aria-selected") === "true") || tabs[0];
  return tab === tabs[0] ? "" : `#${tabTarget(tab)}`;
}
tabs.forEach((tab) => tab.addEventListener("click", () => showTab(tabTarget(tab))));
// Arrow keys, Home and End move along the tabs, as in any other tab list.
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  const at = tabs.indexOf(document.activeElement);
  if (at < 0) return;
  const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  showTab(tabTarget(tabs[(to + tabs.length) % tabs.length]), true);
});
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
RADAR_FILTERS.forEach((id) => $(id).addEventListener("input", () => { saveRadarFilters(); renderRadar(); }));
$("scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  // A dialog on top handles its own keys, Escape included.
  if (document.querySelector("dialog[open]")) return;
  if (e.key === "Escape" && openJobId) closeDrawer();
  else if (e.key === "/" && !openJobId && !e.ctrlKey && !e.metaKey && !e.altKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) {
    e.preventDefault();
    showTab("radar");
    $("radar-search").focus();
    $("radar-search").select();
  } else drawerKeys(e);
});

$("run-sweep").addEventListener("click", () => startRun("sweep"));
$("run-claude").addEventListener("click", () => startRun("claude"));
$("add-open").addEventListener("click", () => { $("add-error").textContent = ""; $("add-dialog").showModal(); });
$("add-cancel").addEventListener("click", () => $("add-dialog").close());
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
    return;  // A check that failed shows nothing, and the next one tries again.
  }
  const button = $("update-open");
  button.hidden = !updateInfo.available;
  if (updateInfo.available) button.title = `GitHub's main has ${commits(updateInfo.behind)} this copy of Pyrite doesn't.`;
}

function openUpdate() {
  const info = updateInfo;
  if (!info || !info.available) return;
  $("update-summary").textContent = `GitHub's main has ${commits(info.behind)} this copy doesn't (${info.current} to ${info.latest}). What they say:`;
  const shown = info.changes.slice(0, 20);
  fill($("update-changes"), shown.map((subject) => h("li", {}, subject)),
    info.changes.length > shown.length ? h("li", { class: "muted" }, "and more") : null);
  $("update-note").textContent = info.why_not
    || "Pyrite moves its code forward to match, installs its packages again if they changed, and restarts the dashboard. Your workspace isn't touched.";
  $("update-go").hidden = Boolean(info.why_not);
  $("update-go").disabled = false;
  $("update-cancel").disabled = false;
  $("update-cancel").textContent = info.why_not ? "Close" : "Not now";
  $("update-error").textContent = "";
  $("update-dialog").showModal();
}

// After an update the server stops and a new one starts on the new code. The page reloads once the new one answers.
async function waitForRestart(old) {
  const until = Date.now() + 60000;
  while (Date.now() < until) {
    await new Promise((resolve) => { setTimeout(resolve, 1000); });
    try {
      const { server } = await api("/api/alive");
      if (server !== old) {
        location.reload();
        return;
      }
    } catch (err) {
      // Down between the old server and the new one.
    }
  }
  throw new Error("The code was updated, but the dashboard hasn't come back after a minute. Run `pyrite open`, or Pyrite.cmd on Windows, to start it.");
}

$("update-open").addEventListener("click", openUpdate);
$("update-cancel").addEventListener("click", () => $("update-dialog").close());
// Escape doesn't close it while an update is going, since the page still has to follow the restart.
$("update-dialog").addEventListener("cancel", (e) => { if ($("update-go").disabled) e.preventDefault(); });
$("update-go").addEventListener("click", async () => {
  $("update-go").disabled = true;
  $("update-cancel").disabled = true;
  $("update-error").textContent = "";
  $("update-note").textContent = "Updating. This takes a minute or so if packages need installing.";
  try {
    const done = await api("/api/update", {});
    const said = `Pyrite was updated from ${done.from} to ${done.to}.${done.packages ? ` ${done.packages}` : ""}`;
    if (!done.restarting) {
      $("update-note").textContent = `${said} Restart the dashboard to run the new code.`;
      $("update-cancel").disabled = false;
      $("update-cancel").textContent = "Close";
      return;
    }
    $("update-note").textContent = `${said} Restarting the dashboard…`;
    try { sessionStorage.setItem(UPDATED, said); } catch (err) { /* The toast after the reload is a nicety. */ }
    await waitForRestart(done.server);
  } catch (err) {
    $("update-error").textContent = err.message;
    $("update-note").textContent = "";
    $("update-go").disabled = false;
    $("update-cancel").disabled = false;
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
checkUpdate();
setInterval(() => { if (!document.hidden) checkUpdate(); }, 3600000);
// A job's address opens its panel once the page has loaded what the panel needs, over the first tab.
const startJob = jobInAddress();
if (!startJob) showTab(location.hash.slice(1));
refresh().then(() => (startJob ? followAddress() : null));
// Pick up what the morning run does while the page sits open, and catch up at once when you come back to the tab.
setInterval(() => { if (!document.hidden) refresh(); }, 60000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
