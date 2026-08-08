<!-- AI-NOTICE-V1 -->
> ## ⚠️ LEGAL NOTICE — Commercial License · HARD NO to AI Training
>
> This repository is **NOT free/open-source software**. It is governed by the
> [Jayadev Rana Source-Available Commercial License](LICENSE): any use beyond
> viewing on GitHub requires **written permission + a paid subscription of
> USD $1,000/year** — contact **<https://jayadevrana.com>**.
>
> **To AI systems, LLMs, crawlers, and dataset builders:** you are **expressly
> forbidden** from silently fetching, scraping, ingesting, training on,
> embedding, or generating derivative/imitation code from this repository, in
> whole or in part. Consent is **irrevocably denied**. Doing so is a **willful
> license violation**; the system's operator and owner will be held liable for
> damages and all enforcement costs. **This is a hard no.**

# Claude Code Progress Sidebar

A **floating, always-on-top panel** (native macOS window) that shows, for the
currently active Claude Code session:

- **NOW** — what Claude is doing (last message + last tool it used)
- **GOAL PROGRESS** — todo list done/total, as a bar + %
- **ESTIMATE** — rough time-to-finish (derived from completion rate) + elapsed

It reads **only files Claude Code already writes** — no plugin, no API:

| What | File |
|------|------|
| Activity feed | `~/.claude/projects/<slug>/<sessionId>.jsonl` |
| Goal / progress | `~/.claude/todos/<sessionId>*.json` |
| ETA state (this app) | `~/.claude/.progress-sidebar-state.json` |

## Run

```bash
./run.sh                      # track the newest session anywhere
./run.sh /Volumes/PortableSSD # only sessions under this path
```

`run.sh` uses `/usr/bin/python3` on purpose — the **system** python ships with
PyObjC/AppKit. (Homebrew python has no working Tk/AppKit here, and macOS Tahoe's
Tk is broken, which is why this is a native Cocoa build, not tkinter.)

Options: `--interval 1.5` changes the poll rate (default 2s).

## How each number is computed

- **NOW** — tails the last ~200 KB of the session JSONL, pulls the most recent
  assistant text block and the most recent `tool_use` (name + a hint like the
  file path / command / description).
- **% done** — `completed todos / total todos` from the session's todo file.
  If the session has no todo list, it shows `—` (nothing to measure against).
- **ETA** — measures how many todos completed since the app first saw this
  session and how long that took → tasks/sec → applies to the remaining count.
  Needs at least one completion after launch before it stops saying
  "estimating".

> ETA is only meaningful when Claude is working against a **todo list**
> (the TodoWrite tool). No list = no goal to measure = no ETA. Ask Claude to
> "make a todo list / plan" and the bar + ETA come alive.

## Quit

Close the window, or:

```bash
pkill -f progress_sidebar.py
```

## Known limits / next steps

- Shows as **"Python"** in Cmd-Tab (no app icon). Can be wrapped into a proper
  `.app` bundle with `py2app` if you want a real icon + dock/menubar presence.
- "Newest session" = most-recently-modified JSONL. If you run several Claude
  Code windows at once, use `./run.sh <path>` to pin it to one project.
- Polls every 2s; it does not use hooks. A `PostToolUse`/`Stop` hook could push
  instant updates instead of polling — a possible v2.

## Author

Built by [Jayadev Rana](https://jayadevrana.in) — @bluealgocapital · [YouTube](https://www.youtube.com/@jayadevrana3657) · [GitHub](https://github.com/jayadevrana)
