"use strict";
// The Profile tab: everything Pyrite knows about you and your search, in one place. The hub lists each section with
// its state, what needs you, and every save with the copy it replaced. Each section's editor is its own file in
// /static/profile/, which registers itself with profileStep(). Sections without one yet point to the Facts or Settings
// tab, which stay as they were.
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

const profileSection = (id) => (profileData ? profileData.steps.find((s) => s.id === id) : null);
const profileCount = (count, one, many) => `${count} ${count === 1 ? one : many || `${one}s`}`;
const profileWhen = (iso) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

async function loadProfile() {
  try {
    profileData = await api("/api/profile");
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
      class: "profile-card", type: "button", onclick: () => profileGo(step.id),
    },
    h("span", { class: "top" }, h("b", {}, step.label), profileStatusPill(step)),
    h("span", { class: "sum" }, step.summary),
    h("small", {}, step.changed ? `Changed ${profileWhen(step.changed)}` : step.required ? "Required" : "Optional"))))));
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
    profileData = data;
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

function renderProfileHub(root) {
  fill(root,
    h("div", { class: "profile-top" },
      h("div", {}, h("h2", {}, "Profile"),
        h("p", { class: "muted" }, profileData.editable
          ? "Everything Pyrite knows about you and your search. Changes apply to the next draft and the next board check."
          : "Everything Pyrite knows about the demo's fictional candidate. Saving is off in the demo."))),
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
  return h("nav", { class: "profile-rail", "aria-label": "Profile sections" },
    h("button", { class: "btn small profile-back", type: "button", onclick: () => profileGo("") }, "← Profile"),
    select,
    groups.map((group) => h("div", { class: "profile-rail-group" },
      h("p", {}, group.name),
      h("ol", {}, group.steps.map((step) => h("li", {}, h("button", {
        class: `profile-rail-step ${step.status}${step.id === current.id ? " current" : ""}`, type: "button",
        "aria-current": step.id === current.id ? "step" : null, onclick: () => profileGo(step.id),
      }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", {}, step.label),
      h("span", { class: "visually-hidden" }, `, ${PROFILE_STATUS[step.status] ? PROFILE_STATUS[step.status][1] : step.status}`))))))));
}

// A section whose editor isn't built yet: what it holds now, and where to change it until then.
function profileFallback(step) {
  const tab = PROFILE_TABS[step.fallback];
  return h("div", { class: "stack profile-fallback" },
    h("p", {}, h("b", {}, "Now: "), step.summary),
    h("div", { class: "callout info" }, h("b", {}, "This section's editor isn't built yet."), h("p", {}, step.meanwhile)),
    tab ? h("div", {}, h("button", { class: "btn", type: "button", onclick: () => showTab(step.fallback) }, `Open the ${tab} tab`)) : null);
}

function profileFoot(step, built) {
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

async function profileSave(step, foot, button, error) {
  if (!profilePending) return;
  error.textContent = "";
  foot.querySelectorAll(".code-prompt, .profile-conflict").forEach((el) => el.remove());
  const body = {
    ...profilePending.extra, changes: profilePending.changes, based_on: profileData.versions, step: step.id,
    reason: `${step.label}: ${profileCount(profilePending.count, "change")}`,
  };
  const saved = (data) => {
    profileData = data;
    profilePending = null;
    toast("Saved. The files as they were before are in History.");
    renderProfile();
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
  const foot = profileFoot(step, Boolean(def));
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
  fill(root, h("div", { class: "profile-step" },
    profileRail(step),
    h("div", { class: "profile-stage" },
      h("header", { class: "profile-stage-head" }, heading, h("p", { class: "muted" }, step.why)),
      h("div", { class: `profile-work${drawn.aside ? "" : " wide"}` },
        h("div", { class: "profile-main" }, drawn.main),
        drawn.aside ? h("aside", { class: "profile-aside", "aria-live": "polite" }, drawn.aside) : null),
      step.writes.length ? h("details", { class: "profile-writes" }, h("summary", {}, "Where this goes"),
        h("ul", {}, step.writes.map((line) => h("li", {}, line)))) : null,
      foot)));
  // A new section's heading takes focus, so a screen reader announces where you are.
  if (document.activeElement === document.body || root.contains(document.activeElement) || !document.activeElement) heading.focus({ preventScroll: true });
}
