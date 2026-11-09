"use strict";
// Gaps to answer: requirements the drafts keep calling gaps, from the numbered "Gaps to prepare for" lists in each
// application's notes, grouped by the server with no AI. A yes adds your own words as a fact; a no adds a line under
// Unsupported. Both go through the usual save, with its diff and History. Doesn't apply and Ask again change no file,
// so they're sent at once. What's recorded as answered follows what the save actually added to facts.md.

profileStep("gaps", {
  render(ctx) {
    const found = ctx.data.gaps || { groups: [], applications: 0, ask_from: 2 };
    const memo = ctx.memo;
    if (!memo.form) memo.form = { answers: {}, once: false };
    const form = memo.form;
    const off = !ctx.editable;
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const error = h("p", { class: "error", role: "alert" });
    // h() wires only onclick, and the page's content security policy refuses inline handlers, so the rest are added here.
    const on = (el, type, handler) => { el.addEventListener(type, handler); return el; };
    const factSections = ctx.data.sections.filter((s) => s.kind === "facts").map((s) => s.title);
    const NEW = "\u0000new";

    const wanted = () => Object.entries(form.answers)
      .filter(([, a]) => a.answer === "yes" || a.answer === "no")
      .map(([id, a]) => ({ id, answer: a.answer, text: a.text || "",
        section: a.section === NEW ? (a.newSection || "") : (a.section || "") }));
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) ctx.change(result.changes, result.count, { answers: wanted() });
    });
    const changed = (now) => send({ answers: wanted() }, now);

    // Doesn't apply and Ask again write no file the assay reads, so they don't wait for Save.
    const question = async (action, id, button) => {
      error.textContent = "";
      button.disabled = true;
      try {
        profileData = await api("/api/gaps", { action, id });
        delete form.answers[id];
        toast(action === "dismiss" ? "Stopped asking about that one." : "It'll be asked again.");
        renderProfile();
      } catch (err) {
        error.textContent = err.message;
        button.disabled = false;
      }
    };

    const members = (group) => h("details", { class: "gap-notes" },
      h("summary", {}, `What the notes said (${profileCount(group.count, "application")})`),
      h("ul", {}, group.members.map((m) => h("li", {},
        h("b", {}, m.title), " ", m.sent ? pill("", "sent") : null, m.kind === "silent" ? pill("info", "record silent") : null,
        h("p", { class: "muted" }, m.text)))));

    const card = (group) => {
      const a = form.answers[group.id] || (form.answers[group.id] = { answer: "", text: "", section: factSections[0] || NEW, newSection: "" });
      const name = `gap-${group.id}`;
      const body = h("div", { class: "stack" });
      const choice = (value, label) => h("label", { class: "gap-choice" },
        on(h("input", { type: "radio", name, value, checked: a.answer === value, disabled: off }), "change", () => {
          a.answer = value;
          if (value === "no" && !a.text) a.text = group.label;
          if (value === "yes" && a.text === group.label) a.text = "";
          drawBody();
          changed(true);
        }), h("span", {}, label));
      const drawBody = () => {
        if (a.answer === "yes") {
          const text = on(h("input", { type: "text", value: a.text, disabled: off, placeholder: "What you did, where, and a number if there is one",
            "aria-label": `What you did: ${group.label}` }), "input", (e) => { a.text = e.target.value; changed(); });
          const custom = on(h("input", { type: "text", value: a.newSection, placeholder: "New section's title", disabled: off,
            hidden: a.section !== NEW, "aria-label": "New section's title" }), "input", (e) => { a.newSection = e.target.value; changed(); });
          const select = on(h("select", { disabled: off, "aria-label": "Section of facts.md" },
            factSections.map((title) => h("option", { value: title, selected: a.section === title }, title)),
            h("option", { value: NEW, selected: a.section === NEW }, "A new section…")), "change", (e) => {
            a.section = e.target.value;
            custom.hidden = a.section !== NEW;
            changed(true);
          });
          fill(body,
            profileField("The fact, as a draft could use it", text, "Only what you could back up in an interview. It's added to facts.md as you write it."),
            profileField("Section of facts.md", select), custom);
        } else if (a.answer === "no") {
          fill(body, profileField("What you haven't done", on(h("input", { type: "text", value: a.text, disabled: off,
            "aria-label": `What you haven't done: ${group.label}` }), "input", (e) => { a.text = e.target.value; changed(); }),
          "Added under Unsupported in facts.md, so drafts stop guessing. To have the assay block it as a claim too, add it on Off limits."));
        } else if (a.answer === "dismiss") {
          fill(body, h("div", { class: "part-actions" },
            h("button", { class: "btn small", type: "button", disabled: off, onclick: (e) => question("dismiss", group.id, e.currentTarget) }, "Stop asking"),
            h("span", { class: "muted" }, "For a gap that's a decision rather than a fact, such as travel. Nothing in facts.md changes.")));
        } else {
          fill(body);
        }
      };
      drawBody();
      const silent = group.kinds.silent || 0;
      return h("section", { class: "panel stack gap-card", "aria-label": group.label },
        h("div", { class: "row" }, h("h3", { class: "profile-sub" }, group.label), h("span", { class: "spacer" }),
          pill(group.count >= 3 ? "warn" : "", profileCount(group.count, "application"))),
        silent ? h("small", { class: "muted" }, `In ${silent} of them the notes say the record is only silent, so you may have done it.`) : null,
        group.hint ? h("div", { class: "callout info" }, h("b", {}, "Your facts may already cover this: "), group.hint,
          h("p", { class: "muted" }, "Drafts written before that was added didn't have it. If it's covered, choose Doesn't apply.")) : null,
        members(group),
        h("div", { class: "gap-choices", role: "radiogroup", "aria-label": `Your answer: ${group.label}` },
          choice("yes", "Yes, I've done this"), choice("no", "No, I haven't"), choice("dismiss", "Doesn't apply"), choice("", "Not now")),
        body);
    };

    const asked = found.groups.filter((g) => g.state === "open" && g.count >= found.ask_from);
    const once = found.groups.filter((g) => g.state === "open" && g.count < found.ask_from);
    const answered = found.groups.filter((g) => g.state === "answered");
    const list = h("div", { class: "stack" });
    const drawList = () => fill(list,
      asked.length ? asked.map(card) : h("p", { class: "muted" }, found.applications
        ? "Nothing comes up as a gap in more than one application's notes right now."
        : "No application has notes yet. Each tailored draft lists its gaps there, and the ones that recur show up here."),
      once.length ? h("div", {}, h("button", { class: "btn small", type: "button", "aria-expanded": String(form.once), onclick: () => {
        form.once = !form.once;
        drawList();
      } }, form.once ? "Hide the gaps raised once" : `Show ${profileCount(once.length, "gap")} raised by one application`)) : null,
      form.once ? once.map(card) : null);
    drawList();

    const done = answered.length ? h("details", { class: "panel" },
      h("summary", {}, `Answered (${answered.length})`),
      h("ul", { class: "stack" }, answered.map((g) => {
        const said = { yes: "Yes", no: "No", dismissed: "Doesn't apply" }[g.answer.answer] || g.answer.answer;
        return h("li", {}, h("b", {}, g.label), ` · ${said}, ${String(g.answer.at).slice(0, 10)}`,
          g.answer.lines && g.answer.lines.length ? h("span", { class: "muted" }, `: “${g.answer.lines[0]}”`) : null,
          g.raised_again ? pill("warn", "raised again since") : null, " ",
          h("button", { class: "btn small", type: "button", disabled: off, onclick: (e) => question("forget", g.id, e.currentTarget) }, "Ask again"));
      }))) : null;

    changed(true);
    return {
      main: h("div", { class: "stack profile-form" },
        h("p", { class: "muted" }, `From the “Gaps to prepare for” lists in ${profileCount(found.applications, "application")}' notes, most often raised first. `
          + "Gaps are grouped by their wording, and each shows what the notes said, so check a group is one question before you answer it."),
        list, error, done, review),
      aside: h("div", { class: "panel stack" }, h("h2", {}, "How answers work"),
        h("p", {}, "A yes adds your words to facts.md, so drafts may use them. Write what you did, where, and a number if there is one."),
        h("p", {}, "A no goes under Unsupported, so drafts stop guessing and say so plainly."),
        h("p", { class: "muted" }, "Drafts you haven't sent that list the gap are flagged on the to-do list for rework. Sent applications are records and stay as they are.")),
    };
  },
});
