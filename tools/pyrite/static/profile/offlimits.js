"use strict";
// Off limits: what drafts must never mention, and what you haven't done. Each is a line in facts.md, which tells the
// drafter, and a pattern under [guard], which the fact check blocks. Blocking a term writes both. Taking anything off
// lets drafts say more, so saving that asks for a code from this computer.

profileStep("offlimits", {
  render(ctx) {
    const data = ctx.data;
    const lists = data.off_limits_lists;
    const memo = ctx.memo;
    const blank = () => ({ add: [], drop_items: [], drop_patterns: [], add_patterns: [] });
    if (!memo.form) memo.form = { never: blank(), nottrue: blank(), test: "" };
    const form = memo.form;
    const off = !ctx.editable;
    const review = h("div", { class: "profile-review", "aria-live": "polite" }, profileReview(null));
    const tested = h("div", { "aria-live": "polite" });
    const unguarded = h("div");
    let last = null;
    const send = profileDrafter(ctx, (result, err) => {
      profileShowReview(review, result, err);
      if (result) {
        last = result.preview;
        showTest();
        showUnguarded(result.preview.unguarded);
      }
    });
    const changed = (now) => send({ never: form.never, nottrue: form.nottrue, test: form.test }, now);
    const toggle = (array, value) => {
      const at = array.indexOf(value);
      if (at >= 0) array.splice(at, 1);
      else array.push(value);
      draw();
      changed(true);
    };

    const KINDS = {
      never: { title: "Never mention", tone: "bad", pill: "blocked always", key: "forbidden",
        help: "Internal project names, customers, unreleased products. Blocked even in a sentence that denies them.",
        placeholder: "A name to block" },
      nottrue: { title: "Haven't done (yet)", tone: "warn", pill: "blocked as a claim", key: "unsupported",
        help: "Things postings ask for that you can't claim. A draft may still say you haven't done them.",
        placeholder: "A skill or claim to block" },
    };
    const panels = {};
    const advanced = {};
    const chip = (text, attrs, onRemove, label) => h("span", attrs, h("span", {}, text),
      h("button", { type: "button", "aria-label": label, title: label, disabled: off, onclick: onRemove }, "✕"));

    const draw = () => {
      for (const kind of Object.keys(KINDS)) {
        const k = KINDS[kind];
        const change = form[kind];
        const items = lists[kind].items.map((item) => {
          const going = change.drop_items.includes(item.line);
          return chip(item.text, { class: `profile-chip ${kind}${going ? " going" : ""}` },
            () => toggle(change.drop_items, item.line), going ? `Keep ${item.text}` : `Take off ${item.text}`);
        });
        const adding = change.add.map((term) => chip(term, { class: `profile-chip ${kind} new` },
          () => toggle(change.add, term), `Don't add ${term}`));
        fill(panels[kind], items.length || adding.length ? [...items, ...adding] : h("span", { class: "muted" }, "Nothing listed yet."));
        const patterns = lists[kind].patterns.map((pattern) => {
          const going = change.drop_patterns.includes(pattern);
          return chip(pattern, { class: `profile-chip pattern${going ? " going" : ""}` },
            () => toggle(change.drop_patterns, pattern), going ? `Keep ${pattern}` : `Remove the pattern ${pattern}`);
        });
        const extra = change.add_patterns.map((pattern) => chip(pattern, { class: "profile-chip pattern new" },
          () => toggle(change.add_patterns, pattern), `Don't add ${pattern}`));
        fill(advanced[kind], patterns.length || extra.length ? [...patterns, ...extra] : h("span", { class: "muted" }, "No patterns."));
      }
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

    const panel = (kind) => {
      const k = KINDS[kind];
      panels[kind] = h("div", { class: "profile-chips" });
      return h("section", { class: "panel stack", "aria-label": k.title },
        h("div", { class: "row" }, h("h3", { class: "profile-sub" }, k.title), h("span", { class: "spacer" }), pill(k.tone, k.pill)),
        h("small", { class: "muted" }, k.help),
        panels[kind],
        adder(k.placeholder, "Block it", (term) => {
          if (!form[kind].add.includes(term)) form[kind].add.push(term);
          draw();
          changed(true);
        }));
    };

    const advancedPanel = (kind) => {
      advanced[kind] = h("div", { class: "profile-chips" });
      return h("div", { class: "stack" }, h("b", {}, `${KINDS[kind].title}: ${KINDS[kind].key} under [guard]`), advanced[kind],
        adder("A pattern, such as \\bOsprey\\b", "Add pattern", (pattern) => {
          if (!form[kind].add_patterns.includes(pattern)) form[kind].add_patterns.push(pattern);
          draw();
          changed(true);
        }));
    };

    function showUnguarded(terms) {
      fill(unguarded, terms && terms.length ? h("div", { class: "callout bad" },
        h("b", {}, `Listed under Do not use, but nothing blocks ${terms.length === 1 ? "it" : "them"}: ${terms.join(", ")}`),
        h("p", {}, "The fact check reads only the patterns, so a draft could still name these."),
        h("div", { class: "row" }, terms.map((term) => h("button", { class: "btn small", type: "button", disabled: off, onclick: () => {
          if (!form.never.add.includes(term)) form.never.add.push(term);
          draw();
          changed(true);
        } }, `Block ${term}`)))) : null);
    }

    const sentence = h("input", { type: "text", value: form.test, "aria-label": "A sentence to test",
      placeholder: "Type anything a draft might say" });
    sentence.addEventListener("input", () => { form.test = sentence.value; changed(); });
    function showTest() {
      const test = last && last.test;
      if (!form.test.trim() || !test) {
        fill(tested, h("p", { class: "muted" }, "Type a sentence to see it as the fact check does."));
        return;
      }
      const parts = [];
      let at = 0;
      for (const hit of test.hits) {
        if (hit.start < at) continue;
        parts.push(test.text.slice(at, hit.start));
        parts.push(h("mark", { class: `profile-hit ${hit.kind}`, title: hit.pattern }, test.text.slice(hit.start, hit.end)));
        at = hit.end;
      }
      parts.push(test.text.slice(at));
      const said = { never: "is never to be mentioned", claim: "is claimed here, and you haven't done it", denied: "is allowed here: the sentence says you haven't done it" };
      fill(tested,
        h("p", { class: "profile-testline" }, parts),
        h("p", { class: test.blocked ? "error" : "profile-ok" }, test.blocked ? "A draft with this sentence would be blocked." : "This sentence would pass these checks."),
        test.hits.length ? h("ul", { class: "muted" }, [...new Set(test.hits.map((hit) => `“${test.text.slice(hit.start, hit.end)}” ${said[hit.kind]}.`))].map((line) => h("li", {}, line))) : null);
    }
    const examples = [
      ["A denial", "I have not worked under ISO 26262, but I built the bench it would need."],
      ["A clean line", "Cut boot time from 42 s to 9 s across the fleet."],
    ];

    const main = h("div", { class: "stack profile-form" },
      unguarded,
      h("div", { class: "profile-pair" }, panel("never"), panel("nottrue")),
      h("small", { class: "muted" }, "Blocking takes effect when you save. Taking something off lets drafts say more, so saving that asks for a code from this computer."),
      h("section", { class: "panel stack", "aria-label": "Test a sentence" },
        h("h3", { class: "profile-sub" }, "Test a sentence"), sentence,
        h("div", { class: "row" }, examples.map(([label, text]) => h("button", { class: "btn small", type: "button", onclick: () => {
          sentence.value = text;
          form.test = text;
          changed(true);
        } }, label))),
        tested),
      h("details", { class: "profile-advanced" }, h("summary", {}, "Advanced: the patterns the fact check uses"),
        h("p", { class: "muted" }, "Blocking a term above writes a pattern that also catches plurals, hyphens and spacing. Patterns are regular expressions, matched without regard to case."),
        advancedPanel("never"), advancedPanel("nottrue")),
      review);
    draw();
    showUnguarded(lists.unguarded);
    showTest();
    changed(true);
    return { main };
  },
});
