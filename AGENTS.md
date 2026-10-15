# Rules for AI coding agents (Devin and others)

Read this file, then `docs/SPEC.md`, then your task file in `docs/tasks/` **before writing any code**.

## Ground rules
1. **The spec is the contract.** Follow `docs/SPEC.md` (stack, names, schemas, endpoints, env vars). Do not swap frameworks, add React/Node build steps, or rename things. If something in the spec is impossible or clearly wrong, implement the closest working version and write what you changed and why in `docs/REVIEW_NOTES.md` under a heading for your task.
2. **Stay in scope.** Only build what your task file lists. Do not refactor or rewrite code from earlier tasks unless your task says so; if earlier code is broken, fix the minimum and note it.
3. **Never commit secrets.** No API keys, passwords, service-account JSON, `.env`, or `deploy/config.env`. Use env vars (see `.env.example`). This repository is **public**.
4. **Privacy rules are mandatory.** The collector must never record key values, input values, or passwords — only timings, key classes and value lengths (SPEC §5.2).
5. **Ground truth is never a feature.** `session_labels` and the `hg_label/hg_variant/hg_task` parameters must never feed `features.py` or the model.
6. **One features implementation.** All feature logic lives in `core/harnessguard_core/features.py` and is reused online and offline.
7. **Cross-platform.** The developer machine is **Windows** (PowerShell + Git for Windows + Docker Desktop; no WSL); deployment runs in **Google Cloud Shell (Linux)**. Use Python scripts or `docker compose` for dev tasks, keep shell scripts in `deploy/` as bash with LF line endings, use `pathlib` for paths, and do not rely on `make`.
8. **Everything must run locally** with `docker compose up --build` and `LLM_MODE=mock`, without any Google Cloud credentials. Cloud clients are only created when the relevant env var selects them.
9. **Tests.** Add pytest tests for the logic you write (at minimum: feature calculations on fixture events, API happy paths). `pytest` must pass before you finish.
10. **Keep docs current.** Update `README.md` (quickstart/status) and `.env.example` when you add commands or env vars.

## Git workflow
- **Work only in the local folder you were opened in.** It is already a clone of the repository, prepared by the developer. Do **not** clone the repository again, do not create another copy elsewhere, and do not use GitHub in any way: no `git clone`, `git fetch`, `git pull`, `git push`, `git remote` changes, `gh` CLI, or GitHub API/website access. All Git operations stay local.
- Work on the branch named in your task file (e.g. `feat/d1-portal`), created from the local `main`.
- Small, descriptive commits (`portal: add transfer review page`).
- Do **not** push; the developer pushes from PowerShell. Do **not** rewrite history on `main`.
- Finish with a short summary in `docs/REVIEW_NOTES.md`: what was built, how to run it, known gaps.

## Definition of done (every task)
- All acceptance criteria in the task file are met and checked by you.
- `docker compose up --build` starts cleanly; `pytest` passes.
- No secrets in the diff; no TODOs left in place of required features.
