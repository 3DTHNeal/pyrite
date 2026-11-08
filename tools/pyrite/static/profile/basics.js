"use strict";
// Name and contact: your name, the contact line under it on every resume and letter, and the paper size. The contact
// line is edited a part at a time and written back with the separator it already uses.

profileStep("basics", {
  render(ctx) {
    const data = ctx.data;
    const info = data.contact_parts;
    const memo = ctx.memo;
    if (!memo.form) {
      const parts = info.parts.map((part) => ({ ...part, was: part.text }));
      // An empty field for each usual part that the line doesn't have yet, after the ones it has.
      for (const kind of ["place", "phone", "email", "link"]) {
        if (!parts.some((part) => part.kind === kind)) parts.push({ kind, text: "", was: null });
      }
      memo.form = { name: data.basics.name, paper: data.basics.paper || "letter", parts };
    }
    const form = memo.form;
    const LABELS = { place: "City and state", phone: "Phone", email: "Email", link: "LinkedIn or website", other: "Also on the line" };
    const TYPES = { phone: "tel", email: "email" };
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const head = h("div", { class: "paper-head" });
    const send = profileDrafter(ctx, (result, err) => profileShowReview(review, result, err));

    const contactChanged = () => form.parts.some((part) => part.text.trim() !== (part.was || ""));
    const contact = () => form.parts.map((part) => part.text.trim()).filter(Boolean).join(info.sep);
    const update = () => {
      fill(head, h("b", {}, form.name.trim() || "Your name"), h("span", {}, contact() || "Your contact line"));
      const edits = { name: form.name, paper: form.paper };
      if (contactChanged()) edits.contact = form.parts.map((part) => part.text);
      send(edits);
    };

    const nameInput = h("input", { type: "text", value: form.name, autocomplete: "name", disabled: !ctx.editable });
    nameInput.addEventListener("input", () => { form.name = nameInput.value; update(); });
    const fields = form.parts.map((part) => {
      const input = h("input", { type: TYPES[part.kind] || "text", value: part.text, disabled: !ctx.editable });
      input.addEventListener("input", () => { part.text = input.value; update(); });
      return profileField(LABELS[part.kind], input);
    });
    const paper = h("div", { class: "row", role: "radiogroup", "aria-label": "Paper size" },
      [["letter", "US Letter"], ["a4", "A4"]].map(([value, label]) => {
        const radio = h("input", { type: "radio", name: "profile-paper", value, checked: form.paper === value, disabled: !ctx.editable });
        radio.addEventListener("change", () => { form.paper = value; update(); });
        return h("label", { class: "profile-choice" }, radio, label);
      }));

    // Where the fact check reads the contact line, when that's a file this section doesn't write.
    const written = ["profile/resume.md", "profile/cover-letter.md"];
    const elsewhere = info.checked_in && !written.includes(info.checked_in)
      ? h("div", { class: "callout info" }, h("b", {}, `The fact check reads your contact line from ${info.checked_in}.`),
        h("p", {}, "This section doesn't change that file, so change its “@ ” line there too when you change it here."))
      : null;
    const differs = Object.values(info.masters).filter((m) => m.exists && m.contact !== null && m.contact !== data.basics.contact);
    const drift = differs.length
      ? h("div", { class: "callout" }, h("b", {}, `${differs.map((m) => m.path).join(" and ")} ${differs.length === 1 ? "has" : "have"} a different contact line.`),
        h("p", {}, "Saving a change to the contact line here sets it there too."))
      : null;

    const main = h("div", { class: "stack profile-form" },
      profileField("Name as it goes on your documents", nameInput, "Every resume and letter opens with it, and the fact check blocks a draft that changes it."),
      h("div", { class: "profile-grid" }, fields),
      h("small", { class: "muted" }, "Leave a field empty to take it off. A part can't hold a ·, | or •, since those separate the parts."),
      h("div", { class: "profile-field" }, h("span", {}, "Paper size"), paper),
      elsewhere, drift, review);
    update();
    return {
      main,
      aside: h("div", { class: "panel" }, h("h2", {}, "Top of every document"), head),
    };
  },
});
