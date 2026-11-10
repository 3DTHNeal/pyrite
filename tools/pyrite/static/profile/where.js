"use strict";
// Where you'll work: the places that count as local, whether remote roles and relocation do, and the area the
// Industries tab looks up, from [location] and [market] in search.toml. Places are plain names; the patterns written
// by hand under local and local_exact stay, and Advanced shows and edits them. Every draft judges a location you type,
// and the prospects already found, with the filters' own code and the settings as drafted.

profileStep("where", {
  render(ctx) {
    const data = ctx.data.where;
    const memo = ctx.memo;
    if (!memo.form) {
      memo.form = {
        places: [...data.places], local: [...data.local], local_exact: [...data.local_exact],
        accept_remote: data.accept_remote, accept_relocation: data.accept_relocation,
        market: { ...data.market }, test: "",
      };
    }
    const form = memo.form;
    const off = !ctx.editable;
    const KINDS = {
      local: ["good", "local"], remote: ["good", "remote"], unknown: ["", "kept, place unknown"],
      elsewhere: ["", "kept, industry anywhere"], out: ["bad", "dropped"],
    };
    const kindPill = (kind) => pill(...(KINDS[kind] || ["", kind]));
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const tested = h("div", { "aria-live": "polite" });
    const counted = h("div", { "aria-live": "polite" });
    let last = null;
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) {
        last = result.preview;
        showTest();
        showProspects();
      }
    });
    const changed = (now) => send({
      places: form.places, local: form.local, local_exact: form.local_exact,
      accept_remote: form.accept_remote, accept_relocation: form.accept_relocation, market: form.market, test: form.test,
    }, now);

    const chip = (text, attrs, onRemove, label) => h("span", attrs, h("span", {}, text),
      h("button", { type: "button", "aria-label": label, title: label, disabled: off, onclick: onRemove }, "✕"));
    // What's saved shows with a cross to take it off, struck through until you save; what you've added shows dashed.
    const chips = (box, saved, wanted, attrs, empty) => {
      const kept = saved.map((value) => {
        const going = !wanted.includes(value);
        return chip(value, { class: `${attrs}${going ? " going" : ""}` }, () => {
          if (going) wanted.push(value);
          else wanted.splice(wanted.indexOf(value), 1);
          draw();
          changed(true);
        }, going ? `Keep ${value}` : `Take off ${value}`);
      });
      const added = wanted.filter((value) => !saved.includes(value)).map((value) => chip(value, { class: `${attrs} new` }, () => {
        wanted.splice(wanted.indexOf(value), 1);
        draw();
        changed(true);
      }, `Don't add ${value}`));
      fill(box, kept.length || added.length ? [...kept, ...added] : h("span", { class: "muted" }, empty));
    };
    const placesBox = h("div", { class: "profile-chips" });
    const localBox = h("div", { class: "profile-chips" });
    const exactBox = h("div", { class: "profile-chips" });
    const draw = () => {
      chips(placesBox, data.places, form.places, "profile-chip", "No places yet.");
      chips(localBox, data.local, form.local, "profile-chip pattern", "No patterns.");
      chips(exactBox, data.local_exact, form.local_exact, "profile-chip pattern", "No patterns.");
    };

    const adder = (placeholder, button, list) => {
      const field = h("input", { type: "text", placeholder, "aria-label": placeholder, disabled: off });
      const go = () => {
        const value = field.value.trim();
        if (!value) return;
        if (!list.some((item) => item.toLowerCase() === value.toLowerCase())) list.push(value);
        field.value = "";
        field.focus();
        draw();
        changed(true);
      };
      field.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
      return h("div", { class: "profile-add" }, field, h("button", { class: "btn", type: "button", disabled: off, onclick: go }, button));
    };

    const toggle = (key, label) => {
      const box = h("input", { type: "checkbox", checked: form[key], disabled: off });
      box.addEventListener("change", () => { form[key] = box.checked; changed(true); });
      return h("label", { class: "profile-choice" }, box, label);
    };

    const location = h("input", { type: "text", value: form.test, "aria-label": "A location to test",
      placeholder: "A location as a job board writes it" });
    location.addEventListener("input", () => { form.test = location.value; changed(); });
    function showTest() {
      const test = last && last.test;
      if (!form.test.trim() || !test) {
        fill(tested, h("p", { class: "muted" }, "Type a location to see how the filters would judge it."));
        return;
      }
      fill(tested,
        h("p", { class: "row" }, kindPill(test.after),
          test.now !== test.after ? h("span", { class: "muted" }, "Before this change: ", kindPill(test.now)) : null),
        h("p", { class: "muted" }, test.why));
    }
    const examples = ["Remote - US", "Springfield, IL", "Remote - Germany", "Chicago, IL", "Middleton, Wisconsin"];

    function showProspects() {
      const found = last && last.prospects;
      if (!found) {
        fill(counted, h("p", { class: "muted" }, "No prospects to count yet. Once Pyrite has read the boards, this shows how each change moves them."));
        return;
      }
      if (!found.total) {
        fill(counted, h("p", { class: "muted" }, "No prospects right now."));
        return;
      }
      const order = ["local", "remote", "unknown", "elsewhere", "out"];
      const rows = order.filter((kind) => found.now[kind] || found.after[kind]).map((kind) => h("tr", {},
        h("td", {}, kindPill(kind)),
        h("td", { class: "num" }, String(found.now[kind])),
        h("td", { class: "num" }, found.now[kind] === found.after[kind] ? String(found.after[kind]) : h("b", {}, String(found.after[kind])))));
      fill(counted,
        h("div", { class: "table-wrap" }, h("table", { class: "grid" },
          h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Place"), h("th", { scope: "col", class: "num" }, "Now"),
            h("th", { scope: "col", class: "num" }, "After"))),
          h("tbody", {}, rows))),
        found.moved ? h("div", { class: "stack" },
          h("small", { class: "muted" }, `${profileCount(found.moved, "prospect")} would count differently${found.moved > found.moves.length ? `, the first ${found.moves.length} shown` : ""}:`),
          h("ul", { class: "profile-rules" }, found.moves.map((move) => h("li", {},
            `${move.company}: ${move.title}`, h("span", { class: "muted" }, ` (${move.location || "no place"}) `),
            kindPill(move.now), " → ", kindPill(move.after)))))
          : h("small", { class: "muted" }, `All ${profileCount(found.total, "prospect")} count the same as now.`));
    }

    const marketField = (key, label, placeholder, help) => {
      const input = h("input", { type: "text", value: form.market[key], placeholder, disabled: off });
      input.addEventListener("input", () => { form.market[key] = input.value; changed(); });
      return profileField(label, input, help);
    };

    const remoteLists = [["remote_home", "Remote open to you"], ["remote_elsewhere", "Remote open elsewhere"]]
      .filter(([key]) => data[key] !== null)
      .map(([key, label]) => h("div", { class: "stack" }, h("b", {}, `${label}: ${key} under [location]`),
        h("div", { class: "profile-chips" }, data[key].length ? data[key].map((p) => h("span", { class: "profile-chip pattern" }, h("span", {}, p)))
          : h("span", { class: "muted" }, "Empty."))));

    const main = h("div", { class: "stack profile-form" },
      h("section", { class: "panel stack", "aria-label": "Your places" },
        h("h3", { class: "profile-sub" }, "Places that count as local"),
        h("small", { class: "muted" }, "Write each as you would: a town, a city and state, or a whole state. Each word is matched whole in any case, so “Springfield, IL” also matches “springfield il” and “Springfield, Illinois”, but not Springfield, Missouri."),
        placesBox,
        adder("A place, such as Springfield, IL", "Add place", form.places),
        data.local.length || data.local_exact.length ? h("small", { class: "muted" },
          `Your search also has ${profileCount(data.local.length + data.local_exact.length, "pattern")} written by hand, under Advanced below.`) : null),
      h("section", { class: "panel stack", "aria-label": "Remote and relocation" },
        h("h3", { class: "profile-sub" }, "Anywhere else"),
        h("div", { class: "row" },
          toggle("accept_remote", "Remote roles count"),
          toggle("accept_relocation", "I'll relocate for an onsite role")),
        h("small", { class: "muted" }, "Remote roles open only to another state or country are dropped either way. Without relocation, an onsite role outside your places is dropped before you see it.")),
      h("section", { class: "panel stack", "aria-label": "Test a location" },
        h("h3", { class: "profile-sub" }, "Test a location"), location,
        h("div", { class: "row" }, examples.map((text) => h("button", { class: "btn small", type: "button", onclick: () => {
          location.value = text;
          form.test = text;
          changed(true);
        } }, text))),
        tested),
      h("section", { class: "panel stack", "aria-label": "Your prospects" },
        h("h3", { class: "profile-sub" }, "Your prospects"),
        h("small", { class: "muted" }, "The postings from the boards still new under Prospects, judged by place with these settings."),
        counted, profileRescore()),
      h("section", { class: "panel stack", "aria-label": "Area for the Industries tab" },
        h("h3", { class: "profile-sub" }, "Area for the Industries tab"),
        h("small", { class: "muted" }, "Where the Industries tab looks up official employment numbers. Use the names the BLS uses. Either can be left empty. This doesn't change which jobs are kept."),
        h("div", { class: "profile-grid" },
          marketField("state", "State", "Illinois", "Its full name."),
          marketField("metro", "Metro area", "Springfield, IL", "As the BLS names it."),
          marketField("country", "Country", "United States", "Elsewhere, the tab shows what Pyrite has seen instead.")),
        h("div", { class: "row" },
          h("button", { class: "btn small", type: "button", onclick: () => showTab("settings/claude") }, "Model for industry outlooks, on Settings"),
          h("button", { class: "btn small", type: "button", onclick: () => showTab("settings/ranking") }, "Cities to see first, on Settings"))),
      h("details", { class: "profile-advanced" }, h("summary", {}, "Advanced: location patterns"),
        h("p", { class: "muted" }, "Regular expressions written by hand. A location that matches any of them counts as local, as a place does. Those under local ignore case; those under local_exact don't, so “, WI\\b” matches a state code and not a word."),
        h("div", { class: "stack" }, h("b", {}, "local under [location]"), localBox,
          adder("A pattern, such as springfield[\\s,]*il\\b", "Add pattern", form.local)),
        h("div", { class: "stack" }, h("b", {}, "local_exact under [location]"), exactBox,
          adder("A pattern, such as , IL\\b", "Add pattern", form.local_exact)),
        remoteLists.length ? h("p", { class: "muted" }, "These lists replace the built-in reading of a remote role's place, which assumes you're in the US. Change them in profile/search.toml.") : null,
        remoteLists),
      review);
    draw();
    showTest();
    showProspects();
    changed(true);
    return { main };
  },
});
