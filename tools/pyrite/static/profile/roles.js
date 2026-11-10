"use strict";
// Roles you want: the kinds of role Pyrite keeps from the boards. Each is a [[track]] in search.toml with plain job
// titles, and any patterns written by hand, which stay as they are. [scoring] holds the words that make a title senior,
// the titles never kept, and the points for skills and flags. What drafts lead with for each goes in run-notes.md, as
// does Roles so far, a line of prose about the kinds of role you've gone for. A role type can be limited to some of the
// industries under [[promote.industry]], picked from the names there.
// Every change is scored against your prospects by the real scorer, so the section shows what would be dropped first.

profileStep("roles", {
  render(ctx) {
    const data = ctx.data.roles;
    const memo = ctx.memo;
    const off = !ctx.editable;
    if (!memo.form) {
      memo.form = {
        tracks: data.tracks.map((t) => ({ index: t.index, name: t.name, titles: [...t.titles], patterns: [...t.patterns],
          needs_level: t.needs_level, industries: [...t.industries], emphasis: t.emphasis, removed: false })),
        roles_so_far: data.roles_so_far.text,
        level_top: [...data.level_top], level_mid: [...data.level_mid], exclude_titles: [...data.exclude_titles],
        keywords: data.keywords.map((row) => [...row]), flags: data.flags.map((row) => [...row]),
        test: "",
      };
    }
    const form = memo.form;
    const original = (index) => data.tracks.find((t) => t.index === index) || { titles: [], patterns: [], industries: [] };
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const prospects = h("div", { class: "stack", "aria-live": "polite" });
    const tested = h("div", { "aria-live": "polite" });
    let last = null;
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) {
        last = result.preview;
        showProspects();
        showTest();
      }
    });
    const changed = (now) => send({
      tracks: form.tracks.filter((t) => !t.removed).map((t) => ({ index: t.index, name: t.name, titles: t.titles,
        patterns: t.patterns, needs_level: t.needs_level, industries: t.industries, emphasis: t.emphasis })),
      roles_so_far: form.roles_so_far,
      level_top: form.level_top, level_mid: form.level_mid, exclude_titles: form.exclude_titles,
      keywords: form.keywords, flags: form.flags, test: form.test,
    }, now);

    // A list of words or patterns as chips: what's there, what you've added, and what you've taken off, which can be
    // put back. Returns the box and a function that draws it again.
    const chips = (current, before, opts) => {
      const box = h("div", { class: "profile-chips" });
      const draw = () => {
        const shown = [...before, ...current.filter((v) => !before.includes(v))];
        fill(box, shown.length ? shown.map((value) => {
          const isNew = !before.includes(value);
          const going = !current.includes(value);
          const label = going ? `Keep ${value}` : isNew ? `Don't add ${value}` : `Take off ${value}`;
          return h("span", { class: `profile-chip${opts.pattern ? " pattern" : ""}${isNew ? " new" : ""}${going ? " going" : ""}` },
            h("span", {}, value),
            h("button", { type: "button", "aria-label": label, title: label, disabled: off, onclick: () => {
              if (going) current.push(value);
              else current.splice(current.indexOf(value), 1);
              draw();
              if (opts.onChange) opts.onChange();
              changed(true);
            } }, "✕"));
        }) : h("span", { class: "muted" }, opts.empty));
      };
      draw();
      return [box, draw];
    };
    const adder = (placeholder, button, onAdd) => {
      const field = h("input", { type: "text", placeholder, "aria-label": placeholder, disabled: off });
      const go = () => {
        const value = field.value.trim();
        if (!value) return;
        onAdd(value);
        field.value = "";
        field.focus();
      };
      field.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
      return h("div", { class: "profile-add" }, field, h("button", { class: "btn", type: "button", disabled: off, onclick: go }, button));
    };
    // A chip list with its adder underneath.
    const editable = (current, before, opts) => {
      const [box, draw] = chips(current, before, opts);
      return h("div", { class: "stack" }, box, adder(opts.placeholder, opts.button || "Add", (value) => {
        if (!current.includes(value)) current.push(value);
        draw();
        changed(true);
      }));
    };

    // ---- Role types ----
    const list = h("div", { class: "stack" });
    let focusNew = null;
    const trackCard = (track, at, live) => {
      const was = original(track.index);
      if (track.removed) {
        return h("div", { class: "callout" }, h("span", {}, `${track.name || "This role type"} will be taken off when you save. `),
          h("button", { class: "btn small", type: "button", disabled: off, onclick: () => { track.removed = false; drawTracks(); changed(true); } }, "Keep it"));
      }
      const name = h("input", { type: "text", value: track.name, "aria-label": "Role type", placeholder: "A name, such as Data platform",
        class: "profile-employer-name", disabled: off });
      name.addEventListener("input", () => { track.name = name.value; changed(); });
      if (focusNew === track) setTimeout(() => name.focus());
      const move = (by, label, text) => h("button", { class: "btn small", type: "button", "aria-label": `${label} ${track.name}`, title: label,
        disabled: off || (by < 0 ? live === 0 : live === form.tracks.filter((t) => !t.removed).length - 1), onclick: () => {
          const shown = form.tracks.filter((t) => !t.removed);
          const other = shown[live + by];
          const a = form.tracks.indexOf(track);
          const b = form.tracks.indexOf(other);
          [form.tracks[a], form.tracks[b]] = [form.tracks[b], form.tracks[a]];
          drawTracks();
          changed(true);
        } }, text);
      const remove = h("button", { class: "btn small danger", type: "button", "aria-label": `Take off ${track.name || "this role type"}`,
        title: "Take it off", disabled: off, onclick: () => {
          if (track.index === null) form.tracks.splice(form.tracks.indexOf(track), 1);
          else track.removed = true;
          drawTracks();
          changed(true);
        } }, "✕");
      const level = h("input", { type: "checkbox", checked: track.needs_level, disabled: off });
      level.addEventListener("change", () => { track.needs_level = level.checked; changed(true); });
      const emphasis = h("input", { type: "text", value: track.emphasis, disabled: off,
        placeholder: "Such as: the evaluation harness and the pilot results lead" });
      emphasis.addEventListener("input", () => { track.emphasis = emphasis.value; changed(); });
      const hasPatterns = track.patterns.length || was.patterns.length;
      // Picked from the industries under Settings › Cities and industries, the only names the scorer can match.
      const industries = () => {
        const names = data.industry_names;
        if (!names.length && !track.industries.length && !was.industries.length) return null;
        const pick = h("select", { "aria-label": `Add an industry to ${track.name || "this role type"}`, disabled: off });
        const warn = h("div", {});
        // The menu offers the industries not picked yet. A name no industry has, written by hand, can only be taken off.
        const refresh = () => {
          const left = names.filter((n) => !track.industries.includes(n));
          fill(pick, h("option", { value: "" }, !names.length ? "No industries yet" : left.length ? "Add an industry…" : "Every industry is added"),
            left.map((n) => h("option", { value: n }, n)));
          pick.disabled = off || !left.length;
          const unknown = track.industries.filter((n) => !names.includes(n));
          fill(warn, unknown.length ? h("small", { class: "error" }, `${unknown.join(", ")} ${unknown.length === 1 ? "isn't an industry" : "aren't industries"} under Settings › Cities and industries, so this role type takes no posting for ${unknown.length === 1 ? "it" : "them"}.`) : null);
        };
        const [box, draw] = chips(track.industries, track.index === null ? [] : was.industries,
          { empty: "Any industry.", onChange: refresh });
        pick.addEventListener("change", () => {
          if (pick.value && !track.industries.includes(pick.value)) track.industries.push(pick.value);
          draw();
          refresh();
          changed(true);
        });
        refresh();
        // Not a <label>, which would pass a click on its text to the first chip's button.
        return h("div", { class: "profile-field" }, h("span", {}, "Only in these industries"), box, pick, warn,
          h("small", { class: "muted" }, names.length
            ? "With any picked, this role type takes only postings in them, judged as Cities and industries judges them. With none, it takes any."
            : "Add industries under Settings › Cities and industries to pick from them here."));
      };
      return h("div", { class: "profile-employer" },
        h("div", { class: "row" }, h("small", { class: "muted" }, `${live + 1}.`), name, h("span", { class: "spacer" }),
          move(-1, "Move up", "↑"), move(1, "Move down", "↓"), remove),
        profileField("Job titles", editable(track.titles, track.index === null ? [] : was.titles,
          { placeholder: "A job title, such as data engineer", empty: "No plain titles yet." }),
        "Each matches as whole words in any case, anywhere in a posting's title."),
        hasPatterns ? profileField("Patterns", chips(track.patterns, track.index === null ? [] : was.patterns,
          { pattern: true, empty: "No patterns." })[0], "Written by hand in search.toml. They still match as before.") : null,
        h("details", { class: "profile-advanced" }, h("summary", {}, "Add a pattern"),
          h("p", { class: "muted" }, "A regular expression, matched against the title in any case. Plain titles above are easier to get right."),
          adder("A pattern, such as \\bstaff\\b.*\\bengineer\\b", "Add pattern", (value) => {
            if (!track.patterns.includes(value)) track.patterns.push(value);
            drawTracks();
            changed(true);
          })),
        h("label", { class: "profile-choice" }, level, "Needs a senior title"),
        industries(),
        profileField("What drafts lead with", emphasis, "Saved under Emphasis by track in run-notes.md, which the daily run reads."));
    };
    const drawTracks = () => {
      let live = 0;
      fill(list, form.tracks.map((track, at) => trackCard(track, at, track.removed ? -1 : live++)));
      focusNew = null;
    };
    const addTrack = h("button", { class: "btn", type: "button", disabled: off, onclick: () => {
      const track = { index: null, name: "", titles: [], patterns: [], needs_level: false, industries: [], emphasis: "", removed: false };
      form.tracks.push(track);
      focusNew = track;
      drawTracks();
    } }, "+ Add a role type");
    // Prose, not a list, so it's yours to word: it isn't kept in step with the role types' names.
    const sofar = h("textarea", { rows: "2", "aria-label": "Roles so far", disabled: off,
      placeholder: "Such as: staff data engineering and analytics platform roles" });
    sofar.value = form.roles_so_far;
    sofar.addEventListener("input", () => { form.roles_so_far = sofar.value.replace(/\s*[\r\n]+\s*/g, " "); changed(); });
    const more = data.roles_so_far.more;

    // ---- Skill points and flags ----
    const grid = (columns) => `display: grid; grid-template-columns: ${columns}; gap: 6px; align-items: center;`;
    const rowsBox = h("div", { class: "stack" });
    const flagsBox = h("div", { class: "stack" });
    const cell = (row, at, label, attrs) => {
      const el = h("input", { type: attrs.type || "text", value: row[at], "aria-label": label, disabled: off, ...attrs });
      el.addEventListener("input", () => { row[at] = el.value; changed(); });
      return el;
    };
    const points = { type: "number", min: "0", max: "100", step: "1", style: "width: 100%;" };
    const drop = (rows, row, draw, label) => h("button", { class: "btn small danger", type: "button", "aria-label": label, title: label, disabled: off,
      onclick: () => { rows.splice(rows.indexOf(row), 1); draw(); changed(true); } }, "✕");
    const drawRows = () => fill(rowsBox, form.keywords.map((row) => h("div", { style: grid("minmax(0, 1fr) 72px auto") },
      cell(row, 0, "Pattern", {}), cell(row, 1, "Points", points), drop(form.keywords, row, drawRows, `Remove ${row[0] || "this row"}`))));
    const drawFlags = () => fill(flagsBox, form.flags.map((row) => h("div", { style: grid("minmax(0, 1fr) minmax(0, 1.5fr) 64px auto") },
      cell(row, 0, "Label", {}), cell(row, 1, "Pattern", {}), cell(row, 2, "Points off", points),
      drop(form.flags, row, drawFlags, `Remove ${row[0] || "this flag"}`))));

    // ---- What the prospects would do ----
    function showProspects() {
      const p = last && last.prospects;
      if (!p) return;
      if (p.error) {
        fill(prospects, h("div", { class: "callout bad" }, h("b", {}, p.error)));
        return;
      }
      if (!p.total) {
        fill(prospects, h("p", { class: "muted" }, "No prospects to score yet. Once Pyrite has read the boards, a change here shows what it would do to them."));
        return;
      }
      if (!p.changed) {
        fill(prospects, h("p", { class: "muted" }, `${profileCount(p.total, "prospect")} from the boards. Change something to see how each would score.`));
        return;
      }
      const job = (j) => `${j.company}: ${j.title}`;
      const dropped = p.dropped.length + p.more_dropped;
      fill(prospects,
        h("p", {}, h("b", {}, `Of ${profileCount(p.total, "prospect")}, ${p.kept} would be kept and ${dropped} would no longer pass.`),
          p.held ? ` A rescore leaves the ${p.held} you've acted on as ${p.held === 1 ? "it is" : "they are"}.` : null),
        p.dropped.length ? h("div", { class: "stack" }, h("b", {}, "Would be dropped"),
          h("ul", { class: "profile-rules" }, p.dropped.map((j) => h("li", {}, `${job(j)}, because ${j.why}`,
            j.held ? h("span", { class: "muted" }, " (kept, since you've acted on it)")
              : j.already ? h("span", { class: "muted" }, " (the next rescore drops it with or without this change)") : null))),
          p.more_dropped ? h("small", { class: "muted" }, `… and ${p.more_dropped} more`) : null) : null,
        p.moved.length ? h("div", { class: "stack" }, h("b", {}, "Would score differently"),
          h("ul", { class: "profile-rules" }, p.moved.map((j) => j.was_dropped
            ? h("li", {}, `${job(j)}: ${j.after} as ${j.track_after}`, h("span", { class: "muted" }, ", where your settings now would drop it"))
            : h("li", {}, `${job(j)}: ${j.before} → ${j.after}`,
              j.track_after !== j.track_before ? h("span", { class: "muted" }, `, ${j.track_before || "no role type"} → ${j.track_after || "no role type"}`) : null))),
          p.more_moved ? h("small", { class: "muted" }, `… and ${p.more_moved} more`) : null)
          : h("p", { class: "muted" }, "No score that's kept would change."));
    }

    // ---- Try a title ----
    const title = h("input", { type: "text", value: form.test, "aria-label": "A job title to try", placeholder: "A job title, such as Staff Data Engineer" });
    title.addEventListener("input", () => { form.test = title.value; changed(); });
    function showTest() {
      const t = last && last.test;
      if (!form.test.trim() || !t) {
        fill(tested, h("p", { class: "muted" }, "Type a job title to see which role type would take it, with the changes above."));
        return;
      }
      const level = { top: "a top-level title", mid: "a senior title", "": "neither top-level nor senior" }[t.level];
      fill(tested,
        t.excluded ? h("p", { class: "error" }, `Never kept: it has ${t.excluded}, which is under Never these titles.`)
          : t.track ? h("p", { class: "profile-ok" }, `Kept as ${t.track}.`)
            : h("p", { class: "error" }, "No role type takes it, so a posting with this title is dropped."),
        h("ul", { class: "muted profile-rules" },
          h("li", {}, `It reads as ${level}.`),
          t.tracks.map((m) => h("li", {}, `${m.name} matches it by ${m.plain ? `“${m.plain}”` : `the pattern ${m.pattern}`}`,
            m.why ? `, but ${m.why}.` : "."))));
    }

    const main = h("div", { class: "stack profile-form" },
      h("section", { class: "panel stack", "aria-label": "Role types" },
        h("h3", { class: "profile-sub" }, "Role types"),
        h("small", { class: "muted" }, "A posting's title goes to the first role type that matches it, from the top. A title none of them match is dropped."),
        list, h("div", {}, addTrack),
        profileField("Roles so far", sofar, `Saved as Roles so far in run-notes.md: the kinds of role you've gone for, in your words, which the daily run reads.${more ? ` The ${more === 1 ? "line" : `${more} lines`} under it there stay as they are.` : ""}`)),
      h("div", { class: "profile-pair" },
        h("section", { class: "panel stack", "aria-label": "Senior titles" },
          h("h3", { class: "profile-sub" }, "Senior titles"),
          h("small", { class: "muted" }, "A role type that needs a senior title takes only titles with one of these words. Top-level words add 10 points, senior ones 5."),
          profileField("Top-level words", editable(form.level_top, data.level_top, { placeholder: "Such as principal", empty: "None." })),
          profileField("Senior words", editable(form.level_mid, data.level_mid, { placeholder: "Such as senior", empty: "None." }))),
        h("section", { class: "panel stack", "aria-label": "Never these titles" },
          h("h3", { class: "profile-sub" }, "Never these titles"),
          h("small", { class: "muted" }, "A title with any of these is dropped, whatever else it says. Each is whole words in any case, so intern doesn't catch Internal. Add \\w* to catch endings."),
          editable(form.exclude_titles, data.exclude_titles, { placeholder: "Such as sales", empty: "None." }))),
      h("section", { class: "panel stack", "aria-label": "Try a title" },
        h("h3", { class: "profile-sub" }, "Try a title"), title, tested),
      h("section", { class: "panel stack", "aria-label": "Your prospects" },
        h("h3", { class: "profile-sub" }, "Your prospects with these changes"), prospects, profileRescore()),
      h("details", { class: "profile-advanced" }, h("summary", {}, "Advanced: points for skills, and flags"),
        h("p", { class: "muted" }, `A posting scores 25 for its role type, up to 10 for seniority, 15 for local or 10 for remote, and the points for each skill pattern it mentions, up to 40 in all. Flags take points off and mark the card. Below ${data.min_score} it isn't kept.`),
        h("b", {}, "Skill points"), rowsBox,
        h("div", {}, h("button", { class: "btn small", type: "button", disabled: off, onclick: () => { form.keywords.push(["", ""]); drawRows(); } }, "+ Add a skill")),
        h("b", {}, "Flags"), flagsBox,
        h("div", {}, h("button", { class: "btn small", type: "button", disabled: off, onclick: () => { form.flags.push(["", "", ""]); drawFlags(); } }, "+ Add a flag"))),
      review);
    drawTracks();
    drawRows();
    drawFlags();
    showTest();
    changed(true);
    return {
      main,
      aside: h("div", { class: "panel stack" }, h("h2", {}, "How a title is read"),
        h("p", {}, "A plain title such as “data engineer” matches as whole words in any case, so it takes “Senior Data Engineer, Platform” but not “Data Engineering Manager”."),
        h("p", {}, "Order matters: a title goes to the first role type that takes it, and that decides what its drafts lead with."),
        h("p", { class: "muted" }, "Saving changes search.toml, not the prospects you have. Rescore now, under Your prospects once you've saved, scores them again as the preview shows, or the next pan does before it reads the boards. `pyrite discover --fresh` looks again at postings dropped before.")),
    };
  },
});
