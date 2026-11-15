#!/usr/bin/env python3
"""Validate LEDGER.json for the multi-agent worktree protocol.

Exit codes: 0 valid, 1 violations, 2 unreadable.
--strict-lock-expiry additionally requires every file lock to carry an expiry.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

STATUSES = {"queued", "in-progress", "review", "rework", "blocked", "done", "dropped"}
ACTIVE = {"queued", "in-progress", "review", "rework", "blocked"}
TASK_FIELDS = {
    "task_id", "title", "status", "assignee", "reviewer", "branch",
    "file_scope", "acceptance_criteria", "blocked_by", "bounces", "history",
}
TOP_FIELDS = {"version", "updated_at", "file_locks", "last_merge", "tasks"}
HISTORY_CAP = 20


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate(ledger, strict_lock_expiry):
    problems = []
    missing = TOP_FIELDS - ledger.keys()
    if missing:
        return [f"missing top-level fields: {sorted(missing)}"]
    if not isinstance(ledger["tasks"], list):
        return ["tasks must be a list"]
    if not isinstance(ledger["file_locks"], dict):
        return ["file_locks must be an object"]

    now = datetime.now(timezone.utc)
    tasks = {}
    for task in ledger["tasks"]:
        tid = task.get("task_id", "<missing>")
        if tid in tasks:
            problems.append(f"duplicate task_id {tid}")
        tasks[tid] = task

        missing = TASK_FIELDS - task.keys()
        if missing:
            problems.append(f"{tid}: missing fields {sorted(missing)}")
        if task.get("status") not in STATUSES:
            problems.append(f"{tid}: invalid status {task.get('status')!r}")
        if task.get("branch") != f"agent/{task.get('assignee')}/{tid}":
            problems.append(f"{tid}: branch must be agent/<assignee>/{tid}")
        bounces = task.get("bounces")
        if not isinstance(bounces, int) or bounces < 0:
            problems.append(f"{tid}: bounces must be a non-negative integer")
        elif bounces >= 3 and task.get("status") in ACTIVE:
            problems.append(f"{tid}: bounces >= 3 while active; re-scope or drop")
        history = task.get("history")
        if not isinstance(history, list):
            problems.append(f"{tid}: history must be a list")
        elif len(history) > HISTORY_CAP:
            problems.append(f"{tid}: history exceeds cap of {HISTORY_CAP}")
        if task.get("status") in ACTIVE:
            for path in task.get("file_scope", []):
                lock = ledger["file_locks"].get(path)
                if lock is None:
                    problems.append(f"{tid}: active task has no lock on {path}")
                elif lock.get("task_id") != tid:
                    problems.append(f"{tid}: lock on {path} belongs to {lock.get('task_id')}")

    for path, lock in ledger["file_locks"].items():
        tid = lock.get("task_id")
        task = tasks.get(tid)
        if task is None:
            problems.append(f"lock {path}: unknown task_id {tid}")
            continue
        if lock.get("owner") != task.get("assignee"):
            problems.append(f"lock {path}: owner does not match assignee of {tid}")
        until = lock.get("until")
        if until is None:
            if strict_lock_expiry:
                problems.append(f"lock {path}: no expiry (strict mode)")
        else:
            try:
                if parse_ts(until) < now:
                    problems.append(f"lock {path}: expired at {until}")
            except (ValueError, AttributeError):
                problems.append(f"lock {path}: invalid until timestamp {until!r}")

    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger")
    parser.add_argument("--strict-lock-expiry", action="store_true",
                        help="require every file lock to carry an expiry")
    args = parser.parse_args()

    try:
        with open(args.ledger) as f:
            ledger = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unreadable ledger: {exc}")
        return 2

    problems = validate(ledger, args.strict_lock_expiry)
    if problems:
        for p in problems:
            print(f"VIOLATION: {p}")
        return 1
    print("ledger valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())