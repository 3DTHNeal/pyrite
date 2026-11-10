"use strict";
// Workspace and backup: the private folder in use, how it was chosen, and how data/pyrite.db is kept. The database is the
// one file in it that can't be made again, so this section can copy it into data/backups. Nothing else is saved.

const profileSize = (bytes) => (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`);
const profileDay = (iso) => new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

profileStep("workspace", {
  readOnly: true,
  render() {
    const box = h("div", { class: "stack", "aria-live": "polite" }, h("p", { class: "muted" }, "Loading…"));

    const gitPanel = (about) => {
      const git = about.git;
      const commands = h("pre", { class: "profile-commands" },
        `git -C "${about.folder}" add -A\ngit -C "${about.folder}" commit -m "Back up my job search"`);
      let said;
      if (git.inside) {
        said = h("div", { class: "callout bad" }, h("b", {}, `This folder is inside the git repository at ${git.inside}.`),
          h("p", {}, "That repository must never commit it. If it's ever shared or public, move your workspace out of it."));
      } else if (!git.repo) {
        said = h("p", {}, "This folder isn't a git repository. ", h("code", {}, "pyrite init --git"),
          " on it makes one that keeps data/pyrite.db as its backup, and changes nothing else.");
      } else if (!git.tracked) {
        said = h("p", {}, "This folder is a git repository, but data/pyrite.db isn't kept in it, so the repository doesn't back it up. "
          + "Copies made here, or your own, are its backup.");
      } else {
        said = h("div", { class: "stack" },
          h("p", {}, "This folder is a git repository that keeps data/pyrite.db. ",
            git.committed ? `It was last committed ${profileDay(git.committed)}.` : "It hasn't been committed yet."),
          git.changed ? h("p", {}, "It has changed since. Commit when nothing is running, with no board check, Claude run or save under way, so the copy is whole:") : null,
          git.changed ? commands : null);
      }
      return h("section", { class: "panel stack", "aria-label": "Git" },
        h("h3", { class: "profile-sub" }, "Git"),
        said,
        git.repo && git.remote ? h("p", { class: "muted" }, "It has a remote. Keep that repository private: everything in this folder is yours.") : null);
    };

    const copiesPanel = (about) => {
      const kept = about.backups;
      const error = h("p", { class: "error", role: "alert" });
      const make = h("button", { class: "btn primary", type: "button", disabled: about.demo || !about.database.exists },
        about.demo ? "Backing up is off in the demo" : "Back up now");
      make.addEventListener("click", async () => {
        make.disabled = true;
        error.textContent = "";
        try {
          const done = await api("/api/profile/backup", {});
          toast(`Copied data/pyrite.db to ${kept.folder}/${done.made.name}.`);
          draw(done);
          loadProfile();
        } catch (err) {
          error.textContent = err.message;
          make.disabled = false;
        }
      });
      return h("section", { class: "panel stack", "aria-label": "Copies" },
        h("h3", { class: "profile-sub" }, "Copies on this computer"),
        about.database.exists
          ? h("p", {}, `data/pyrite.db is ${profileSize(about.database.bytes)}, last changed ${profileDay(about.database.changed)}. `
            + "It holds every job, what happened to it and what passed the fact check, and it can't be made again from anything else.")
          : h("p", { class: "muted" }, "There's no data/pyrite.db yet. The first board check or dashboard start makes it."),
        kept.copies.length
          ? h("ol", { class: "profile-copies" }, kept.copies.map((copy) => h("li", {},
            h("time", { datetime: copy.at }, profileDay(copy.at)), h("span", { class: "muted" }, ` · ${profileSize(copy.bytes)} · ${kept.folder}/${copy.name}`))))
          : h("p", { class: "empty" }, `No copies in ${kept.folder} yet.`),
        h("div", { class: "part-actions" }, make,
          h("span", { class: "muted" }, `Pyrite keeps the newest ${kept.keep}. It's safe while a run is going.`)),
        error,
        h("p", { class: "muted" }, `A copy on this computer is lost with it. From time to time, copy ${kept.folder} somewhere else, `
          + "such as a USB drive or a private cloud folder."),
        h("details", {}, h("summary", {}, "Putting a copy back"),
          h("p", {}, "Close the dashboard and wait for any run to finish. Then copy the backup over data/pyrite.db in this folder, "
            + "and delete data/pyrite.db-wal and data/pyrite.db-shm beside it if they're there. Start the dashboard again.")));
    };

    const draw = (about) => {
      fill(box,
        h("section", { class: "panel stack", "aria-label": "Folder in use" },
          h("h3", { class: "profile-sub" }, "Folder in use"),
          h("p", {}, h("code", { class: "profile-path" }, about.folder)),
          h("p", { class: "muted" }, about.demo
            ? "This is the fictional example that comes with Pyrite. Point PYRITE_HOME at your own workspace to use yours."
            : `${about.chosen_by} names it. Pyrite's code is in ${about.code}, which never holds anything of yours.`)),
        copiesPanel(about),
        about.demo ? null : gitPanel(about));
    };

    api("/api/profile/workspace").then(draw, (err) => fill(box, h("p", { class: "error", role: "alert" }, err.message)));
    return { main: h("div", { class: "stack profile-form" }, box) };
  },
});
