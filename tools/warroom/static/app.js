"use strict";
// Postings are untrusted, so everything is built as DOM nodes with text content, never as HTML strings.

const $ = (id) => document.getElementById(id);
let state = null;
let openJobId = null;
let refreshWatch = null;

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
  const data = await res.json();
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
    parts.push(`Last sweep ${ago(run.finished_at)}: ${run.stats.postings.toLocaleString()} postings read across ${run.stats.sources} sources, ${run.stats.new} new${reposted}.`);
  } else {
    parts.push("No sweep has run yet.");
  }
  const nodes = [parts.join(" ")];
  if (run && Date.now() - toDate(run.finished_at).getTime() > 30 * 3.6e6) nodes.push(" ", h("span", { class: "alert" }, "This is out of date, so check the War Room Sweep task."));
  if (failed.length) nodes.push(" ", h("span", { class: "alert" }, `${failed.length} source${failed.length > 1 ? "s" : ""} failing.`));
  fill($("sweep"), nodes);
}

function renderKpis() {
  const s = state.stats;
  const tile = (value, label, sub, hot) => h("div", { class: `kpi${hot ? " hot" : ""}` },
    h("span", { class: "value" }, value), h("span", { class: "label" }, label), h("span", { class: "sub" }, sub));
  fill($("kpis"),
    tile(s.ready, "Ready to send", "Resume passed checks", s.ready > 0),
    tile(s.applied, "Applied", `${s.applied_week} in the last 7 days`),
    tile(s.awaiting, "Awaiting reply", s.follow_ups ? `${s.follow_ups} follow-up${s.follow_ups > 1 ? "s" : ""} due` : "No follow-ups due", s.follow_ups > 0),
    tile(s.response_rate === null ? "–" : `${s.response_rate}%`, "Response rate",
      s.applied ? `${s.heard} of ${s.applied}${s.median_days_to_reply !== null ? `, median ${s.median_days_to_reply}d` : ""}` : "Nothing sent yet"),
    tile(s.interviews, "Interviews", "Reached interview stage"),
    tile(s.to_triage, "On the radar", `${s.fresh} new, ${s.possible_ghosts} possible ghost${s.possible_ghosts === 1 ? "" : "s"}`, s.fresh > 0));
}

function renderOrders() {
  const b = state.briefing;
  fill($("briefing"), b ? [h("span", { class: "when" }, `Morning briefing, ${ago(b.ts)}`), b.body] : []);
  const kindClass = (kind) => `kind kind-${kind.toLowerCase().replace(/\s+/g, "-")}`;
  const items = state.orders.map((o) => h("li", {},
    h("button", { class: "order", type: "button", onclick: () => openJob(o.job_id) },
      h("span", { class: kindClass(o.kind) }, o.kind),
      h("span", {}, h("span", { class: "what" }, o.text), h("span", { class: "why" }, o.detail)))));
  fill($("orders"), items.length ? items : h("li", { class: "empty" }, "Nothing needs you right now."));
}

function renderFunnel() {
  const max = Math.max(1, ...state.funnel.map((f) => f.count));
  fill($("funnel"), state.funnel.map((f) => {
    const width = f.count ? Math.max(1, Math.sqrt(f.count / max) * 100) : 0;
    return h("div", { class: "funnel-row", title: `${f.stage}: ${f.count}` },
      h("span", { class: "stage" }, f.stage),
      h("span", { class: "funnel-track" }, h("span", { class: `funnel-bar${f.count ? "" : " zero"}`, style: `width:${width}%` })),
      h("span", { class: "count" }, f.count.toLocaleString()));
  }), h("p", { class: "muted", style: "font-size:12px" }, "Bar length uses a square-root scale so small stages stay visible."));
}

// ---- Pipeline ----

const COLUMNS = [
  { title: "Being tailored", statuses: ["shortlisted", "needs_fix"], hint: "Claude writes these on the next run" },
  { title: "Ready to send", statuses: ["ready"], hint: "Read, then apply on the company's site" },
  { title: "Applied", statuses: ["applied"], hint: "Waiting to hear" },
  { title: "Heard back", statuses: ["responded"] },
  { title: "Interviewing", statuses: ["interviewing"] },
  { title: "Offer", statuses: ["offer"] },
];

function freshnessPills(job) {
  const pills = [];
  if (job.is_new && !job.applied_at) pills.push(pill("good", "New", `Posted ${daysAgo(job.age_days)} and never reposted`));
  if (!job.applied_at) for (const name of job.promoted) pills.push(pill("info", name, "A city or industry you asked to rank higher. It raises priority, not the score."));
  if (job.reposts) pills.push(pill(job.reposts > 1 ? "bad" : "warn", `Reposted ${job.reposts}×`, "The same job came back under a new listing, or after being taken down"));
  if (job.redates) pills.push(pill("warn", `Re-dated ${job.redates}×`, "The board moved this listing's posted date forward"));
  if (job.ghost_risk) pills.push(pill("bad", "Possible ghost", `${capitalized(job.ghost_reason)}. A prompt to look closer, not proof.`));
  if (job.may_be_repost) pills.push(pill("muted", "May be a repost", "This Workday link ends in -1 or similar, which often means the requisition has more than one posting. A hint only."));
  return pills;
}

const FIT_TONE = { strong: "good", good: "good", stretch: "warn", skip: "bad" };

function cardMeta(job) {
  const meta = [];
  if (job.possible_reply) meta.push(pill("warn", "Possible reply"));
  if (job.priority) meta.push(pill("info", "Your pick", "You asked for this one next"));
  if (job.score) meta.push(h("span", { class: "score", title: "Filter score, out of 100" }, `Score ${job.score}`));
  if (job.fit) meta.push(pill(FIT_TONE[job.fit] || "muted", job.fit === "skip" ? "Skip" : `${capitalized(job.fit)} fit`, job.fit_reason));
  if (job.refresh && job.refresh.state === "running") meta.push(pill("info", "Refreshing resume"));
  if (job.status === "needs_fix") meta.push(pill("bad", "Failed checks"));
  if (job.posting_closed_at) meta.push(pill("bad", "Posting down"));
  if (job.follow_up_due) meta.push(pill("warn", job.next_action === "Follow up" ? "Follow up" : "Next step due", job.next_action));
  if (job.quiet) meta.push(pill("warn", "Gone quiet"));
  if (job.days_since_applied !== null && job.status === "applied") meta.push(h("span", {}, `Applied ${daysAgo(job.days_since_applied)}`));
  if (job.location_kind === "local") meta.push(h("span", {}, "Local"));
  if (job.location_kind === "remote") meta.push(h("span", {}, "Remote"));
  (job.flags || []).forEach((flag) => meta.push(pill("warn", flag)));
  return [...meta, ...freshnessPills(job)];
}

function renderBoard() {
  fill($("board"), COLUMNS.map((col) => {
    const jobs = state.jobs.filter((j) => col.statuses.includes(j.status));
    return h("div", { class: "column" },
      h("h3", {}, col.title, h("span", {}, jobs.length)),
      col.hint ? h("div", { class: "column-hint" }, col.hint) : null,
      h("div", { class: "cards" }, jobs.map((job) => h("button", { class: "card", type: "button", onclick: () => openJob(job.id) },
        h("span", { class: "co" }, job.company), h("span", { class: "ti" }, job.title), h("span", { class: "meta" }, cardMeta(job))))));
  }));
}

// ---- Radar ----

const RADAR_SORTS = {
  priority: (a, b) => b.rank - a.rank,
  newest: (a, b) => (a.age_days ?? Infinity) - (b.age_days ?? Infinity) || b.rank - a.rank,
  score: (a, b) => b.score - a.score || b.rank - a.rank,
};
const RADAR_SHOWS = {
  "": () => true,
  new: (j) => j.is_new,
  promoted: (j) => j.promoted.length,
  clean: (j) => !j.reposts && !j.redates,
  "no-ghost": (j) => !j.ghost_risk,
};

function renderRadar() {
  const tracks = [...new Set(state.jobs.map((j) => j.track).filter(Boolean))].sort();
  const trackSel = $("radar-track");
  const picked = trackSel.value;
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
  $("radar-count").textContent = rows.length > shown.length ? `Showing ${shown.length} of ${rows.length}` : `${rows.length} postings`;
  fill($("radar"),
    h("thead", {}, h("tr", {},
      h("th", { class: "num", title: "Score plus points for a recent posting and for a preferred city or industry, minus a penalty for each repost" }, "Priority"),
      h("th", { class: "num", title: "Filter score, out of 100" }, "Score"),
      ["Company", "Title", "Location", "Track", "Pay", "Posted", "Signals"].map((c) => h("th", {}, c)))),
    h("tbody", {}, shown.length ? shown.map((j) => h("tr", { "data-id": j.id, onclick: () => openJob(j.id) },
      h("td", { class: "num" }, j.rank),
      h("td", { class: "num muted" }, j.score),
      h("td", {}, j.company),
      h("td", {}, h("button", { class: "linkish", type: "button" }, j.title)),
      h("td", {}, j.location || "Not stated"),
      h("td", {}, j.track),
      h("td", {}, j.comp),
      h("td", { class: "nowrap", title: shortDate(j.first_posted_at || j.posted_at) }, daysAgo(j.age_days) || "Unknown"),
      h("td", {}, h("span", { class: "signals" }, freshnessPills(j)))))
      : h("tr", {}, h("td", { colspan: 9, class: "empty" }, "Nothing on the radar matches."))));
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
      : h("tr", {}, h("td", { colspan: 5, class: "empty" }, "Nothing closed out yet."))));
}

function renderSources() {
  fill($("manual-list"), state.manual_check.map((m) => h("li", {},
    safeHref(m.url) ? h("a", { href: m.url, target: "_blank", rel: "noopener noreferrer" }, m.name) : m.name,
    h("span", { class: "muted" }, ` ${m.why}`))));
  const rows = [...state.sources].sort((a, b) => (b.last_error ? 1 : 0) - (a.last_error ? 1 : 0) || (a.company || "").localeCompare(b.company || ""));
  const failing = rows.filter((r) => r.last_error).length;
  $("source-summary").textContent = rows.length
    ? `${rows.length - failing} of ${rows.length} sources working. A failing source is reported here rather than quietly returning nothing.`
    : "No sweep has run yet.";
  fill($("sources"),
    h("thead", {}, h("tr", {}, ["State", "Company", "Source", "Postings", "Last good read"].map((c) => h("th", {}, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {},
      h("td", {}, h("span", { class: `pill ${r.last_error ? "bad" : "good"}` }, r.last_error ? "Failing" : "Working")),
      h("td", {}, r.company),
      h("td", {}, r.last_error ? `${r.source_key}: ${r.last_error}` : r.source_key),
      h("td", { class: "num" }, r.last_count),
      h("td", {}, ago(r.last_ok) || "Never")))));
}

// ---- Settings ----

let settings = null;
let settingsDirty = false;
let collectCities = [];
let collectIndustries = [];

const settingsLines = (text) => text.split("\n").map((line) => line.trim()).filter(Boolean);
const settingsNumber = (input) => (input.value.trim() === "" ? null : Number(input.value));
const onRadar = (name) => (state ? state.jobs.filter((j) => j.status === "new" && j.promoted.includes(name)).length : 0);
const postingCount = (count) => `${count} posting${count === 1 ? "" : "s"} on the radar`;

function settingsField(label, input, hint) {
  return h("label", {}, label, input, hint ? h("span", { class: "muted hint" }, hint) : null);
}

function numberInput(value, placeholder) {
  return h("input", { type: "number", min: "0", max: "50", step: "1", value: value ?? "", placeholder });
}

function removeButton(what, row, list, collect) {
  return h("button", { class: "btn danger", type: "button", "aria-label": `Remove ${what}`, onclick: () => {
    list.splice(list.indexOf(collect), 1);
    row.remove();
    settingsDirty = true;
  } }, "Remove");
}

function cityRow(city, body) {
  const name = h("input", { value: city.name || "", "aria-label": "City name" });
  const points = numberInput(city.points, "Default");
  points.setAttribute("aria-label", "Points");
  const match = h("input", { value: city.match || "", placeholder: "Only if the name isn't enough", "aria-label": "Pattern" });
  const collect = () => ({ name: name.value, points: settingsNumber(points), match: match.value });
  const row = h("tr", {}, h("td", {}, name), h("td", {}, points), h("td", {}, match),
    h("td", { class: "num muted" }, city.name ? onRadar(city.name) : ""), h("td", {}));
  row.lastChild.append(removeButton("this city", row, collectCities, collect));
  collectCities.push(collect);
  body.append(row);
}

function skillsSummary(match) {
  if (!match || !(match.have.length + match.gaps.length)) {
    return h("p", { class: "muted hint" }, "List the skills this industry wants, and saving checks them against your fact bank.");
  }
  return h("div", { class: "skills" },
    h("p", {}, h("strong", {}, `You have ${match.have.length} of ${match.have.length + match.gaps.length}`),
      h("span", { class: "muted" }, " in profile/facts.md, by word match. It doesn't change the ranking or what a resume may claim.")),
    h("div", { class: "signals" }, match.have.map((name) => pill("good", name, "Found in your fact bank")),
      match.gaps.map((name) => pill("muted", name, "Not in your fact bank. If it's true of you, add it to profile/facts.md."))));
}

function industryCard(industry, body, match) {
  const name = h("input", { value: industry.name || "" });
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
  const card = h("div", { class: "panel industry" },
    h("div", { class: "industry-head" }, settingsField("Industry", name), settingsField("Points", points),
      h("span", { class: "muted count" }, industry.name ? postingCount(onRadar(industry.name)) : "")),
    h("div", { class: "industry-lists" },
      settingsField("Words in a posting", terms, "One per line. These are patterns, so \\b marks a word's edge."),
      settingsField("Employers", companies, "One per line. These always count."),
      settingsField("Skills it wants", wants, "One per line. Add \": pattern\" if the name alone won't match your fact bank.")),
    skillsSummary(match));
  card.querySelector(".industry-head").append(removeButton("this industry", card, collectIndustries, collect));
  collectIndustries.push(collect);
  body.append(card);
}

function renderSettings() {
  const promote = settings.promote;
  collectCities = [];
  collectIndustries = [];
  const cityPoints = numberInput(promote.city_points ?? 10);
  const industryPoints = numberInput(promote.industry_points ?? 10);
  const mentions = numberInput(promote.mentions_needed ?? 3);
  $("settings-form").collect = () => ({
    city_points: settingsNumber(cityPoints),
    industry_points: settingsNumber(industryPoints),
    mentions_needed: settingsNumber(mentions),
    cities: collectCities.map((c) => c()),
    industry: collectIndustries.map((c) => c()),
  });
  const cityBody = h("tbody", {});
  const industries = h("div", { class: "industries" });
  fill($("settings-form"),
    h("div", { class: "panel" },
      h("h2", {}, "Preferred cities and industries"),
      h("p", { class: "muted" }, "These change the order on the Radar and in the daily run. They don't change what's kept or tailored, and they can't bring back a posting the filters dropped. Filters and everything else stay in profile/search.toml."),
      h("div", { class: "settings-defaults" },
        settingsField("Points for a city", cityPoints),
        settingsField("Points for an industry", industryPoints),
        settingsField("Mentions needed", mentions, "How often a posting must use an industry's words. At 2, degree lists count."))),
    h("div", { class: "panel" },
      h("h2", {}, "Cities"),
      h("div", { class: "table-wrap" }, h("table", { class: "grid" },
        h("thead", {}, h("tr", {}, ["City", "Points", "Pattern", "On the radar", ""].map((c) => h("th", {}, c)))),
        cityBody)),
      h("button", { class: "btn add-row", type: "button", onclick: () => { cityRow({}, cityBody); settingsDirty = true; } }, "Add a city")),
    h("h2", { class: "settings-heading" }, "Industries"),
    industries,
    h("button", { class: "btn add-row", type: "button", onclick: () => { industryCard({}, industries); settingsDirty = true; } }, "Add an industry"));
  (promote.cities || []).forEach((city) => cityRow(city, cityBody));
  (promote.industry || []).forEach((industry) => industryCard(industry, industries, settings.skills[industry.name]));
  settingsDirty = false;
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

async function saveSettings() {
  $("settings-error").textContent = "";
  $("settings-status").textContent = "";
  try {
    settings = await api("/api/settings", { version: settings.version, promote: $("settings-form").collect() });
    await refresh();
    renderSettings();
    const radar = state.jobs.filter((j) => j.status === "new");
    $("settings-status").textContent = `Saved. ${radar.filter((j) => j.promoted.length).length} of ${radar.length} postings on the radar match.`;
  } catch (err) {
    $("settings-error").textContent = err.message;
  }
}

function render() {
  $("demo-tag").hidden = !state.demo;
  renderSweep();
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
    $("sweep").textContent = `Can't reach the server: ${err.message}`;
  }
}

// ---- Job drawer ----

async function act(id, body) {
  await api(`/api/job/${id}/action`, body);
  await refresh();
  await openJob(id);
}

function actionButtons(job, noteEl) {
  const note = () => noteEl.value.trim();
  const button = (label, body, cls = "btn") => h("button", {
    class: cls, type: "button", onclick: () => act(job.id, { ...body, note: note() }),
  }, label);
  const status = (s) => ({ action: "status", status: s });
  const heard = (kind) => ({ action: "heard_back", kind });
  switch (job.status) {
    case "new":
      return [button("Tailor a resume next", { action: "tailor_next" }, "btn primary"), button("Pass", status("passed"))];
    case "shortlisted":
    case "needs_fix":
      return [button("Tailor this one first", { action: "tailor_next" }, "btn primary"), button("Pass", status("passed"))];
    case "ready":
      return [button("I applied", status("applied"), "btn primary"), button("Pass", status("passed"))];
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
      return [button("Reopen", { action: "reopen" }, "btn primary")];
  }
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
      onclick: () => act(job.id, { action: "dismiss_reply" }) }, "Dismiss")));
}

function checkBlock(job) {
  const result = job.check_result;
  if (!result) return null;
  const list = (items) => h("ul", {}, items.map((item) => h("li", {}, item)));
  const blocks = [];
  if (result.errors && result.errors.length) {
    blocks.push(h("div", { class: "callout bad" }, h("strong", {}, "Fact checker blocked this draft"), list(result.errors)));
  }
  if (result.warnings && result.warnings.length) {
    blocks.push(h("div", { class: "callout" }, h("strong", {}, "Worth a look"), list(result.warnings)));
  }
  if (result.overlap && result.overlap.pct !== null) {
    const missing = result.overlap.missing.length ? ` Not on the resume: ${result.overlap.missing.join(", ")}.` : "";
    blocks.push(h("p", { class: "muted" }, `The resume uses ${result.overlap.pct}% of the skill terms in this posting.${missing}`));
  }
  return blocks;
}

const refreshing = (job) => Boolean(job.refresh && job.refresh.state === "running");

async function startRefresh(job) {
  const question = "Have Claude rewrite this resume from the posting and your fact bank?\n\nIt takes a few minutes and uses your Claude plan. The new version only replaces this one if it passes the fact checker.";
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
      h("p", {}, "This usually takes a few minutes, and you can close this panel meanwhile. The current version stays until the new one passes the fact checker."));
  }
  if (result.state === "failed") {
    return h("div", { class: "callout bad" }, h("strong", {}, `Last refresh failed, ${ago(result.at)}`), h("p", {}, result.detail));
  }
  return h("div", { class: "callout" }, h("strong", {}, `Resume refreshed ${ago(result.at)}`), h("p", {}, result.detail),
    h("p", { class: "muted" }, "Read it through before you send it. The version before this one is in resume.previous.md in its folder."));
}

// Reopening would wipe anything being typed in the panel, so only do it once the result is in.
async function watchRefresh(id) {
  if (openJobId !== id) return;
  try {
    const job = await api(`/api/job/${id}`);
    if (!refreshing(job)) {
      await refresh();
      if (openJobId === id) await openJob(id);
      return;
    }
  } catch (err) {
    // The dashboard may be restarting, so keep waiting.
  }
  refreshWatch = setTimeout(() => watchRefresh(id), 5000);
}

async function openJob(id) {
  let job;
  try {
    job = await api(`/api/job/${id}`);
  } catch (err) {
    return;
  }
  openJobId = id;
  clearTimeout(refreshWatch);
  if (refreshing(job)) refreshWatch = setTimeout(() => watchRefresh(id), 5000);
  const noteEl = h("input", { placeholder: "Add a note to this update (optional)", "aria-label": "Note for this update", style: "width:100%" });
  const notesEl = h("textarea", { rows: 3, "aria-label": "Your notes" });
  notesEl.value = job.notes || "";
  const nextText = h("input", { placeholder: "e.g. Phone screen with the hiring manager", "aria-label": "Next step" });
  nextText.value = job.next_action || "";
  const nextDate = h("input", { type: "date", "aria-label": "Next step date" });
  nextDate.value = job.next_action_date || "";
  const href = safeHref(job.url);
  const pdfs = job.files.filter((f) => f.endsWith(".pdf") || f.endsWith(".docx"));

  const facts = [["Status", job.status.replace("_", " ")], ["Location", job.location || "Not stated"], ["Pay", job.comp],
    ["Track", job.track], ["Fit", job.fit ? `${capitalized(job.fit)}: ${job.fit_reason}` : ""], ["Found", shortDate(job.first_seen)],
    ["Posted", job.posted_at ? shortDate(job.posted_at) : ""],
    ["First posted", job.first_posted_at && job.first_posted_at !== job.posted_at ? `${shortDate(job.first_posted_at)} (${daysAgo(job.age_days)})` : ""],
    ["Listed for", !job.first_posted_at || job.first_posted_at === job.posted_at ? (job.age_days === null ? "" : job.age_days === 0 ? "Posted today" : `${job.age_days} days`) : ""],
    ["Reposted", job.reposts ? `${job.reposts} time${job.reposts > 1 ? "s" : ""}${job.last_reposted_at ? `, last ${shortDate(job.last_reposted_at)}` : ""}` : ""],
    ["Re-dated", job.redates ? `${job.redates} time${job.redates > 1 ? "s" : ""}` : ""],
    ["Applied", job.applied_at ? `${shortDate(job.applied_at)} (${daysAgo(job.days_since_applied)})` : ""],
    ["Heard back", job.response_at ? shortDate(job.response_at) : ""]].filter(([, value]) => value);

  fill($("drawer"),
    h("div", { class: "drawer-head" },
      h("div", {}, h("h2", {}, job.title), h("p", { class: "muted" }, job.company)),
      h("button", { class: "btn", type: "button", onclick: closeDrawer }, "Close")),
    h("div", { class: "row" },
      href ? h("a", { class: "btn", href, target: "_blank", rel: "noopener noreferrer" }, "Open posting") : null,
      pdfs.map((file) => h("a", { class: "btn", href: `/files/${file.split("/").map(encodeURIComponent).join("/")}`, target: "_blank", rel: "noopener" }, file.split("/").pop().replace(/^.*?(?=Resume|Cover_Letter)/, "").replace(/_/g, " "))),
      refreshButton(job),
    ),
    h("div", { id: "refresh-error" }),
    refreshBlock(job),
    job.posting_closed_at ? h("div", { class: "callout bad" }, `This posting came down around ${shortDate(job.posting_closed_at)}.`) : null,
    job.ghost_risk ? h("div", { class: "callout bad" }, h("strong", {}, "Possible ghost job"),
      h("p", {}, `${capitalized(job.ghost_reason)}. A prompt to look closer, not proof: some companies keep real openings up all year. Consider asking a recruiter whether it's actively being filled.`)) : null,
    job.may_be_repost ? h("div", { class: "callout" }, "This Workday link ends in -1 or similar, which often means the requisition has more than one posting. It may have been posted before. This is only a hint, and it doesn't affect priority.") : null,
    freshnessPills(job).length ? h("div", { class: "signals" }, freshnessPills(job)) : null,
    job.status === "ready" ? h("div", { class: "callout" },
      h("strong", {}, "Before you send"),
      h("ul", {}, ["Read it through: you'll be asked about every line.", ...state.before_send].map((item) => h("li", {}, item)))) : null,
    replyBlock(job),
    checkBlock(job),
    h("div", { class: "stack" }, noteEl, h("div", { class: "row" }, actionButtons(job, noteEl))),
    h("dl", { class: "facts" }, facts.flatMap(([key, value]) => [h("dt", {}, key), h("dd", {}, value)])),
    (job.flags.length ? h("div", { class: "callout" }, `Flagged: ${job.flags.join(", ")}`) : null),
    h("div", {}, h("h3", {}, "Next step"), h("div", { class: "stack" }, nextText,
      h("div", { class: "row" }, nextDate, h("button", { class: "btn", type: "button",
        onclick: () => act(job.id, { action: "next_action", text: nextText.value, date: nextDate.value }) }, "Save")))),
    h("div", {}, h("h3", {}, "Your notes"), h("div", { class: "stack" }, notesEl, h("div", { class: "row" },
      h("button", { class: "btn", type: "button", onclick: () => act(job.id, { action: "note", notes: notesEl.value }) }, "Save notes")))),
    job.notes_md ? h("div", {}, h("h3", {}, "Fit and interview notes"), h("div", { class: "prose" }, job.notes_md)) : null,
    job.score_reasons.length ? h("div", {}, h("h3", {}, `Why it scored ${job.score}`), h("p", { class: "muted" }, job.score_reasons.join(" · "))) : null,
    job.freshness_reasons.length ? h("div", {}, h("h3", {}, `Why its priority is ${job.rank}`), h("p", { class: "muted" }, [`Score ${job.score}`, ...job.freshness_reasons].join(" · "))) : null,
    job.description ? h("div", {}, h("h3", {}, "Posting"), h("div", { class: "prose" }, job.description)) : null,
    h("div", {}, h("h3", {}, "Timeline"), h("ul", { class: "timeline" }, job.events.map((e) => h("li", {},
      h("time", {}, shortDate(e.ts)), e.kind.replace("_", " "), e.detail ? h("span", { class: "detail" }, e.detail) : null)))),
  );
  $("drawer").hidden = false;
  $("scrim").hidden = false;
}

function closeDrawer() {
  openJobId = null;
  $("drawer").hidden = true;
  $("scrim").hidden = true;
}

// ---- Wiring ----

document.querySelectorAll(".tabs button").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b === tab)));
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== `view-${tab.dataset.tab}`; });
  if (tab.dataset.tab === "settings" && !settingsDirty) loadSettings();
}));
$("view-settings").addEventListener("input", () => { settingsDirty = true; $("settings-status").textContent = ""; });
$("settings-save").addEventListener("click", saveSettings);
$("settings-discard").addEventListener("click", loadSettings);
window.addEventListener("beforeunload", (e) => { if (settingsDirty) e.preventDefault(); });
["radar-search", "radar-track", "radar-place", "radar-show", "radar-sort"].forEach((id) => $(id).addEventListener("input", renderRadar));
$("scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openJobId) closeDrawer(); });

$("add-open").addEventListener("click", () => { $("add-error").textContent = ""; $("add-dialog").showModal(); });
$("add-cancel").addEventListener("click", () => $("add-dialog").close());
$("add-save").addEventListener("click", async () => {
  const field = (name) => $(`add-${name}`).value;
  try {
    const { id } = await api("/api/jobs", {
      company: field("company"), title: field("title"), url: field("url"), location: field("location"), description: field("description"),
    });
    ["company", "title", "url", "location", "description"].forEach((name) => { $(`add-${name}`).value = ""; });
    $("add-dialog").close();
    await refresh();
    await openJob(id);
  } catch (err) {
    $("add-error").textContent = err.message;
  }
});

refresh();
// Pick up what the morning run does while the page sits open.
setInterval(() => { if (!document.hidden) refresh(); }, 60000);
