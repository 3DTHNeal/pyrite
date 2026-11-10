"use strict";
// Companies to watch: the job boards Pyrite reads every morning, under [watch.*] in search.toml, the companies with no
// board it can read, which you check by hand, and what it searches Workday sites for. A pasted careers page address is
// read on the server as the board it names. Test reads one board once, as `pyrite sources` does, and saves nothing.

profileStep("companies", {
  render(ctx) {
    const data = ctx.data.companies;
    const kinds = data.kinds;
    const memo = ctx.memo;
    if (!memo.form) {
      memo.form = {
        boards: data.boards.map((b) => ({ was: b.was, kind: b.kind, key: b.key, name: b.name, wd: b.wd, site: b.site, going: false })),
        manual: data.manual.map((m) => ({ at: m.at, name: m.name, url: m.url, why: m.why })),
        queries: [...data.queries],
        paste: "",
      };
      memo.tests = {};
      memo.pasteName = "";
    }
    const form = memo.form;
    const off = !ctx.editable;
    const known = Object.fromEntries(data.boards.map((b) => [b.was, b]));
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const pasted = h("div", { class: "stack", "aria-live": "polite" });
    let lastPasted = null;
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) {
        const now = result.preview.pasted || null;
        if (now && now.ok && (!lastPasted || lastPasted.key !== now.key || lastPasted.kind !== now.kind)) memo.pasteName = now.name;
        lastPasted = now;
        showPasted();
      }
    });
    const edits = () => ({
      boards: form.boards.filter((b) => !b.going).map(({ was, kind, key, name, wd, site }) => ({ was, kind, key, name, wd, site })),
      manual: form.manual, queries: form.queries, paste: form.paste,
    });
    const changed = (now) => send(edits(), now);

    const input = (value, label, onInput, attrs = {}) => {
      const el = h("input", { type: "text", value, "aria-label": label, title: label, disabled: off, ...attrs });
      el.addEventListener("input", () => { onInput(el.value.trim()); changed(); });
      return el;
    };
    const boardId = (b) => [b.kind, b.key, b.wd, b.site].join(":");
    const where = (b) => (b.kind === "workday" ? `${b.key}.${b.wd}.myworkdayjobs.com/${b.site}` : `${kinds[b.kind]} board ${b.key}`);

    // ---- Test: one board, once, as `pyrite sources` reads it ----
    const testLine = (b) => {
      const test = memo.tests[boardId(b)];
      if (!test) return null;
      if (test.busy) return h("small", { class: "muted" }, "Testing…");
      if (test.error) return h("small", { class: "error" }, test.error);
      return test.ok
        ? h("small", {}, pill("good", "Answers"), ` ${profileCount(test.count, "posting")} listed right now.`)
        : h("small", {}, pill("bad", "Didn't answer"), ` ${test.hint || test.reason}`);
    };
    const testButton = (b, redraw) => h("button", { class: "btn small", type: "button", onclick: async () => {
      const id = boardId(b);
      memo.tests[id] = { busy: true };
      redraw();
      try {
        const found = await api("/api/profile/test-board", { kind: b.kind, key: b.key, wd: b.wd || "", site: b.site || "", name: b.name || "" });
        memo.tests[id] = { ok: found.ok, count: found.count, reason: found.error, hint: found.hint };
      } catch (err) {
        memo.tests[id] = { error: err.message };
      }
      redraw();
    } }, "Test");

    // ---- Add a company from its careers page ----
    // Reading an address and testing a board save nothing, so the demo does both too.
    const pasteField = h("input", { type: "text", value: form.paste, "aria-label": "A careers page address",
      placeholder: "boards.greenhouse.io/acme, or a job's page on any of these boards" });
    pasteField.addEventListener("input", () => { form.paste = pasteField.value; changed(); });
    function showPasted() {
      const found = form.paste.trim() ? lastPasted : null;
      if (!found) {
        fill(pasted, h("small", { class: "muted" }, "Paste the address of a company's job board, or of one job on it. Pyrite works out which board it is."));
        return;
      }
      if (!found.ok) {
        fill(pasted, h("div", { class: "callout info" }, h("p", {}, found.error),
          /\.[a-z]{2,}/i.test(found.url) ? h("div", { class: "row" }, h("button", { class: "btn small", type: "button", disabled: off, onclick: () => {
            form.manual.push({ at: null, name: "", url: found.url, why: "" });
            form.paste = "";
            pasteField.value = "";
            focusManual = form.manual[form.manual.length - 1];
            drawManual();
            changed(true);
          } }, "Add it under Check by hand")) : null));
        return;
      }
      const board = { kind: found.kind, key: found.key, wd: found.wd || "", site: found.site || "", name: memo.pasteName };
      const already = form.boards.find((b) => !b.going && b.kind === board.kind && b.key === board.key);
      const name = h("input", { type: "text", value: memo.pasteName, "aria-label": "The company's name" });
      name.addEventListener("input", () => { memo.pasteName = name.value; board.name = name.value.trim(); });
      const result = h("div");
      const redraw = () => fill(result, testLine(board));
      const add = h("button", { class: "btn primary", type: "button", disabled: off || Boolean(already), onclick: () => {
        board.name = memo.pasteName.trim();
        if (!board.name) { name.focus(); return; }
        form.boards.unshift({ was: null, ...board, going: false });
        form.paste = "";
        pasteField.value = "";
        lastPasted = null;
        draw();
        showPasted();
        changed(true);
      } }, "Add to the watchlist");
      fill(pasted, h("div", { class: "profile-board-found" },
        h("div", { class: "row" }, pill("info", kinds[board.kind]), h("b", {}, where(board))),
        profileField("Company name", name),
        already ? h("small", { class: "muted" }, `Watched already, as ${already.name || already.key}.`) : null,
        h("div", { class: "row" }, add, testButton(board, redraw)),
        result));
      redraw();
    }

    // ---- The boards watched now ----
    const list = h("div", { class: "stack" });
    const heading = h("h3", { class: "profile-sub" });
    function draw() {
      const shown = form.boards.filter((b) => !b.going).length;
      heading.textContent = `Watched boards (${shown})`;
      if (!form.boards.length) {
        fill(list, h("p", { class: "muted" }, "No boards yet. Paste a company's careers page above to add one."));
        return;
      }
      fill(list, form.boards.map((b, at) => {
        const row = h("div", { class: `profile-board ${b.kind}${b.going ? " going" : ""}${b.was ? "" : " new"}` });
        const result = h("div");
        const redraw = () => fill(result, testLine(b));
        const was = b.was ? known[b.was] : null;
        const same = was && was.kind === b.kind && was.key === b.key && was.wd === b.wd && was.site === b.site;
        const status = same && was.status
          ? (was.status.error ? h("small", { class: "error" }, `Failing at the last run: ${was.status.error}`)
            : h("small", { class: "muted" }, `${profileCount(was.status.count || 0, "posting")} at the last run.`))
          : null;
        const keyInputs = b.kind === "workday"
          ? [input(b.key, "Workday tenant", (v) => { b.key = v; }, { placeholder: "tenant", disabled: off || b.going }),
            input(b.wd, "Workday server, such as wd1", (v) => { b.wd = v; }, { placeholder: "wd1", class: "short", disabled: off || b.going }),
            input(b.site, "Workday site", (v) => { b.site = v; }, { placeholder: "site", disabled: off || b.going })]
          : [input(b.key, `${kinds[b.kind]} board`, (v) => { b.key = v; }, { placeholder: "board", disabled: off || b.going })];
        const label = b.going ? `Keep ${b.name || b.key}` : `Stop watching ${b.name || b.key}`;
        fill(row,
          h("span", { class: "profile-board-kind" }, kinds[b.kind]),
          input(b.name, "Company name", (v) => { b.name = v; }, { placeholder: "Company name", disabled: off || b.going }),
          h("div", { class: "profile-board-key" }, keyInputs),
          h("div", { class: "row-actions" }, testButton(b, redraw),
            h("button", { class: "btn small danger", type: "button", "aria-label": label, title: label, disabled: off, onclick: () => {
              if (b.was) b.going = !b.going;
              else form.boards.splice(at, 1);
              draw();
              changed(true);
            } }, b.going ? "↺" : "✕")),
          h("div", { class: "profile-board-note" },
            b.going ? h("small", { class: "muted" }, "Stops being read when you save.") : null,
            was && was.problem && !b.going ? h("small", { class: "error" }, was.problem) : null,
            b.going ? null : status, result));
        redraw();
        return row;
      }));
    }

    // ---- Companies checked by hand ----
    const manualList = h("div", { class: "stack" });
    let focusManual = null;
    function drawManual() {
      fill(manualList, form.manual.length ? form.manual.map((m, at) => {
        const name = input(m.name, "Company or site", (v) => { m.name = v; }, { placeholder: "Company or site" });
        if (focusManual === m) setTimeout(() => name.focus());
        return h("div", { class: "profile-manual" }, name,
          input(m.url, "Its careers page", (v) => { m.url = v; }, { placeholder: "https://…" }),
          input(m.why, "Why it's checked by hand", (v) => { m.why = v; }, { placeholder: "Why by hand" }),
          h("button", { class: "btn small danger", type: "button", "aria-label": `Remove ${m.name || "this one"}`, title: `Remove ${m.name || "this one"}`,
            disabled: off, onclick: () => { form.manual.splice(at, 1); drawManual(); changed(true); } }, "✕"));
      }) : h("p", { class: "muted" }, "None."));
      focusManual = null;
    }

    // ---- What Workday sites are searched for ----
    const chips = h("div", { class: "profile-chips" });
    function drawQueries() {
      fill(chips, form.queries.length ? form.queries.map((query) => h("span", { class: "profile-chip" }, h("span", {}, query),
        h("button", { type: "button", "aria-label": `Stop searching for ${query}`, title: `Stop searching for ${query}`, disabled: off, onclick: () => {
          form.queries = form.queries.filter((q) => q !== query);
          drawQueries();
          changed(true);
        } }, "✕"))) : h("span", { class: "muted" }, "No searches, so Workday sites find nothing."));
    }
    const queryField = h("input", { type: "text", placeholder: "A search, such as firmware engineer", "aria-label": "A Workday search", disabled: off });
    const addQuery = () => {
      const query = queryField.value.trim();
      if (!query) return;
      if (!form.queries.includes(query)) form.queries.push(query);
      queryField.value = "";
      queryField.focus();
      drawQueries();
      changed(true);
    };
    queryField.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addQuery(); } });

    draw();
    drawManual();
    drawQueries();
    showPasted();
    changed(true);
    return {
      main: h("div", { class: "stack profile-form" },
        h("section", { class: "panel stack", "aria-label": "Add a company" },
          h("h3", { class: "profile-sub" }, "Add a company"),
          pasteField, pasted),
        h("section", { class: "panel stack", "aria-label": "Watched boards" },
          heading,
          h("small", { class: "muted" }, "Read every morning. A Workday site is its tenant, server and site, from its address: tenant.wd1.myworkdayjobs.com/site."),
          list),
        h("section", { class: "panel stack", "aria-label": "Check by hand" },
          h("h3", { class: "profile-sub" }, "Check by hand"),
          h("small", { class: "muted" }, "Companies and sites with no board Pyrite can read, such as one whose terms forbid it. The Sources tab lists them as a reminder."),
          manualList,
          h("div", {}, h("button", { class: "btn small", type: "button", disabled: off, onclick: () => {
            form.manual.push({ at: null, name: "", url: "", why: "" });
            focusManual = form.manual[form.manual.length - 1];
            drawManual();
          } }, "+ Add one"))),
        h("section", { class: "panel stack", "aria-label": "Workday searches" },
          h("h3", { class: "profile-sub" }, "Workday searches"),
          h("small", { class: "muted" }, "A Workday site has no full list to read, so Pyrite searches each one for these. What they find still goes through the filters in Roles you want."),
          chips,
          h("div", { class: "profile-add" }, queryField, h("button", { class: "btn", type: "button", disabled: off, onclick: addQuery }, "Add"))),
        review),
      aside: h("div", { class: "panel stack" }, h("h2", {}, "Finding a company's board"),
        h("p", {}, "Pyrite reads four kinds of job board: Greenhouse, Lever, Ashby and Workday. Their addresses look like these:"),
        h("ul", { class: "profile-hosts" }, ["boards.greenhouse.io/acme", "jobs.lever.co/acme", "jobs.ashbyhq.com/acme", "acme.wd1.myworkdayjobs.com/External"]
          .map((host) => h("li", {}, host))),
        h("p", {}, "A company's own careers page often hands its jobs to one of these. Open a job there and paste where its Apply button goes."),
        h("p", { class: "muted" }, "Test reads the board once, as ", h("code", {}, "pyrite sources"), " does, and says how many postings it lists. It saves nothing. A board that fails at a run is shown on the Sources tab.")),
    };
  },
});
