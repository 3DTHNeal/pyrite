"use strict";
// The Profile tab: everything Pyrite knows about you and your search, in one place. The hub lists each section with
// its state, what needs you, and every save with the copy it replaced. Each section's editor is its own file in
// /static/profile/, which registers itself with profileStep(). Sections set on the Settings tab point there.
//
// While a new workspace is set up, the same sections are the guided setup: the hub says how far it has got, the rail
// shows it, and each section's footer moves on to the next one.
//
// The server decides what a save may change and which changes need a code. This file only carries the page's edits.
// Loads before app.js, so it uses app.js's helpers (h, fill, api, codePrompt, pill, toast) only once the page is up.

const profileSteps = {};

// A section's editor. def.render(ctx) returns { main, aside } as DOM nodes, aside optional. ctx.data is the profile as
// the server read it, ctx.step that section's entry in the server's list, and ctx.editable is false in the demo.
// ctx.change(changes, count, extra) reports the edited files as { key: whole new text } and how many edits that is, which
// the footer shows and saves; a count of 0 means nothing to save. `extra` goes with the save, such as which gaps it
// answers. After a save or Discard the section is drawn again.
// ctx.memo is the section's own object for its form: it lasts while there are unsaved edits, so drawing the section
// again keeps them, and starts empty after a save or Discard.
// def.readOnly marks a section that only shows what it finds, such as Tools check, so its footer has no Save.
function profileStep(id, def) {
  profileSteps[id] = def;
}

let profileMemo = { step: "" };

// Sends a section's form to the server, which works out the files as a save would leave them. Returns send(edits),
// which waits for typing to pause; `show(result, error)` gets each answer, and only the latest one counts.
function profileDrafter(ctx, show) {
  let timer = null;
  let sent = 0;
  return (edits, now) => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++sent;
      try {
        const result = await api("/api/profile/draft", { step: ctx.step.id, edits, based_on: ctx.data.versions });
        if (mine !== sent) return;
        ctx.change(result.changes, result.count);
        show(result, null);
      } catch (err) {
        if (mine !== sent) return;
        ctx.change({}, 0);
        show(null, err);
      }
    }, now ? 0 : 250);
  };
}

// What a draft would do: why it can't, anything to know first, whether saving needs a code, and each file's diff.
function profileReview(result, err) {
  if (err) {
    return h("div", { class: "callout bad", role: "alert" }, h("b", {}, err.message),
      err.status === 409 ? h("p", {}, h("button", { class: "btn small", type: "button", onclick: () => { profilePending = null; loadProfile(); } }, "Reload")) : null);
  }
  if (!result || !result.count) return h("p", { class: "muted" }, "No changes yet. What you change is shown here before you save it.");
  return h("div", { class: "stack" },
    result.notes.length ? h("div", { class: "callout info" }, h("b", {}, "Before you save"),
      h("ul", {}, result.notes.map((note) => h("li", {}, note)))) : null,
    result.code.length ? h("div", { class: "callout" }, h("b", {}, "Saving asks for a code from this computer, because it will:"),
      h("ul", {}, result.code.map((change) => h("li", {}, change)))) : null,
    h("details", { class: "profile-changes" },
      h("summary", {}, `What changes in your files: ${result.diffs.map((d) => d.path.split("/").pop()).join(", ")}`),
      result.diffs.map((d) => h("div", {}, h("p", { class: "profile-file" }, d.path), profileDiff(d.lines, d.cut)))));
}

// Draws a draft's review into `box`, keeping the file changes open if you had opened them.
function profileShowReview(box, result, err) {
  const was = box.querySelector(".profile-changes");
  fill(box, profileReview(result, err));
  const now = box.querySelector(".profile-changes");
  if (was && was.open && now) now.open = true;
}

// A labelled form field. `input` can be any control; `help` is a line under it.
function profileField(label, input, help) {
  return h("label", { class: "profile-field" }, h("span", {}, label), input, help ? h("small", { class: "muted" }, help) : null);
}

let profileData = null;
let profileAt = ""; // "" for the hub, or the open section's id.
let profilePending = null; // { changes, count } while the open section has edits that aren't saved.
let profileError = "";
const PROFILE_HISTORY_SHOWN = 15;
const PROFILE_STATUS = {
  set: ["good", "set"],
  attention: ["warn", "needs you"],
  not_set: ["", "not set"],
  unknown: ["", "not checked"],
};
const PROFILE_TABS = { facts: "Facts", settings: "Settings" };

// Setup is a guided path through these same sections while a new workspace is being set up. Its progress comes from
// the server, which reads it from the files, so there's nothing here to keep in step.
let profileDone = false; // Setup finished while this page was open, so the hub says so until you hide it.
const profileGuiding = () => Boolean(profileData && profileData.guide && profileData.guide.active);

// Every answer the server gives with the profile in it comes through here, which notices setup finishing: either the
// answer that ended it says so, or the one before said setup was going and this one doesn't.
function profileTake(data) {
  const was = profileGuiding();
  profileData = data;
  if (data.guide && (data.guide.finished || (was && !data.guide.active))) profileDone = true;
  profileRailCount(data.guide);
}

// The app rail's Profile count: how many required sections are set while setup is going, and nothing after. A save
// here updates it at once, rather than at the dashboard's next refresh.
function profileRailCount(guide) {
  const el = document.getElementById("count-profile");
  if (!el) return;
  const going = guide && guide.active ? guide : null;
  el.textContent = going ? `${going.set}/${going.required}` : "";
  el.className = `rail-count${going ? " hot" : ""}`;
  el.title = going ? `Setup: ${going.set} of ${profileCount(going.required, "required section")} set` : "";
}

const profileSection = (id) => (profileData ? profileData.steps.find((s) => s.id === id) : null);
const profileBeside = (step, by) => {
  const at = profileData.steps.findIndex((s) => s.id === step.id);
  return at < 0 ? null : profileData.steps[at + by] || null;
};
const profileCount = (count, one, many) => `${count} ${count === 1 ? one : many || `${one}s`}`;
const profileWhen = (iso) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

async function loadProfile() {
  try {
    profileTake(await api("/api/profile"));
    profileError = "";
  } catch (err) {
    profileError = err.message;
  }
  renderProfile();
}

// Called by showTab with whatever follows "profile/" in the address. Returns the section that's open afterwards, which
// is the one already open when you choose to keep unsaved edits.
function profileShow(at) {
  // Before the first load the section can't be looked up yet, so it's taken on trust until renderProfile draws it.
  const target = (profileSection(at) || !profileData) ? at : "";
  if (target !== profileAt && profilePending) {
    const leave = window.confirm(`Leave without saving? ${profileCount(profilePending.count, "change")} to this section will be lost.`);
    if (!leave) return profileAt;
    profilePending = null;
  }
  const moved = target !== profileAt;
  profileAt = target;
  if (!profilePending) loadProfile();
  else renderProfile();
  if (moved) window.scrollTo(0, 0);
  return profileAt;
}

function profileGo(at) {
  location.hash = at ? `#profile/${at}` : "#profile";
}

function renderProfile() {
  const root = $("profile-view");
  if (!root) return;
  $("profile-error").textContent = profileError;
  if (!profileData) {
    fill(root, h("p", { class: "muted" }, profileError ? "" : "Loading…"));
    return;
  }
  const step = profileSection(profileAt);
  if (step) renderProfileStep(root, step);
  else {
    profileAt = "";
    renderProfileHub(root);
  }
}

// ---- The hub ----

function profileStatusPill(step) {
  const [tone, label] = PROFILE_STATUS[step.status] || ["", step.status];
  return pill(step.status === "not_set" && step.required ? "warn" : tone, label);
}

function profileNeeds() {
  const items = profileData.needs;
  const list = items.length ? items.map((item) => {
    const step = profileSection(item.step);
    return h("li", { class: `profile-need ${item.severity}` },
      h("span", { class: "visually-hidden" }, item.severity === "bad" ? "Important: " : ""),
      h("div", {}, h("b", {}, item.title), h("small", {}, item.detail)),
      step ? h("button", { class: `btn small${item.severity === "bad" ? " primary" : ""}`, type: "button", onclick: () => profileGo(step.id) },
        `Open ${step.label}`) : null);
  }) : [h("li", { class: "profile-need info" }, h("div", {}, h("b", {}, "Nothing needs you."),
    h("small", {}, "Pyrite lists things here when setup isn't finished or a file can't be read as it should.")))];
  return h("section", { class: "panel profile-needs", "aria-label": "Needs you" },
    h("h2", {}, `Needs you · ${items.length}`), h("ul", {}, list));
}

// A section set on the Settings tab for good opens it there, as a link would. The rest open here.
function profileOpen(step) {
  if (step.settings && !profileSteps[step.id]) showTab(step.fallback);
  else profileGo(step.id);
}

function profileCards() {
  const groups = [];
  for (const step of profileData.steps) {
    let group = groups.find((g) => g.name === step.group);
    if (!group) groups.push(group = { name: step.group, steps: [] });
    group.steps.push(step);
  }
  return groups.map((group) => h("section", { class: "profile-group", "aria-label": group.name },
    h("h3", {}, group.name),
    h("div", { class: "profile-cards" }, group.steps.map((step) => h("button", {
      class: "profile-card", type: "button", onclick: () => profileOpen(step),
    },
    h("span", { class: "top" }, h("b", {}, step.label), profileStatusPill(step)),
    h("span", { class: "sum" }, step.summary),
    h("small", {}, step.settings ? `On the Settings tab, under ${step.settings} →`
      : step.changed ? `Changed ${profileWhen(step.changed)}` : step.required ? "Required" : "Optional"))))));
}

// Several files saved together share a stamp, so they show as one save.
function profileSaves(entries) {
  const saves = [];
  for (const entry of entries) {
    const last = saves[saves.length - 1];
    if (last && last.stamp === entry.stamp) last.files.push(entry);
    else saves.push({ stamp: entry.stamp, at: entry.at, reason: entry.reason, files: [entry] });
  }
  return saves;
}

function profileDiff(lines, cut) {
  // Each line is its own block, so it needs no line break of its own.
  return h("pre", { class: "profile-diff" }, lines.map((line) => h("span", {
    class: line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : "",
  }, line || " ")), cut ? h("span", { class: "hunk" }, `… and ${profileCount(cut, "more line")}`) : null);
}

// What putting back one file's earlier copy would change, and the button that does it. A save that changed other files
// too says so, and offers to put the whole save back, since one file alone can leave the others out of step with it.
async function profileShowKept(entry, box, save) {
  fill(box, h("p", { class: "muted" }, "Loading…"));
  let kept;
  try {
    kept = await api(`/api/profile/kept?key=${encodeURIComponent(entry.key)}&stamp=${encodeURIComponent(entry.stamp)}`);
  } catch (err) {
    fill(box, h("p", { class: "error", role: "alert" }, err.message));
    return;
  }
  const error = h("p", { class: "error", role: "alert" });
  const put = h("button", { class: "btn small", type: "button", disabled: !profileData.editable || kept.same }, `Put back ${entry.path}`);
  const actions = h("div", { class: "part-actions" }, put,
    kept.same ? h("span", { class: "muted" }, "The file is already the same as this copy.")
      : h("span", { class: "muted" }, profileData.editable ? "Lines marked + come back and lines marked − go. The file as it is now is kept in History too."
        : "Putting back is off in the demo."));
  put.addEventListener("click", () => profilePutBack({ key: entry.key, stamp: entry.stamp }, entry.path, put, actions, error));
  const others = save.files.filter((file) => file.key !== entry.key);
  let whole = null;
  if (others.length) {
    const names = others.map((file) => file.path.split("/").pop()).join(", ");
    const all = save.files.every((file) => file.kept);
    const button = h("button", { class: "btn small", type: "button", disabled: !profileData.editable || !all }, "Put back this whole save");
    whole = h("div", { class: "callout" },
      h("p", {}, `This save also changed ${names}. Putting back ${entry.path.split("/").pop()} alone leaves ${others.length > 1 ? "those" : "that"} as ${others.length > 1 ? "they are" : "it is"} now, which can leave your files disagreeing, such as a name changed back in one but not the other.`),
      h("div", { class: "part-actions" }, button, all ? null : h("span", { class: "muted" }, "Not every file from this save is still kept.")));
    button.addEventListener("click", () => profilePutBack({ stamp: entry.stamp, whole: true }, "this save's files", button, whole, error));
  }
  fill(box, kept.same ? null : profileDiff(kept.diff, kept.cut), actions, whole, error);
}

// `what` is what's being put back, by its copy's stamp and either one file's key or the whole save.
async function profilePutBack(what, named, button, actions, error) {
  error.textContent = "";
  const body = { ...what, based_on: profileData.versions };
  const done = (data) => {
    profileTake(data);
    toast(`Put back ${named}. What ${what.whole ? "they" : "it"} replaced is in History.`);
    renderProfile();
  };
  button.disabled = true;
  try {
    done(await api("/api/profile/put-back", body));
  } catch (err) {
    if (err.status !== 428) {
      error.textContent = err.message;
      button.disabled = false;
      if (err.status === 409) actions.append(h("button", { class: "btn small", type: "button", onclick: loadProfile }, "Reload"));
      return;
    }
    // The copy would loosen a check, such as an older terms file with a term since removed.
    const prompt = codePrompt(err.data,
      async (requestId, code) => done(await api("/api/profile/put-back", { ...body, request_id: requestId, code })),
      () => { prompt.remove(); button.disabled = false; });
    actions.after(prompt);
  }
}

function profileHistory() {
  const saves = profileSaves(profileData.history || []);
  const shown = saves.slice(0, PROFILE_HISTORY_SHOWN);
  const rows = shown.map((save) => {
    const box = h("div", { class: "profile-kept" });
    return h("li", {},
      h("div", { class: "profile-save" },
        h("time", { datetime: save.at }, profileWhen(save.at)),
        h("span", {}, save.reason),
        h("span", { class: "files" }, save.files.map((entry) => entry.kept
          ? h("button", { class: "btn small", type: "button", "aria-expanded": "false", onclick: (e) => {
            const open = e.currentTarget.getAttribute("aria-expanded") === "true";
            box.querySelectorAll(":scope > *").forEach((el) => el.remove());
            box.closest("li").querySelectorAll(".files .btn").forEach((b) => b.setAttribute("aria-expanded", "false"));
            if (!open) {
              e.currentTarget.setAttribute("aria-expanded", "true");
              profileShowKept(entry, box, save);
            }
          } }, entry.path.split("/").pop())
          : h("span", { class: "muted", title: "Only the latest copies of each file are kept." }, `${entry.path.split("/").pop()} (not kept)`)))),
      box);
  });
  return h("section", { class: "panel profile-history", "aria-label": "History" },
    h("h2", {}, "History"),
    h("p", { class: "muted" }, "Every save keeps the files as they were before it. Pick a file to see what putting it back would change."),
    rows.length ? h("ol", {}, rows) : h("p", { class: "empty" }, "No saves yet."),
    saves.length > shown.length ? h("p", { class: "muted" }, `${profileCount(saves.length - shown.length, "older save")} not shown.`) : null);
}

// How many required sections are set, as a bar. The numbers are in the text beside it too.
function profileProgress(guide) {
  const share = guide.required ? Math.round((guide.set / guide.required) * 100) : 100;
  return h("div", {
    class: "profile-progress", role: "progressbar", "aria-label": "Required sections set",
    "aria-valuemin": "0", "aria-valuemax": String(guide.required), "aria-valuenow": String(guide.set),
  }, h("i", { style: `width: ${share}%` }));
}

const profileProgressLine = (guide) => `${guide.set} of ${profileCount(guide.required, "required section")} set`;

// While a new workspace is set up, the hub opens on where setup has got to and the section to do next. Once it's
// done, it says so once, with the first board check a button away.
function profileSetupPanel() {
  const guide = profileData.guide;
  if (profileDone) {
    const blocked = typeof state !== "undefined" && state && state.not_ready ? state.not_ready.sweep : null;
    return h("section", { class: "panel profile-setup done", "aria-label": "Setup" },
      h("div", { class: "profile-setup-head" }, pill("good", "Setup done"), h("h2", {}, "Every required section is set")),
      h("p", {}, "Pyrite can find, rank and draft for you now. Everything you set up stays here on Profile, which is also where "
        + "Pyrite asks when it needs a decision. From here on, a change that lets drafts say more asks for a code sent to "
        + "this computer's notifications."),
      h("div", { class: "row" },
        h("button", { class: "btn primary", type: "button", disabled: Boolean(blocked), title: blocked || null,
          onclick: () => { profileDone = false; startRun("sweep"); showTab("todo"); } }, "Check the boards now"),
        h("button", { class: "btn", type: "button", onclick: () => { profileDone = false; showTab("todo"); } }, "Open To do"),
        h("button", { class: "btn", type: "button", onclick: () => { profileDone = false; renderProfile(); } }, "Hide")),
      blocked ? h("p", { class: "muted" }, blocked) : null);
  }
  if (!profileGuiding()) return null;
  const next = profileSection(guide.next) || profileData.steps.find((s) => s.status !== "set");
  return h("section", { class: "panel profile-setup", "aria-label": "Setup" },
    h("div", { class: "profile-setup-head" }, h("h2", {}, "Setting up"), h("span", { class: "muted" }, profileProgressLine(guide))),
    profileProgress(guide),
    h("p", {}, "Setup goes through the sections below in order, and the required ones are marked. Each says why it matters "
      + "and what it writes. Leave whenever you like: what's done is read from your files, so setup picks up where they are."),
    next ? h("div", { class: "row" }, h("button", { class: "btn primary", type: "button", onclick: () => profileGo(next.id) },
      guide.set ? `Continue setup: ${next.label}` : `Start setup: ${next.label}`)) : null);
}

function renderProfileHub(root) {
  fill(root,
    h("div", { class: "profile-top" },
      h("div", {}, h("h2", {}, "Profile"),
        h("p", { class: "muted" }, profileData.editable
          ? "Everything Pyrite knows about you and your search. Changes apply to the next draft and the next board check."
          : "Everything Pyrite knows about the demo's fictional candidate. Saving is off in the demo."))),
    profileSetupPanel(),
    profileNeeds(),
    h("div", { class: "profile-groups" }, profileCards()),
    profileHistory());
}

// ---- One section ----

function profileRail(current) {
  const select = h("select", { class: "profile-rail-select", "aria-label": "Section" },
    h("option", { value: "" }, "← Profile"),
    profileData.steps.map((step) => h("option", { value: step.id, selected: step.id === current.id }, `${step.group}: ${step.label}`)));
  select.addEventListener("change", () => {
    profileGo(select.value);
    select.value = profileAt; // Put back if you chose to stay.
  });
  const groups = [];
  for (const step of profileData.steps) {
    if (!groups.length || groups[groups.length - 1].name !== step.group) groups.push({ name: step.group, steps: [] });
    groups[groups.length - 1].steps.push(step);
  }
  // While setting up, the rail shows how far setup has got and which sections can wait.
  const guiding = profileGuiding();
  return h("nav", { class: "profile-rail", "aria-label": guiding ? "Setup sections" : "Profile sections" },
    h("button", { class: "btn small profile-back", type: "button", onclick: () => profileGo("") }, "← Profile"),
    guiding ? h("div", { class: "profile-rail-progress" }, h("small", {}, profileProgressLine(profileData.guide)), profileProgress(profileData.guide)) : null,
    select,
    groups.map((group) => h("div", { class: "profile-rail-group" },
      h("p", {}, group.name),
      h("ol", {}, group.steps.map((step) => h("li", {}, h("button", {
        class: `profile-rail-step ${step.status}${step.id === current.id ? " current" : ""}`, type: "button",
        "aria-current": step.id === current.id ? "step" : null, onclick: () => profileGo(step.id),
      }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", {}, step.label),
      guiding && !step.required ? h("span", { class: "opt" }, "optional") : null,
      h("span", { class: "visually-hidden" }, `, ${PROFILE_STATUS[step.status] ? PROFILE_STATUS[step.status][1] : step.status}`))))))));
}

// A section whose editor isn't built yet: what it holds now, and where to change it until then.
function profileFallback(step) {
  // A fallback may name a section of its tab, as settings/ranking does.
  const tab = PROFILE_TABS[String(step.fallback || "").split("/")[0]];
  if (step.settings) {
    // Set on the Settings tab for good, so it's a way there rather than a section waiting for its editor.
    return h("div", { class: "stack profile-fallback" },
      h("p", {}, h("b", {}, "Now: "), step.summary),
      h("p", {}, step.meanwhile),
      h("div", {}, h("button", { class: "btn primary", type: "button", onclick: () => showTab(step.fallback) },
        `Open ${step.settings} on the Settings tab`)));
  }
  return h("div", { class: "stack profile-fallback" },
    h("p", {}, h("b", {}, "Now: "), step.summary),
    h("div", { class: "callout info" }, h("b", {}, "This section's editor isn't built yet."), h("p", {}, step.meanwhile)),
    tab ? h("div", {}, h("button", { class: "btn", type: "button", onclick: () => showTab(step.fallback) }, `Open the ${tab} tab`)) : null);
}

function profileFoot(step, built) {
  if (profileGuiding()) return profileSetupFoot(step, built);
  const foot = h("div", { class: "profile-foot" });
  const status = h("span", { class: "profile-dirty", "aria-live": "polite" });
  const error = h("p", { class: "error", role: "alert" });
  const back = h("button", { class: "btn", type: "button", onclick: () => profileGo("") }, "← Profile");
  const discard = h("button", { class: "btn", type: "button", onclick: () => { profilePending = null; renderProfile(); } }, "Discard");
  const save = h("button", { class: "btn primary", type: "button" }, profileData.editable ? "Save changes" : "Saving is off in the demo");
  const update = () => {
    const count = profilePending ? profilePending.count : 0;
    status.textContent = count ? `${profileCount(count, "unsaved change")}` : built ? "No changes" : "Nothing to save here";
    status.classList.toggle("dirty", Boolean(count));
    discard.hidden = !count;
    save.disabled = !count || !profileData.editable;
  };
  save.addEventListener("click", () => profileSave(step, foot, save, error));
  foot.update = update;
  update();
  fill(foot, h("div", { class: "row" }, back, h("span", { class: "spacer" }), status, built ? discard : null, built ? save : null), error);
  return foot;
}

// The footer while setting up: back to the section before, and one button on to the next that saves first when
// there's something to save. An optional section not set yet can be skipped. A required one can be left too, since
// setup comes back to it, but it can't be finished without it.
function profileSetupFoot(step, built) {
  const foot = h("div", { class: "profile-foot" });
  const status = h("span", { class: "profile-dirty", "aria-live": "polite" });
  const error = h("p", { class: "error", role: "alert" });
  const before = profileBeside(step, -1);
  const after = profileBeside(step, 1);
  const onward = () => profileGo(profileDone || !after ? "" : after.id);
  const back = h("button", { class: "btn", type: "button", onclick: () => profileGo(before ? before.id : "") },
    before ? `← ${before.label}` : "← Profile");
  const discard = h("button", { class: "btn", type: "button", onclick: () => { profilePending = null; renderProfile(); } }, "Discard");
  const go = h("button", { class: "btn primary", type: "button" });
  const update = () => {
    const count = profilePending ? profilePending.count : 0;
    const skip = !step.required && step.status !== "set";
    status.textContent = count ? profileCount(count, "unsaved change")
      : step.required && step.status !== "set" ? "Required: setup comes back to this until it's set." : "";
    status.classList.toggle("dirty", Boolean(count));
    discard.hidden = !count;
    go.textContent = count ? (profileData.editable ? (after ? "Save and continue" : "Save and finish") : "Saving is off in the demo")
      : skip ? "Skip for now" : after ? "Continue" : "Finish";
    go.classList.toggle("primary", Boolean(count) || !skip);
    go.disabled = Boolean(count) && !profileData.editable;
  };
  go.addEventListener("click", () => (profilePending ? profileSave(step, foot, go, error, onward) : onward()));
  foot.update = update;
  update();
  fill(foot, h("div", { class: "row" }, back, h("span", { class: "spacer" }), status, built ? discard : null, go), error);
  return foot;
}

// `then` runs after a save instead of drawing the section again, as Save and continue moves on to the next one.
async function profileSave(step, foot, button, error, then) {
  if (!profilePending) return;
  error.textContent = "";
  foot.querySelectorAll(".code-prompt, .profile-conflict").forEach((el) => el.remove());
  const body = {
    ...profilePending.extra, changes: profilePending.changes, based_on: profileData.versions, step: step.id,
    reason: `${step.label}: ${profileCount(profilePending.count, "change")}`,
  };
  const saved = (data) => {
    profileTake(data);
    profilePending = null;
    toast("Saved. The files as they were before are in History.");
    if (then) then();
    else renderProfile();
  };
  button.disabled = true;
  try {
    saved(await api("/api/profile", body));
  } catch (err) {
    if (err.status === 428) {
      // It loosens a check: the edits stay as they are until the code confirms them.
      const prompt = codePrompt(err.data,
        async (requestId, code) => saved(await api("/api/profile", { ...body, request_id: requestId, code })),
        () => { prompt.remove(); button.disabled = false; });
      foot.append(prompt);
    } else if (err.status === 409) {
      foot.append(h("div", { class: "callout profile-conflict" },
        h("b", {}, err.message), " ",
        h("button", { class: "btn small", type: "button", onclick: () => { profilePending = null; loadProfile(); } }, "Reload and lose these edits")));
      button.disabled = false;
    } else {
      error.textContent = err.message;
      button.disabled = false;
    }
  }
}

function renderProfileStep(root, step) {
  const def = profileSteps[step.id];
  // A section that only shows what it finds, such as Tools check, has nothing to save.
  const foot = profileFoot(step, Boolean(def) && !def.readOnly);
  let drawn = { main: profileFallback(step) };
  if (def) {
    if (!profilePending || profileMemo.step !== step.id) profileMemo = { step: step.id };
    const ctx = {
      data: profileData, step, editable: profileData.editable, memo: profileMemo,
      change(changes, count, extra) {
        profilePending = count ? { changes, count, extra: extra || {} } : null;
        foot.update();
      },
    };
    try {
      drawn = def.render(ctx);
    } catch (err) {
      drawn = { main: h("p", { class: "error", role: "alert" }, `This section couldn't be shown: ${err.message}`) };
    }
  }
  const heading = h("h2", { tabindex: "-1" }, step.label);
  // A section without its own editor already says how to change it by hand, so only the others add that here.
  const byHand = def && step.meanwhile ? h("p", { class: "muted" }, step.meanwhile) : null;
  fill(root, h("div", { class: "profile-step" },
    profileRail(step),
    h("div", { class: "profile-stage" },
      h("header", { class: "profile-stage-head" },
        profileGuiding() ? h("p", { class: "eyebrow" }, `Setup · ${step.group} · ${step.required ? "required" : "optional"}`) : null,
        heading, h("p", { class: "muted" }, step.why)),
      h("div", { class: `profile-work${drawn.aside ? "" : " wide"}` },
        h("div", { class: "profile-main" }, drawn.main),
        drawn.aside ? h("aside", { class: "profile-aside", "aria-live": "polite" }, drawn.aside) : null),
      step.writes.length || byHand ? h("details", { class: "profile-writes" }, h("summary", {}, "Where this goes"),
        step.writes.length ? h("ul", {}, step.writes.map((line) => h("li", {}, line))) : null, byHand) : null,
      foot)));
  // A new section's heading takes focus, so a screen reader announces where you are.
  if (document.activeElement === document.body || root.contains(document.activeElement) || !document.activeElement) heading.focus({ preventScroll: true });
}
