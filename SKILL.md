---
name: multi-agent-worktree-coding
description: Use when coordinating multiple coding agents (coordinator,
  orchestrator, worker) in isolated git worktrees with a shared LEDGER.json task
  ledger — especially when the agents run in Herdr tabs/panes and you need to
  start or re-establish worker/orchestrator sessions that are not yet running
  (no pane to message, pane_not_found, agent_not_found), relay messages, handle
  worker approval dialogs, bootstrap a repo with no remote, choose which
  CLI/model runs each role, assign tasks, review patches, merge agent branches,
  or update the ledger.
---
# Multi-Agent Worktree Coding

Coordinate 3 coding agents (coordinator, orchestrator, worker) working in
isolated git worktrees. This skill defines roles, message formats, git
protocol, ledger protocol, and validation.

## Roles and ownership

- **Coordinator** (owns `integration` branch and `LEDGER.json`): breaks down
  the user's task into milestone work orders, assigns tasks, resolves
  conflicts, merges approved branches, declares milestones done. Sole writer
  of the ledger.
- **Orchestrator** (owns architecture/integration): turns work orders into
  execution plans with file scopes, delegates subtasks to the worker,
  reviews patches, runs CI, reports PASS/FAIL with merge order.
- **Worker** (owns code): implements subtasks as small tested patches,
  asks instead of guessing, never refactors beyond scope.

Only the worker writes code; only the orchestrator approves and verifies;
only the coordinator changes priorities or declares done.

## Worktree and branch setup

One-time (coordinator):

```bash
git worktree add .trees/worker       -b agent/worker/base
git worktree add .trees/orchestrator -b agent/orchestrator/base
git worktree add .trees/coord        -b agent/coord/base
```

Rules for all agents:

1. Work only in your own worktree path and only on branches named
   `agent/<assignee>/<task_id>`, branched from `origin/integration`.
2. Never modify another agent's worktree. Reading (`git -C .trees/<other>
   log/diff/show`) is allowed.
3. Commit early; every commit message starts with the `task_id`.
4. Before starting or submitting work: `git fetch origin && git rebase
   origin/integration`. On conflicts outside your file scope, STOP and
   escalate to the orchestrator.
5. Handoff is via commits: a PATCH message contains only branch, commit
   range, diffstat, and test status.

## Bootstrap: fresh repo / no remote

The base protocol assumes `origin/integration`. Check `git log` and
`git remote -v` first and adapt when the repo is new or has no remote:

1. No commits yet → make an initial baseline commit of the project files.
2. Create the integration branch locally: `git branch integration`.
3. No `origin` → agents branch from and rebase against **local `integration`**,
   not `origin/integration`; skip `git fetch origin`.
4. Add `.trees/` to `.gitignore` before the baseline commit.
5. Create the worktrees branched from integration, and put the coordinator on
   integration so it can write the ledger:

```bash
git worktree add .trees/worker       -b agent/worker/base       integration
git worktree add .trees/orchestrator -b agent/orchestrator/base integration
git worktree add .trees/coord        -b agent/coord/base        integration
git -C .trees/coord checkout integration
```

6. Create the initial `LEDGER.json` at the repo root (use
   `ledger-example.json` from this skill as the template), copy
   `scripts/validate_ledger.py` into the repo, and commit both on
   `integration`.

Record the no-remote adaptation in the ledger history so a restarted agent
rebuilds the correct picture.

## Message format

```
[<SENDER> → <RECIPIENT>] <TYPE>
task_id: <id>
body: <content>
```

Types: `WORK_ORDER`, `PLAN`, `SUBTASK`, `REVIEW` (APPROVE/REJECT + notes),
`PATCH_READY`, `STATUS`, `QUESTION`, `DECISION`, `LEDGER_UPDATE`, `NOTE`.

## Agent session availability and bootstrap

A git worktree is not an agent session. The coordinator can assign work only
once the orchestrator and worker each have a **live, ready CLI session** in
their worktree. The most common stall is "nowhere to send the message": the
worktrees exist but the peer agents were never launched, or their panes
vanished. Verify availability before every work order; never block waiting on
a pane that does not exist.

### Preflight (before assigning work)

```bash
herdr agent list        # registered agents + states
herdr pane list         # raw panes (a pane can exist with no agent running)
```

Map each role to a live pane and classify:
- **ready** — agent present, state `idle`/`done` → send work.
- **blocked** — agent present, approval dialog on screen → resolve it first
  (see Handling worker approval dialogs).
- **absent** — no pane, or a pane with no running agent → bootstrap below.

A send that fails with `pane_not_found` / `agent_not_found` means the session
is gone: treat as absent and go to Recovery, not retry-in-a-loop.

### Bootstrap an absent agent (coordinator)

These are the mechanical launch steps. When peers are unexpectedly absent or
vanished mid-workflow, run the Recovery authorization gate below first, then
use these steps to (re)launch. During initial setup the user asked for, you
may run them directly.

1. Ensure the role's worktree exists (see Worktree and branch setup) and is on
   the expected branch.
2. Create a pane rooted at that worktree:

   ```bash
   herdr tab create --cwd .trees/orchestrator --label orchestrator --no-focus
   herdr tab create --cwd .trees/worker       --label worker       --no-focus
   ```

3. Launch the CLI. Prefer the supported-kind launcher — it waits for readiness
   and registers the agent:

   ```bash
   herdr agent start orchestrator --kind agy --pane <pane-id> --timeout 120000
   ```

   `--kind` supports `agy`, `gemini`, `qodercli`, `claude`, `codex`, and others
   (`herdr agent start --help`). For a CLI with **no** supported kind (e.g.
   Mistral `vibe`), launch it manually and let Herdr detect it:

   ```bash
   herdr pane run <pane-id> <cli-command>   # or: pane send-text <id> "<cmd>" + send-keys enter
   ```

4. Clear first-run dialogs (trust prompt, intro banner) and set the working
   mode — see Handling worker approval dialogs.
5. Verify ready before sending work:

   ```bash
   herdr agent wait <name> --until idle --timeout 120000
   herdr agent list
   ```

   If the agent is not detected, `herdr agent explain <pane-id>` shows why.

### Choosing the agent and model per role

`--kind` selects which CLI runs a role; the **model** is that CLI's own
concern, not a `herdr` flag. Each role can run a different CLI and model.

- **Supported kind** — forward the CLI's model flag after `--`; herdr passes
  trailing args to the agent executable:

  ```bash
  herdr agent start worker --kind claude --pane <pane-id> -- --model sonnet
  ```

- **Unsupported kind** (manual launch) — include the CLI's model flag in the
  command itself: `herdr pane run <pane-id> <cli-command-with-model-flag>`.

The exact flag and model names vary by CLI (e.g. `claude --model <alias>`);
check that CLI's `--help`. `herdr agent start` has no `--model` of its own —
the model flag goes after `--`, not before it.

### Recovery: vanished or never-started peers

Do not silently recreate or close panes. Surface the gap to the user
(`AskUserQuestion`) with the options: re-establish the missing agents, or have
the coordinator perform the review/merge directly. On authorization to
re-establish:

1. Re-create the pane and relaunch the CLI (Bootstrap above).
2. Re-sync the worktree to the expected branch and re-read `LEDGER.json` +
   branch state to rebuild the picture — a restarted agent rebuilds from the
   ledger, not from memory.
3. Re-run preflight; only then resume assigning work.

Only create or close panes you own. Re-establishing that requires syncing
another agent's worktree needs explicit user authorization.

## Running in Herdr

When the three agents run in Herdr tabs/panes, the coordinator relays
messages over the Herdr CLI instead of a shared chat. Prerequisite: run
inside a Herdr session (`HERDR_ENV=1`); load `herdr --skill` for the full
CLI reference. Sessions must exist first — see Agent session availability
and bootstrap above.

Discover the panes first — never guess identifiers:

```bash
herdr tab list
herdr agent list
```

**Target by pane ID or registered agent name, NOT the kind label.**
`herdr agent prompt <kind> ...` fails with `agent_not_found` when `<kind>`
is only the agent kind shown in `agent list`; use the pane ID (e.g.
`wE:p3`) or the registered tab name (e.g. `worker`).

Send a message (heredoc keeps multi-line bodies intact):

```bash
herdr agent prompt wE:p2 "$(cat <<'EOF'
[COORDINATOR → ORCHESTRATOR] WORK_ORDER
task_id: T1
body: <work order text>
EOF
)"
```

Wait for the agent to finish, then read its output:

```bash
herdr agent wait wE:p2 --timeout 120000
herdr agent read wE:p2 --source recent-unwrapped --lines 120
```

Agent states: `idle`/`done` = ready for input, `working` = busy,
`blocked` = an approval dialog is on screen.

### Handling worker approval dialogs

When an agent is `blocked`, read the pane to see the exact dialog (command,
options, highlighted option) before doing anything:

```bash
herdr agent read wE:p3 --source recent-unwrapped --lines 60
```

**Default: inspect the blocked UI and ask the user before answering it.**
Never auto-approve destructive or out-of-scope commands. Present the pending
command and options; once the user chooses, move the selection and confirm:

```bash
herdr agent send-keys wE:p3 down down enter   # move to the chosen option, confirm
```

If the user has given explicit standing authorization for benign prompts
(e.g. "allow for this session"), you may answer benign, in-scope prompts
without re-asking, but still reject anything destructive or outside the task's
file scope. Authorization for benign prompts is not authorization for risky
ones.

Common dialog mechanics (verify against the live pane; UIs differ by CLI):
- **vibe (worker):** options 1–4. Approve a benign command with option 2
  ("Allow for remainder of this session"): `send-keys <pane> down enter`.
  Reject with `esc`. Cycle ask→accept-edits mode with `shift+tab`.
- **agy (orchestrator):** permission options 1–4; option 1 ("Yes, run command")
  is the default → approve with `enter`. Confirm the trust prompt with `enter`;
  dismiss the intro banner with `esc`.

`send-keys` names: `down`, `up`, `enter`, `esc`, `ctrl+c`, `shift+tab`. After
answering, `wait` + `read` to confirm the agent resumed.

**Queued messages:** a message sent while an agent is mid-turn is queued and
only processed when the turn ends. To force a correction (e.g. revert an
out-of-scope edit), interrupt with `send-keys <pane> ctrl+c`, wait for `idle`,
then re-send. A queued NOTE alone will not interrupt a running turn.

### Herdr quick reference

| Action | Command |
|---|---|
| List tabs / agents / panes | `herdr tab list` / `herdr agent list` / `herdr pane list` |
| Create a pane | `herdr tab create --cwd <path> --label <name> --no-focus` |
| Launch supported agent | `herdr agent start <name> --kind <kind> --pane <id>` |
| Run a CLI in a pane | `herdr pane run <id> <cmd>` |
| Send message (registered) | `herdr agent prompt <pane> "<msg>"` |
| Wait until idle | `herdr agent wait <pane> --until idle --timeout <ms>` |
| Read output (registered) | `herdr agent read <pane> --source recent-unwrapped --lines N` |
| Answer dialog | `herdr agent send-keys <pane> down ... enter` |
| Diagnose detection | `herdr agent explain <pane>` |

A freshly created pane has no registered agent yet: drive it with
`herdr pane send-text <id> "<text>"` + `herdr pane send-keys <id> enter`, and
read it with `herdr pane read <id> --lines N`. Once the agent is detected,
switch to the `herdr agent prompt/wait/read` family.

Do not close tabs/panes/sessions you did not create, and never stop the
Herdr server or kill its main process from an active session, unless the
user explicitly asks.

## LEDGER.json protocol

`LEDGER.json` lives at the repo root of `integration`. Single-writer: only
the coordinator commits it (batching pending `LEDGER_UPDATE` requests).
All agents re-read it after every rebase and check: their tasks, file
locks, and `last_merge` (if it postdates their branch point, rebase again).

Task fields: `task_id`, `title`, `status` (queued | in-progress | review |
rework | blocked | done | dropped), `assignee`, `reviewer`, `branch`,
`file_scope`, `acceptance_criteria`, `blocked_by`, `bounces`, `history`
(append-only, cap ~20 entries). Top-level: `version`, `updated_at`,
`file_locks` (path → {owner, task_id, until}), `last_merge`.

Conflict rule: two tasks requesting the same file lock → coordinator grants
the older `task_id` and serializes the other. Recovery: a restarted agent
rebuilds its view solely from `LEDGER.json` + branch state.

## Validation gate

The orchestrator runs `scripts/validate_ledger.py LEDGER.json
--strict-lock-expiry` before any APPROVE; CI runs it on every ledger commit.
Exit 0 = valid, 1 = violations, 2 = unreadable. A task with `bounces >= 3`
still active must be re-scoped or dropped by the coordinator.

Provisioning: copy `scripts/validate_ledger.py` from this skill into the
repo's `scripts/` (the coordinator does this during bootstrap). The gate
enforces two invariants worth remembering when writing the ledger:

- Every **active** task (queued/in-progress/review/rework/blocked) must hold
  a file lock on **every** path in its `file_scope`, owned by that task.
- `--strict-lock-expiry` requires each lock to carry a non-expired `until`
  timestamp; refresh expiries when a task runs long.

`ledger-example.json` in this skill is a valid reference ledger.

## Shared rules

1. Every message carries a `task_id`. No orphan work.
2. Disagreement: escalate one hop toward the coordinator with a 3-line
   summary (options, tradeoffs, recommendation).
3. Messages ≤ 20 lines unless a patch or plan requires more.
4. Loop guard: a task bouncing more than 3 times is re-scoped or dropped.
5. Integration merges: coordinator merges approved branches in the
   orchestrator's `merge_order` (rebase merges), runs the full suite, and
   on failure reverts (never hand-fixes on `integration`); the fix goes
   through the normal task flow. Delete merged branches afterwards.

### Merge mechanics (coordinator)

Run from the coordinator worktree (on `integration`). For each approved
branch in `merge_order`:

```bash
git -C .trees/coord checkout integration
git -C .trees/coord merge --ff-only agent/worker/<task_id>   # after worker rebased onto integration
# run the full suite here; on failure: git revert, never hand-fix
git -C .trees/coord branch -d agent/worker/<task_id>
```

The worker rebases its task branch onto the latest `integration` before
`PATCH_READY`, so the coordinator's merge is a fast-forward. If it is not,
send the branch back for rebase rather than forcing a merge commit. After
merging, update `LEDGER.json` (task → done, release its file locks, set
`last_merge`), commit the ledger, and notify the orchestrator.

### Branch base and scope checks (coordinator)

- The worker branches each task from the **current** `integration` HEAD
  (`git rev-parse integration`), never a remembered SHA from an earlier task.
  Verify the base before accepting work — a stale base silently drops earlier
  tasks' changes.
- Verify scope per commit with `git show <commit> --stat`, not
  `git diff integration..HEAD`: branch-point divergence can list `LEDGER.json`
  (or other files) as changed even when the worker never touched them.
- Reject out-of-scope commits: send the worker a revert instruction
  (`git checkout -- <out-of-scope-file>`) and require a commit of only the
  in-scope files before review.

## Safety

- Never work on `master` directly. Code changes go through the worker on
  `integration`; merge `integration`→`master` only on an explicit user request.
- Commit only when authorized (the workflow's task/ledger commits are
  authorized; ad-hoc commits are not). Never force-push, `reset --hard`, or
  skip hooks without an explicit user request.
- Pushing to a remote is a handoff: follow the security-scan handoff gate
  before `git push`.
