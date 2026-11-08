"use strict";
// Achievements: the themed sections of facts.md, a fact at a time, and a builder that turns what you did into one fact
// line. Drafts may only claim what's here. Where a result was measured is saved as a wording rule in run-notes.md, so
// drafts keep it.

profileStep("achievements", {
  render(ctx) {
    const data = ctx.data;
    const memo = ctx.memo;
    if (!memo.form) {
      memo.form = {
        sections: data.sections.filter((s) => s.kind === "facts").map((s) => ({
          line: s.line, title: s.title,
          items: s.items.filter((i) => i.level === 0).map((i) => ({ line: i.line, text: i.text })),
          // Lines under a fact stay with it. They're shown, not edited here.
          under: Object.fromEntries(s.items.filter((i) => i.level === 0).map((i) => [i.line,
            s.items.filter((c) => c.level > 0 && c.line > i.line && !s.items.some((p) => p.level === 0 && p.line > i.line && p.line < c.line)).map((c) => c.text)])),
        })),
        wording: [],
        builder: { role: "", did: "", before: "", after: "", where: "", section: 0 },
      };
    }
    const form = memo.form;
    const off = !ctx.editable;
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const built = h("div", { "aria-live": "polite" });
    const rules = h("ul", { class: "profile-rules" });
    let composed = null;
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) {
        composed = result.preview.builder;
        showBuilt();
        fill(rules, result.preview.wording.length ? result.preview.wording.map((rule) => h("li", {}, rule))
          : h("li", { class: "muted" }, "No wording rules yet."));
      }
    });
    const changed = (now) => send({
      sections: form.sections.map((s) => ({ line: s.line, title: s.title, items: s.items.map((i) => ({ line: i.line, text: i.text })) })),
      wording: form.wording.map((w) => ({ keep: w.keep, fact: w.item.text })),
      builder: form.builder,
    }, now);

    const list = h("div", { class: "stack" });
    let focus = null;
    const draw = () => {
      fill(list, form.sections.map((section, si) => {
        const title = h("input", { type: "text", value: section.title, "aria-label": "Section title", class: "profile-employer-name", disabled: off });
        title.addEventListener("input", () => { section.title = title.value; changed(); });
        if (focus === section) setTimeout(() => title.focus());
        return h("section", { class: "profile-employer", "aria-label": section.title || "New section" },
          h("div", { class: "row" }, title, h("span", { class: "spacer" }),
            h("button", { class: "btn small", type: "button", disabled: off, onclick: () => {
              const item = { line: null, text: "" };
              section.items.push(item);
              focus = item;
              draw();
            } }, "+ Add a fact"),
            h("button", { class: "btn small danger", type: "button", disabled: off, title: `Remove ${section.title || "this section"}`,
              "aria-label": `Remove ${section.title || "this section"} and its facts`, onclick: () => {
                form.sections.splice(si, 1);
                draw();
                changed(true);
              } }, "✕")),
          section.items.length ? section.items.map((item, ii) => {
            const input = h("input", { type: "text", value: item.text, "aria-label": "Fact", disabled: off });
            input.addEventListener("input", () => { item.text = input.value; changed(); });
            if (focus === item) setTimeout(() => input.focus());
            const under = item.line !== null ? section.under[item.line] || [] : [];
            return h("div", { class: "profile-fact" },
              h("div", { class: "profile-add" }, input,
                h("button", { class: "btn small danger", type: "button", disabled: off, title: "Remove this fact", "aria-label": `Remove ${item.text}`, onclick: () => {
                  section.items.splice(ii, 1);
                  form.wording = form.wording.filter((w) => w.item !== item);
                  draw();
                  changed(true);
                } }, "✕")),
              under.length ? h("ul", { class: "muted profile-under" }, under.map((text) => h("li", {}, text))) : null);
          }) : h("p", { class: "muted" }, "No facts here yet."));
      }));
      fill(target, form.sections.map((s, i) => h("option", { value: i, selected: i === form.builder.section }, s.title || "New section")));
      focus = null;
    };

    // The achievement builder.
    const b = form.builder;
    const roles = data.timeline.employers.flatMap((e) => e.roles.map((r) => `${r.title}, ${e.name}`));
    const roleSelect = h("select", { "aria-label": "Which role", disabled: off },
      h("option", { value: "" }, "Choose a role"), roles.map((r) => h("option", { value: r, selected: b.role === r }, r)));
    roleSelect.addEventListener("change", () => { b.role = roleSelect.value; changed(); });
    const target = h("select", { "aria-label": "Which section it goes in", disabled: off });
    target.addEventListener("change", () => { b.section = Number(target.value); });
    const field = (key, label, help, placeholder) => {
      const input = h("input", { type: "text", value: b[key], placeholder: placeholder || "", disabled: off });
      input.addEventListener("input", () => { b[key] = input.value; changed(); });
      return profileField(label, input, help);
    };
    const inputs = {};
    function showBuilt() {
      if (!composed || !composed.text) {
        fill(built, h("p", { class: "muted" }, "The fact line appears here as you type."));
        return;
      }
      const add = h("button", { class: "btn primary", type: "button", disabled: off || !form.sections.length, onclick: () => {
        const section = form.sections[b.section] || form.sections[0];
        const item = { line: null, text: composed.text };
        section.items.push(item);
        if (composed.where) form.wording.push({ keep: composed.where, item });
        Object.assign(b, { did: "", before: "", after: "", where: "" });
        for (const [key, input] of Object.entries(inputs)) input.value = b[key];
        composed = null;
        draw();
        changed(true);
      } }, "Add to the fact bank");
      fill(built, h("div", { class: `callout ${composed.flags.length ? "" : "good"}` },
        h("b", {}, composed.text),
        composed.flags.length ? h("ul", {}, composed.flags.map((flag) => h("li", {}, flag))) : null,
        composed.where ? h("p", { class: "muted" }, `Saved with it as a wording rule: drafts keep “${composed.where}”.`) : null),
      h("div", { class: "row" }, add, h("span", { class: "muted" }, "It's added below, and saved when you save.")));
    }
    const builderFields = [
      ["did", "What you did", "Start with a verb, such as Cut, Built or Shipped. Leave the result for the next fields.", "Cut nightly regression time"],
      ["before", "Before", null, "6 hours"],
      ["after", "After", null, "50 minutes"],
      ["where", "Where or how it was measured", "Such as “on the test rig” or “in a pilot of 8 engineers”. Drafts must keep it.", "on the shared CI farm"],
    ].map(([key, label, help, placeholder]) => {
      const node = field(key, label, help, placeholder);
      inputs[key] = node.querySelector("input");
      return node;
    });
    const builder = h("details", { class: "panel profile-builder", open: !form.sections.some((s) => s.items.length) },
      h("summary", {}, h("b", {}, "Add one with the achievement builder")),
      h("div", { class: "stack" },
        h("div", { class: "profile-grid" }, profileField("Which role", roleSelect), profileField("Which section", target)),
        builderFields[0], h("div", { class: "profile-grid" }, builderFields[1], builderFields[2]), builderFields[3],
        built));

    draw();
    showBuilt();
    changed(true);
    return {
      main: h("div", { class: "stack profile-form" },
        h("p", { class: "muted" }, "Numbers stay as measured. One fact to a line, grouped however suits you. Do not use and Unsupported are under Off limits."),
        builder,
        list,
        h("div", {}, h("button", { class: "btn", type: "button", disabled: off, onclick: () => {
          const section = { line: null, title: "", items: [], under: {} };
          form.sections.push(section);
          focus = section;
          draw();
        } }, "+ Add a section")),
        review),
      aside: h("div", { class: "panel stack" }, h("h2", {}, "Wording rules"),
        h("p", { class: "muted" }, "From run-notes.md. Drafts keep this wording when they use these facts."), rules),
    };
  },
});
