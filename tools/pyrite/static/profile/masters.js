"use strict";
// Master resume: profile/resume.md and profile/cover-letter.md, which every draft starts from. The headline and the
// text under each heading are edited here; the name, contact line and headings come from Name and contact and Work
// history. Each draft of a change runs the fact check on both, and names anything only the master says.

profileStep("masters", {
  render(ctx) {
    const data = ctx.data;
    const shown = data.master_blocks;
    const memo = ctx.memo;
    if (!memo.form) {
      memo.form = {
        headline: shown.resume.headline || "",
        blocks: shown.resume.blocks.map((b) => ({ ...b, was: b.text })),
        body: shown.letter.body || "",
      };
    }
    const form = memo.form;
    const off = !ctx.editable;
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const checked = h("div", { class: "stack" }, h("p", { class: "muted" }, "Checking…"));
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) fill(checked, verdicts(result.preview));
    });
    const changed = (now) => {
      const edits = {};
      if (shown.resume.exists) {
        edits.resume = { headline: form.headline, blocks: form.blocks.filter((b) => b.text !== b.was).map((b) => ({ line: b.line, text: b.text })) };
      }
      if (shown.letter.exists) edits.letter = { body: form.body };
      send(edits, now);
    };

    const heading = data.heading_source;
    const elsewhere = heading.path && heading.path !== "profile/resume.md"
      ? h("div", { class: "callout info" }, h("b", {}, `Drafts are checked against ${heading.path}.`),
        h("p", {}, "That's your master as far as the fact check goes. This section edits profile/resume.md and profile/cover-letter.md, so change that file in a text editor."))
      : null;
    const go = (id, label) => h("button", { class: "btn small", type: "button", onclick: () => profileGo(id) }, label);

    const area = (value, label, onInput, rows) => {
      // Tall enough for the text as it wraps, roughly 70 characters to a row.
      const wrapped = value.split("\n").reduce((sum, line) => sum + Math.max(1, Math.ceil(line.length / 70)), 0);
      const box = h("textarea", { rows: String(rows || Math.min(14, Math.max(2, wrapped + 1))), "aria-label": label, disabled: off });
      box.value = value;
      box.addEventListener("input", () => { onInput(box.value); changed(); });
      return box;
    };

    const resume = shown.resume.exists ? (() => {
      const headline = h("input", { type: "text", value: form.headline, disabled: off });
      headline.addEventListener("input", () => { form.headline = headline.value; changed(); });
      return h("section", { class: "panel stack", "aria-label": "Resume" },
        h("div", { class: "row" }, h("h3", { class: "profile-sub" }, "Resume"), h("span", { class: "spacer" }),
          h("small", { class: "muted" }, "profile/resume.md")),
        profileField("Headline", headline, "The line under your name. Drafts may change it for each job."),
        form.blocks.map((block, index) => {
          const next = form.blocks[index + 1];
          const label = h(block.level === 2 ? "b" : "span", { class: `profile-head level${block.level}` }, block.heading);
          // A heading whose text is only the headings under it, such as Experience.
          if (!block.text && next && next.level > block.level) return h("div", { class: "profile-block" }, label);
          return h("div", { class: "profile-block" }, label, area(block.text, `Text under ${block.heading}`, (v) => { block.text = v; }));
        }),
        h("div", { class: "row" }, h("small", { class: "muted" }, "Headings come from Work history, and the name and contact line from Name and contact."),
          go("history", "Work history"), go("basics", "Name and contact")));
    })() : h("div", { class: "callout" }, h("b", {}, "There's no profile/resume.md."),
      h("p", {}, "Copy your best resume there, in the form docs/operating.md describes, to edit it here."));

    const letter = shown.letter.exists
      ? h("section", { class: "panel stack", "aria-label": "Cover letter" },
        h("div", { class: "row" }, h("h3", { class: "profile-sub" }, "Cover letter"), h("span", { class: "spacer" }),
          h("small", { class: "muted" }, "profile/cover-letter.md")),
        area(form.body, "Letter", (v) => { form.body = v; }, 14),
        h("small", { class: "muted" }, "Everything after your name and contact line. Drafts tailor the opening for each job."))
      : h("div", { class: "callout" }, h("b", {}, "There's no profile/cover-letter.md."),
        h("p", {}, "Drafts can still be written, but there's no master letter for them to start from."));

    function verdicts(preview) {
      const files = Object.values(preview);
      if (!files.length) return h("p", { class: "muted" }, "Nothing to check yet.");
      return files.map((f) => h("div", { class: "stack" },
        h("b", {}, f.path.split("/").pop()),
        f.errors.length
          ? h("div", { class: "callout bad" }, h("b", {}, "A draft made from this would be blocked:"), h("ul", {}, f.errors.map((e) => h("li", {}, e))))
          : h("p", { class: "profile-ok" }, "Passes the fact check."),
        f.warnings.length ? h("ul", { class: "muted profile-gaps" }, f.warnings.map((w) => h("li", {}, w))) : null,
        f.only_here.length ? h("div", { class: "callout" }, h("b", {}, "Only your master says these"),
          h("ul", {}, f.only_here.map((e) => h("li", {}, e))),
          h("p", {}, "Drafts may use them, because the master is an approved source. Make sure each is true, and add it to your facts so it's on record.")) : null));
    }

    changed(true);
    return {
      main: h("div", { class: "stack profile-form" }, elsewhere, resume, letter, review),
      aside: h("div", { class: "panel stack" }, h("h2", {}, "Fact check"), checked),
    };
  },
});
