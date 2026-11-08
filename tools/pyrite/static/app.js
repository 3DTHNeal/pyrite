"use strict";
// Postings are untrusted, so everything is built as DOM nodes with text content, never as HTML strings.

const $ = (id) => document.getElementById(id);
let state = null;
let openJobId = null;
let refreshWatch = null;
// Whatever had focus before the job panel opened, so closing it puts you back where you were.
let drawerOpener = null;

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "onclick") el.addEventListener("click", value);
    else if (key === "style") el.setAttribute("style", value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
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
const capitalized = (text) => text.charAt(0).toUpperCase() + text.slice(1);

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
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// ---- Top of page ----

function renderSweep() {
  const run = state.last_run;
  const failed = state.sources.filter((s) => s.last_error);
  const parts = [];
  if (run) {
    const reposted = run.stats.reposted ? `, ${run.stats.reposted} reposted` : "";
    parts.push(`Boards checked ${ago(run.finished_at)}: ${run.stats.postings.toLocaleString()} postings read across ${run.stats.sources} sources, ${run.stats.new} new${reposted}.`);
  } else {
    parts.push("The boards haven't been checked yet.");
  }
  const nodes = [parts.join(" ")];
  if (run && Date.now() - toDate(run.finished_at).getTime() > 30 * 3.6e6) nodes.push(" ", h("span", { class: "alert" }, "This is out of date, so check the Pyrite Sweep task."));
  if (failed.length) nodes.push(" ", h("span", { class: "alert" }, `${failed.length} source${failed.length > 1 ? "s" : ""} failing.`));
  fill($("sweep"), nodes);
}

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

function renderOrders() {
  renderBriefing();
  const kindClass = (kind) => `kind kind-${kind.toLowerCase().replace(/\s+/g, "-")}`;
  const recheck = state.demo ? [] : state.orders.filter((o) => o.action === "recheck").map((o) => o.job_id);
  const sluiceIds = state.orders.map((o) => o.job_id).filter(Boolean);
  const checkButton = (ids, label) => h("button", { class: "btn dismiss", type: "button", disabled: Boolean(recheckProgress),
    title: "Rebuilds the documents and runs the assay again. Takes up to a minute each.", onclick: () => recheckAll(ids) }, recheckProgress || label);
  // A scam warning may name no job. Its sender and subject are the mail's own words, kept as text.
  const items = state.orders.map((o) => h("li", {},
    h("button", { class: "order", type: "button", onclick: () => (o.job_id ? openJob(o.job_id, sluiceIds) : null) },
      h("span", { class: kindClass(o.kind) }, o.kind),
      h("span", {}, h("span", { class: "what" }, o.text), h("span", { class: "why" }, o.detail))),
    o.alert_id ? h("button", { class: "btn dismiss", type: "button", onclick: () => dismissAlert(o.alert_id) }, "Dismiss") : null,
    o.action === "recheck" && !state.demo ? checkButton([o.job_id], "Check again") : null));
  const all = recheck.length > 1 ? h("li", { class: "order-batch" }, checkButton(recheck, `Check all ${recheck.length} again`)) : null;
  fill($("orders"), items.length ? [all, ...items] : h("li", { class: "empty" }, "Nothing needs you right now."));
}

function renderFunnel() {
  const max = Math.max(1, ...state.funnel.map((f) => f.count));
  fill($("funnel"), state.funnel.map((f) => {
    const width = f.count ? Math.max(1, Math.sqrt(f.count / max) * 100) : 0;
    return h("div", { class: "funnel-row", title: `${f.stage}: ${f.count}` },
      h("span", { class: "stage" }, f.stage),
      h("span", { class: "funnel-track" }, h("span", { class: `funnel-bar${f.count ? "" : " zero"}`, style: `width:${width}%` })),
      h("span", { class: "count" }, f.count.toLocaleString()));
  }), h("p", { class: "muted funnel-note" }, closedLine()),
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
  return pills;
}

const FIT_TONE = { strong: "good", good: "good", stretch: "warn", skip: "bad" };
const NOT_SENT = ["new", "shortlisted", "needs_fix", "ready"];
const dayName = (iso) => toDate(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

// When the posting stops taking applications. Only worth showing until you've sent one.
function deadlinePill(job) {
  const days = job.days_to_deadline;
  if (days === null || days === undefined || !NOT_SENT.includes(job.status)) return null;
  const on = shortDate(job.deadline);
  if (days < 0) return pill("muted", `Deadline ${on} passed`, "The posting's stated deadline has passed. \"At least until\" often runs longer, so check the posting is still up.");
  const label = days === 0 ? "Apply today" : days === 1 ? "Apply by tomorrow" : `Apply by ${on}`;
  return pill(days <= 2 ? "bad" : days <= 7 ? "warn" : "muted", label, `The posting gives ${dayName(job.deadline)} as its deadline`);
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
  if (job.fit && !sent) meta.push(pill(FIT_TONE[job.fit] || "muted", job.fit === "skip" ? "Skip" : `${capitalized(job.fit)} fit`, job.fit_reason));
  if (job.refresh && job.refresh.state === "running") meta.push(pill("info", "Refreshing resume"));
  if (job.prep && job.prep.state === "running") meta.push(pill("info", "Writing interview prep"));
  if (job.status === "needs_fix") meta.push(pill("bad", "Failed assay"));
  if (job.changed_since_check && job.changed_since_check.length) meta.push(pill("bad", "Changed since checked", "Its files changed after the assay passed it"));
  if (job.changed_after_sending && job.changed_after_sending.length) meta.push(pill("bad", "Changed after sending", `${job.changed_after_sending.join(", ")} no longer match the sent copy`));
  if (job.posting_closed_at) meta.push(pill("bad", "Posting down"));
  if (job.follow_up_due) meta.push(pill("warn", job.next_action === "Follow up" ? "Follow up" : "Next step due", job.next_action));
  if (job.quiet) meta.push(pill("warn", "Gone quiet"));
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
      h("h3", {}, col.title, h("span", {}, jobs.length)),
      col.hint ? h("div", { class: "column-hint" }, col.hint) : null,
      col.batch && (jobs.length || busy) ? h("div", { class: "row" }, h("button", {
        id: "run-tailor", class: "btn primary", type: "button", disabled: busy || state.demo,
        title: state.demo ? "Not in the demo, which starts no runs."
          : "Have Claude write every draft in this column now, stretch jobs included. Uses your Claude plan.",
        onclick: () => startRun("tailor") }, busy ? RUNS.tailor.busy : RUNS.tailor.idle)) : null,
      h("div", { class: "cards" }, jobs.map((job) => h("button", { class: "card", type: "button", onclick: () => openJob(job.id, jobs.map((j) => j.id)) },
        h("span", { class: "co" }, job.company), h("span", { class: "ti" }, job.title), h("span", { class: "meta" }, cardMeta(job))))));
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
    && (!query || `${j.company} ${j.title}`.toLowerCase().includes(query))
    && (!trackSel.value || j.track === trackSel.value)
    && (!place || j.location_kind === place)
    && RADAR_SHOWS[$("radar-show").value](j))
    .sort(RADAR_SORTS[$("radar-sort").value]);
  const shown = rows.slice(0, 300);
  const ids = shown.map((j) => j.id);
  const unseen = state.jobs.filter((j) => j.status === "new" && !j.seen).length;
  const count = rows.length > shown.length ? `Showing ${shown.length} of ${rows.length}` : `${rows.length} postings`;
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
      h("td", {}, j.company),
      h("td", {}, h("button", { class: "linkish", type: "button", title: j.seen ? null : "You haven't opened this one yet" }, j.title)),
      h("td", {}, h("span", { class: "place", title: j.location || "" }, shortPlace(j.location))),
      h("td", {}, j.track),
      h("td", {}, j.comp),
      h("td", { class: "nowrap", title: shortDate(j.first_posted_at || j.posted_at) }, daysAgo(j.age_days) || "Unknown"),
      h("td", {}, h("span", { class: "signals" }, urgentPills(j), freshnessPills(j))),
      h("td", { class: "row-actions" }, quick(j, "Tailor", "tailor_next", "btn small"), quick(j, "Pass", "pass", "btn small"))))
      : h("tr", {}, h("td", { colspan: 10, class: "empty" }, "No prospects match."))));
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
      h("td", {}, label[j.status]), h("td", {}, j.company),
      h("td", {}, h("button", { class: "linkish", type: "button" }, j.title)),
      h("td", {}, j.applied_at ? shortDate(j.applied_at) : "No"), h("td", {}, j.fit_reason || "")))
      : h("tr", {}, h("td", { colspan: 5, class: "empty" }, "Nothing closed yet."))));
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

// What a city name would match right now, by the same whole-word rule the ranking uses.
function cityFeedback(name, pattern) {
  if (!name) return "";
  if (pattern) return `${plural(onRadar(name), "prospect")} with your pattern, as last saved`;
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
  return `${plural(prospects, "prospect")}.${seen}`;
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
    const points = numberInput(city.points, "Default");
    points.setAttribute("aria-label", "Points");
    const match = h("input", { value: city.match || "", placeholder: "Optional", "aria-label": "Pattern", title: "A pattern to use when the name alone isn't enough, as when another state has a city with the same name" });
    const seen = h("td", { class: "muted city-seen" });
    const row = { collect: () => ({ name: name.value, points: settingsNumber(points), match: match.value }) };
    row.show = () => { seen.textContent = cityFeedback(name.value.trim(), match.value.trim()); };
    const line = h("tr", {}, h("td", {}, name), h("td", {}, points), h("td", {}, match), seen,
      h("td", {}, h("button", { class: "btn danger", type: "button", "aria-label": "Remove this city", onclick: () => {
        rows.delete(row);
        line.remove();
        part.touch();
      } }, "Remove")));
    name.addEventListener("input", row.show);
    match.addEventListener("input", row.show);
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
  const points = numberInput(industry.points, "Default");
  const terms = h("textarea", { rows: "4" });
  terms.value = (industry.terms || []).join("\n");
  const companies = h("textarea", { rows: "4" });
  companies.value = (industry.companies || []).join("\n");
  const wants = h("textarea", { rows: "4" });
  wants.value = (industry.wants || []).map((w) => (w.match ? `${w.name}: ${w.match}` : w.name)).join("\n");
  const collect = () => ({
    name: name.value,
    points: settingsNumber(points),
    terms: settingsLines(terms.value),
    companies: settingsLines(companies.value),
    wants: settingsLines(wants.value).map((line) => {
      const split = line.indexOf(": ");
      return split < 0 ? { name: line } : { name: line.slice(0, split), match: line.slice(split + 2) };
    }),
  });
  const summary = h("summary", {});
  const skills = h("div", {});
  const root = h("details", { class: "panel industry", open: index === null });
  card.describe = () => {
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
    h("div", { class: "industry-head" }, settingsField("Name", name), settingsField("Points", points)),
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
      h("p", { class: "muted" }, "A match adds points to a posting's priority, which only changes the order you and the daily run see things in. It can't bring back a posting the filters dropped: to accept a new city at all, add it under [location] in profile/search.toml too. An industry counts when the employer is listed, a word is in the employer's name or the title, or the words appear often enough in the description. Filters and everything else stay in profile/search.toml.")),
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
    try {
      facts = await api("/api/facts", { file: file.key, version: file.version, text: rebuild(area.value) });
    } catch (err) {
      error.textContent = err.message;
      return;
    }
    renderFacts();
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
    : "One per line: specialist terms that are true of you but aren't named in the fact bank.";
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
      ? "What a resume may claim. The assay reads these files as they stand each time it checks a draft, and every save keeps the version before it beside the file."
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
      // The demo starts no runs, so its buttons say so rather than asking to spend your Claude plan and then refusing.
      button.disabled = busy || Boolean(state.demo);
      button.textContent = busy ? run.busy : run.idle;
      if (state.demo) button.title = "Not in the demo, which starts no runs.";
    }
    if (!task) continue;
    const ended = task.finished_at || task.started_at;
    if (busy) lines.push(h("span", {}, `${run.name}, started ${ago(task.started_at)}: ${task.detail}`));
    else if (task.state === "failed") lines.push(h("span", { class: "alert" }, `${run.name} failed ${ago(ended)}: ${task.detail}`));
    else if (Date.now() - toDate(ended).getTime() < RUN_RESULT_SHOWN_FOR) {
      lines.push(h("span", {}, `${run.name} finished ${ago(ended)}. ${kind === "claude" ? "Its field report is below." : task.detail}`));
    }
  }
  fill($("runs"), lines.flatMap((line, index) => (index ? [h("br"), line] : [line])));
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
  return h("div", { class: changed.length ? "callout bad" : "callout" },
    h("strong", {}, changed.length ? "Changed after sending" : `Frozen since you applied on ${shortDate(job.applied_at)}`),
    h("p", {}, changed.length
      ? `${changed.join(", ")} no longer match the copy kept when you applied. The sent copies below are the record; the files in the folder are not what the company has.`
      : links.length ? "The copies below are what went out. The folder's documents aren't rebuilt or refreshed any more; a new application gets a new job."
        : "No copy of the sent documents is on record for this job, so the folder's files may not match what the company has."),
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
    lines.push(days < 0 ? `The posting's stated deadline, ${on}, has passed. Check it's still up before you spend time on it.`
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

// `list` is the order of the list it was opened from, for Previous, Next and moving on after a pass.
async function openJob(id, list) {
  let job;
  try {
    job = await api(`/api/job/${id}`);
  } catch (err) {
    return;
  }
  if (list) nav = list;
  else if (!nav.includes(id)) nav = [];
  if (job.status === "new" && !job.seen && !state.demo) markSeen(id);
  const wasOpen = !$("drawer").hidden;
  if (!wasOpen) drawerOpener = document.activeElement;
  openJobId = id;
  clearTimeout(refreshWatch);
  if (working(job)) refreshWatch = setTimeout(() => watchRefresh(id), 5000);
  const noteEl = h("input", { placeholder: "Add a note to this update (optional)", "aria-label": "Note for this update", style: "width:100%" });
  keepDraft(id, "update", noteEl, "");
  const notesStatus = h("span", { class: "muted part-status", role: "status" });
  const notesEl = h("textarea", { rows: 3, "aria-label": "Your notes" });
  keepDraft(id, "notes", notesEl, job.notes || "", notesStatus);
  const nextStatus = h("span", { class: "muted part-status", role: "status" });
  const nextText = h("input", { placeholder: "e.g. Phone screen with the hiring manager", "aria-label": "Next step" });
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
      h("div", {}, h("h2", {}, job.title), h("p", { class: "muted" }, job.company)),
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
    h("div", {}, h("h3", {}, "Next step"), h("div", { class: "stack" }, nextText,
      h("div", { class: "row" }, nextDate, h("button", { class: "btn", type: "button",
        onclick: () => tryAct(job.id, { action: "next_action", text: nextText.value, date: nextDate.value }, undefined, ["nextText", "nextDate"]) }, "Save"),
      nextStatus))),
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
  $("drawer").scrollTop = 0;
  // Focus goes into the panel so the keyboard shortcuts and Tab start there, not on the page behind it.
  if (!wasOpen || !$("drawer").contains(document.activeElement)) $("drawer").focus();
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

function closeDrawer() {
  openJobId = null;
  $("drawer").hidden = true;
  $("scrim").hidden = true;
  // A pass or a refresh may have redrawn the list it came from, and then there's nothing left to return to.
  if (drawerOpener && drawerOpener.isConnected) drawerOpener.focus();
  drawerOpener = null;
}

// ---- Wiring ----

const tabs = [...document.querySelectorAll(".tabs button")];

// The tab you're on is in the address, so a reload or a bookmark comes back to it.
function showTab(name, focus = false) {
  const tab = tabs.find((t) => t.dataset.tab === name) || tabs[0];
  tabs.forEach((b) => {
    b.setAttribute("aria-selected", String(b === tab));
    b.tabIndex = b === tab ? 0 : -1;
  });
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== `view-${tab.dataset.tab}`; });
  if (focus) tab.focus();
  const hash = tab === tabs[0] ? "" : `#${tab.dataset.tab}`;
  if (location.hash !== hash) history.replaceState(null, "", hash || location.pathname + location.search);
  if (tab.dataset.tab === "settings" && !dirtyParts.size) loadSettings();
  if (tab.dataset.tab === "facts" && !factsOpen) loadFacts();
}

tabs.forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));
// Arrow keys, Home and End move along the tabs, as in any other tab list.
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  const at = tabs.indexOf(document.activeElement);
  if (at < 0) return;
  const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  showTab(tabs[(to + tabs.length) % tabs.length].dataset.tab, true);
});
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
window.addEventListener("beforeunload", (e) => { if (dirtyParts.size || factsOpen || drafts.size) e.preventDefault(); });
$("radar-search").addEventListener("input", renderRadar);
RADAR_FILTERS.forEach((id) => $(id).addEventListener("input", () => { saveRadarFilters(); renderRadar(); }));
$("scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  // A dialog on top handles its own keys, Escape included.
  if ($("add-dialog").open) return;
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
    const { id } = await api("/api/jobs", {
      company: field("company"), title: field("title"), url: field("url"), location: field("location"), description: field("description"),
    });
    $("add-form").reset();
    $("add-dialog").close();
    await refresh();
    await openJob(id);
  } catch (err) {
    $("add-error").textContent = err.message;
  } finally {
    save.disabled = false;
  }
});

restoreRadarFilters();
showTab(location.hash.slice(1));
refresh();
// Pick up what the morning run does while the page sits open, and catch up at once when you come back to the tab.
setInterval(() => { if (!document.hidden) refresh(); }, 60000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
