---
name: pdp:session-wrap
description: End-of-session doc/memory sync — survey what actually changed (git + openspec status), update stale CLAUDE.md files, docs/RUNBOOK.md, and the persistent memory index, then commit (and, after confirming, push) the doc-only changes. Use at the end of a work session, or when the user asks to "wrap up", "sync docs", or "update CLAUDE.md/memory before we stop".
metadata:
  author: pdp
  version: "1.0"
---

Keep the repo's self-documentation (CLAUDE.md hierarchy, `docs/RUNBOOK.md`, and the persistent
cross-session memory) in sync with what actually happened this session, so the next session (or a
fresh Claude instance) can pick up with minimal re-derivation. This is a **skill**, not a hook —
staleness detection and prose rewriting need judgment (deciding *which* doc lines are now wrong and
what to say instead), which a deterministic shell hook can't do. A hook can only remind you to run it.

## When to run

- User explicitly asks to wrap up, sync docs, or update CLAUDE.md/memory/runbook.
- End of a session that did non-trivial implementation, archived an OpenSpec change, or discovered
  something a future session would otherwise have to re-derive.
- Don't run it for tiny sessions (a one-line fix, a question answered) — nothing will be stale.

## Steps

1. **Survey what changed, don't assume.**
   ```
   git status --short
   git log --oneline -10
   git diff --stat
   openspec list --json
   ```
   For any change whose `status` looks further along than what CLAUDE.md/memory currently claims
   (newly archived, task-count increased, newly created), read its `tasks.md` and the touched source
   files directly — don't trust a stale memory or doc as ground truth. If several changes moved (e.g.
   background/parallel work landed mid-session), note all of them, not just the one you were focused on.

2. **Find candidate stale docs.**
   ```
   git diff --name-only <last-known-good-ref>..HEAD   # or since session start
   ```
   Map touched paths to their nearest `CLAUDE.md` (root, `backend/CLAUDE.md`, `backend/pdp/<mod>/CLAUDE.md`,
   `app/CLAUDE.md`, `docs/CLAUDE.md`). Only open docs whose claims plausibly changed — module maps,
   "active files" tables, roadmap/chunk status lines, settings tables, command examples. Skip docs
   nothing touched.

3. **Update root `CLAUDE.md`** — the `Program roadmap` section's per-chunk status (✓ done / N-of-M /
   in-progress), and any sub-program block (e.g. a nested "N-change program" summary) whose change
   statuses moved. Keep entries terse (one line + a parenthetical), matching existing style — this
   file is loaded every session, so bloat is expensive.

4. **Update module-level `CLAUDE.md` files** whose "Active files" / module-map table is missing a
   file that now exists, or describes behavior that changed (e.g. a flag's default flipped, a new
   collection was added, a local-file mode became DB-first). Prefer editing existing tables/rows over
   adding new prose sections.

5. **Update `docs/RUNBOOK.md`** where a command's actual behavior no longer matches what's documented
   (flag defaults, new endpoints, new OpenSearch index families/dashboards, new skills). Grep for the
   feature area first (`grep -n -i "<topic>" docs/RUNBOOK.md`) rather than re-reading the whole file.

6. **Update persistent memory** at
   `C:\Users\prasa\.claude\projects\c--Users-prasa-OneDrive-Desktop-komalavalli-PDP\memory\`:
   - Update (don't duplicate) the relevant `project` memory file(s) with what completed/archived and
     what's now in progress, including exact task-count and which files are uncommitted.
   - Refresh the "next session priorities" list so it reflects reality — stale priorities are worse
     than none, since a future session will act on them.
   - Update `MEMORY.md` index lines (≤150 chars each) for any file you touched.
   - Follow the memory-writing rules from the system prompt: no code-pattern/architecture facts
     (derivable from the repo), no git-history dumps, `**Why:**`/`**How to apply:**` structure for
     feedback/project memories, `[[links]]` between related memories.
   - If you discover an in-flight, uncommitted change made by a parallel/background process during
     this survey, record it factually (files touched, task-count) — don't guess intent beyond what
     tasks.md / the diff shows.

7. **Verify before asserting.** Before writing any file path, function name, task count, or "N/M done"
   claim into a doc or memory, confirm it against the current repo state (`Read`/`Grep`/`openspec status`),
   not against what an earlier part of the conversation said — state may have moved since.

8. **Commit the doc/memory sync — scoped, not bundled.**
   - Stage **only** the documentation files this skill changed (root/module `CLAUDE.md`,
     `docs/RUNBOOK.md`, other `docs/*.md`) — an explicit file list, never `git add -A`.
   - Do **not** bundle in-progress feature code (e.g. a partially-done OpenSpec change's source
     edits) into this commit unless the user has separately asked for that code to be committed.
     Doc-sync and feature-code commits are different concerns; keep them separable in history.
   - Memory files live outside the repo (`~/.claude/projects/.../memory/`) and are never part of a
     git commit — they persist independently.
   - Commit message: summarize what was synced and why (e.g. "docs: sync CLAUDE.md/RUNBOOK after
     backtest-results-warehouse archive"), not a line-by-line diff description.

9. **Push — after a lightweight confirmation, every run.** Show the user the commit (hash + one-line
   summary + `git status` confirming nothing unintended is included), then push the current branch
   (`git push`). Never force-push. Never push to `main` directly if the current branch isn't `main`
   unless the user says otherwise. If the push fails (diverged remote, no upstream), report it and
   ask rather than force-pushing or setting upstream blindly on a shared branch.

10. **Close with a short status, not a wall of text.** End with: what was synced (bullet list of
    files), the commit hash, whether the push succeeded, and — if relevant — one line naming the
    clearest next task for the next session (pull it from the memory priorities you just wrote,
    don't re-derive it).

## Notes

- This skill deliberately does **not** try to make every doc perfect — it targets the docs whose
  claims are now factually wrong or would waste a future session's tokens re-deriving. Cosmetic
  polish is out of scope.
- If the user wants this to fire automatically (not just on request), that requires a Claude Code
  hook (e.g. on session end) that reminds/invokes this skill — that's a `settings.json` change via
  the `update-config` skill, separate from this skill's own content.
