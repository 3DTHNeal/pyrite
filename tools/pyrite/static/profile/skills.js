"use strict";
// Skills and terms: words a draft may use that aren't elsewhere in your facts, from approved-terms.txt. Taking one off
// is saved at once; approving one lets every draft name it, so saving that asks for a code from this computer.

profileStep("skills", {
  render(ctx) {
    const groups = ctx.data.term_groups;
    const memo = ctx.memo;
    if (!memo.form) memo.form = { add: [], drop: [] };
    const form = memo.form;
    const off = !ctx.editable;
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const send = profileDrafter(ctx, (result, err) => profileShowReview(review, result, err));
    const changed = () => send({ add: form.add, drop: form.drop }, true);
    const list = h("div", { class: "stack" });
    const same = (a, b) => a.line === b.line && a.term === b.term;

    const draw = () => {
      const added = form.add.map((term) => h("span", { class: "profile-chip new" }, h("span", {}, term),
        h("button", { type: "button", "aria-label": `Don't approve ${term}`, title: `Don't approve ${term}`, disabled: off,
          onclick: () => { form.add.splice(form.add.indexOf(term), 1); draw(); changed(); } }, "✕")));
      fill(list,
        groups.length ? groups.map((group) => h("div", { class: "stack" },
          group.note ? h("small", { class: "muted" }, group.note) : null,
          h("div", { class: "profile-chips" }, group.terms.map((entry) => {
            const going = form.drop.some((d) => same(d, entry));
            const label = going ? `Keep ${entry.term}` : `Take ${entry.term} off`;
            return h("span", { class: `profile-chip${going ? " going" : ""}` }, h("span", {}, entry.term),
              h("button", { type: "button", "aria-label": label, title: label, disabled: off, onclick: () => {
                if (going) form.drop = form.drop.filter((d) => !same(d, entry));
                else form.drop.push({ line: entry.line, term: entry.term });
                draw();
                changed();
              } }, "✕"));
          })))) : h("p", { class: "muted" }, "No approved terms yet."),
        added.length ? h("div", { class: "stack" }, h("small", { class: "muted" }, "To approve when you save"), h("div", { class: "profile-chips" }, added)) : null);
    };

    const field = h("input", { type: "text", placeholder: "A term that's true of you", "aria-label": "A term that's true of you", disabled: off });
    const add = () => {
      const term = field.value.trim();
      if (!term) return;
      if (!form.add.includes(term)) form.add.push(term);
      field.value = "";
      field.focus();
      draw();
      changed();
    };
    field.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });

    draw();
    changed();
    return {
      main: h("div", { class: "stack profile-form" },
        h("section", { class: "panel stack", "aria-label": "Approved terms" },
          h("h3", { class: "profile-sub" }, "Approved terms"),
          h("small", { class: "muted" }, "The fact check blocks a specialist word in a resume unless your facts or this list has it. Drafts read this list a word at a time."),
          list,
          h("div", { class: "profile-add" }, field, h("button", { class: "btn", type: "button", disabled: off, onclick: add }, "Approve"))),
        review),
      aside: h("div", { class: "panel stack" }, h("h2", {}, "Before you approve one"),
        h("p", {}, "Every future draft may name an approved term, so approve only what you could talk about in an interview."),
        h("p", { class: "muted" }, ctx.data.setting_up
          ? "Your workspace is new, so approving a term needs no code from this computer yet. Once setup is done, approving asks for one."
          : "Approving asks for a code sent to this computer's notifications. Taking a term off needs none.")),
    };
  },
});
