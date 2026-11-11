"use strict";
// Tools check: what `pyrite doctor` finds on this computer, as a page. Each program says what it's for, what still works
// without it and how to get it. Claude Code and mail are set up on the Settings tab, so theirs open it. Nothing is saved.

const PROFILE_TOOL_TONES = { true: ["good", "found"], false: ["bad", "missing"], null: ["", "not set up"] };

profileStep("tools", {
  readOnly: true,
  render() {
    const list = h("div", { class: "stack", "aria-live": "polite" }, h("p", { class: "muted" }, "Checking…"));
    const again = h("button", { class: "btn small", type: "button" }, "Check again");

    const row = (tool) => {
      const [tone, label] = PROFILE_TOOL_TONES[String(tool.ok)] || ["", "unknown"];
      const where = tool.settings ? h("button", { class: "btn small", type: "button", onclick: () => showTab(tool.settings) },
        `Set up on the Settings tab`) : null;
      return h("section", { class: "panel stack profile-tool", "aria-label": tool.name },
        h("div", { class: "top" }, h("h3", { class: "profile-sub" }, tool.name), pill(tool.ok === false && tool.required ? "bad" : tone, label),
          tool.required ? h("small", { class: "muted" }, "Every draft needs it") : h("small", { class: "muted" }, "Optional")),
        h("p", { class: "muted" }, tool.what),
        h("dl", { class: "profile-facts" },
          h("dt", {}, "What it's for"), h("dd", {}, tool.for),
          h("dt", {}, "Without it"), h("dd", {}, tool.without),
          tool.fix ? [h("dt", {}, tool.ok === true ? "Note" : "How to get it"), h("dd", { class: "profile-fix" }, withCode(tool.fix))] : null),
        where);
    };

    const load = async (fresh) => {
      again.disabled = true;
      if (fresh) fill(list, h("p", { class: "muted" }, "Checking…"));
      try {
        const found = await api(`/api/profile/tools${fresh ? "?fresh=1" : ""}`);
        fill(list, found.tools.map(row));
      } catch (err) {
        fill(list, h("p", { class: "error", role: "alert" }, err.message));
      }
      again.disabled = false;
    };
    again.addEventListener("click", () => load(true));
    load(false);

    return {
      main: h("div", { class: "stack profile-form" },
        h("div", { class: "row" }, h("p", { class: "muted" }, "Asking Claude Code takes a second or two, so its answer is kept for a minute."),
          h("span", { class: "spacer" }), again),
        list),
    };
  },
});
