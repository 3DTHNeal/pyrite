"use strict";
// Work history: employers, their roles and dates, and lines such as Education. Saved to the Timeline in facts.md a
// line at a time, with notes and wording you added kept, and to the matching headings in your master resume.

profileStep("history", {
  render(ctx) {
    const data = ctx.data;
    const memo = ctx.memo;
    if (!memo.form) {
      memo.form = {
        employers: data.timeline.employers.map((e) => ({
          line: e.line, name: e.name,
          roles: e.roles.map((r) => ({ line: r.line, title: r.title, place: r.place, start: r.start, end: r.end === "Present" ? "" : r.end })),
        })),
        other: data.timeline.other.map((o) => ({ line: o.line, label: o.label, text: o.text })),
        expected: data.expected.map((x) => ({ ...x })),
      };
    }
    const form = memo.form;
    const off = !ctx.editable;
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const preview = h("div", { class: "stack" });
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) fill(preview, previewOf(result.preview));
    });
    const changed = () => send({ employers: form.employers, other: form.other, expected: form.expected });

    const input = (value, label, onInput, attrs = {}) => {
      const el = h("input", { type: "text", value, "aria-label": label, disabled: off, ...attrs });
      el.addEventListener("input", () => { onInput(el.value); changed(); });
      return el;
    };
    const remove = (label, onClick) => h("button", { class: "btn small danger", type: "button", "aria-label": label, title: label, disabled: off,
      onclick: () => { onClick(); draw(); changed(); } }, "✕");

    const list = h("div", { class: "stack" });
    let focusNext = null;
    const draw = () => {
      fill(list, form.employers.map((employer, ei) => {
        const name = input(employer.name, "Employer", (v) => { employer.name = v; }, { class: "profile-employer-name" });
        if (focusNext && focusNext.employer === employer && focusNext.name) setTimeout(() => name.focus());
        return h("div", { class: "profile-employer" },
          h("div", { class: "row" }, name, h("span", { class: "spacer" }),
            h("button", { class: "btn small", type: "button", disabled: off, onclick: () => {
              const role = { line: null, title: "", place: employer.roles[0] ? employer.roles[0].place : "", start: "", end: "" };
              employer.roles.unshift(role);
              focusNext = { role };
              draw();
            } }, "+ Add a role"),
            remove(`Remove ${employer.name || "this employer"}`, () => form.employers.splice(ei, 1))),
          h("div", { class: "profile-role profile-role-head", "aria-hidden": "true" },
            h("span", {}, "Title"), h("span", {}, "Place"), h("span", {}, "From"), h("span", {}, "To"), h("span", {})),
          employer.roles.map((role, ri) => {
            const title = input(role.title, "Title", (v) => { role.title = v; });
            if (focusNext && focusNext.role === role) setTimeout(() => title.focus());
            return h("div", { class: "profile-role" }, title,
              input(role.place, "Place", (v) => { role.place = v; }),
              input(role.start, "From", (v) => { role.start = v; }, { placeholder: "Jan 2020" }),
              input(role.end, "To, empty for Present", (v) => { role.end = v; }, { placeholder: "Present" }),
              remove(`Remove ${role.title || "this role"}`, () => employer.roles.splice(ri, 1)));
          }));
      }));
      fill(others, form.other.map((line, oi) => h("div", { class: "profile-other" },
        input(line.label, "Label", (v) => { line.label = v; }, { placeholder: "Education" }),
        input(line.text, "Text", (v) => { line.text = v; }),
        remove(`Remove ${line.label || "this line"}`, () => form.other.splice(oi, 1)))));
      fill(expected, form.expected.map((item, xi) => h("div", { class: "profile-other" },
        input(item.label, "What it is", (v) => { item.label = v; }, { placeholder: "Degree" }),
        input(item.text, "Words every resume should include", (v) => { item.text = v; }),
        remove(`Stop expecting ${item.label || item.text || "this"}`, () => form.expected.splice(xi, 1)))));
      focusNext = null;
    };
    const others = h("div", { class: "stack" });
    const expected = h("div", { class: "stack" });
    const addEmployer = h("button", { class: "btn", type: "button", disabled: off, onclick: () => {
      const employer = { line: null, name: "", roles: [{ line: null, title: "", place: "", start: "", end: "" }] };
      form.employers.unshift(employer);
      focusNext = { employer, name: true };
      draw();
    } }, "+ Add an employer");

    const unread = data.timeline.unread.length
      ? h("div", { class: "callout info" }, h("b", {}, "Shown as written"),
        h("p", {}, "These Timeline lines don't read as an employer or a labelled line, so they stay as they are. Drafts can still use them."),
        h("ul", {}, data.timeline.unread.map((u) => h("li", {}, u.text))))
      : null;
    const heading = data.heading_source;
    const source = heading.path && !heading.written
      ? h("div", { class: "callout info" }, h("b", {}, `Every draft's headings are checked against ${heading.path}.`),
        h("p", {}, "This section changes the Timeline in facts.md, and profile/resume.md if you have one. Change the headings in that file to match."))
      : null;

    function previewOf(p) {
      const heads = p.headings;
      return [
        heads ? h("div", { class: "paper-lines" }, heads.map((row) => h("div", { class: row.startsWith("#### ") ? "role" : "employer" },
          row.replace(/^#+\s*/, "")))) :
          h("div", { class: "paper-lines" }, p.timeline.map((e) => [
            h("div", { class: "employer" }, `${e.name} | ${e.start} – ${e.end}`),
            e.roles.map((r) => h("div", { class: "role" }, [r.title, r.place, `${r.start} – ${r.end}`].filter(Boolean).join(" | ")))])),
        p.gaps.length ? h("ul", { class: "muted profile-gaps" }, p.gaps.map((g) => h("li", {}, g))) : null,
      ];
    }

    draw();
    changed();
    return {
      main: h("div", { class: "stack profile-form" },
        source,
        h("p", { class: "muted" }, "Newest first. Dates as Jan 2023 or 2023; leave To empty for a role you're in now. A note after the dates in facts.md stays as it is."),
        h("div", {}, addEmployer), list, unread,
        h("h3", { class: "profile-sub" }, "Education, certifications and other lines"),
        others,
        h("div", {}, h("button", { class: "btn small", type: "button", disabled: off, onclick: () => {
          form.other.push({ line: null, label: "", text: "" });
          draw();
        } }, "+ Add a line")),
        h("h3", { class: "profile-sub" }, "On every resume"),
        h("p", { class: "muted" }, "Words a resume should always include, such as your degree. A draft without them gets a warning, not a block."),
        expected,
        h("div", {}, h("button", { class: "btn small", type: "button", disabled: off, onclick: () => {
          form.expected.push({ text: "", label: "" });
          draw();
        } }, "+ Add one")),
        review),
      aside: h("div", { class: "panel" }, h("h2", {}, "Experience, as drafts must write it"), preview),
    };
  },
});
