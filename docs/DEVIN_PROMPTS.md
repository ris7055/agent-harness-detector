# Devin session prompts

Run **one session at a time**, in order. Before each session:

```bash
# in WSL, inside the repo folder
git checkout main && git pull
```

After each session:

```bash
git status                       # check nothing unexpected (no .env, no keys)
git push -u origin <branch-name>
```

Then open a pull request on GitHub and ask Claude to review it. Merge only after review, then start the next session from the updated `main`.

| # | Task file | Branch | When |
|---|---|---|---|
| 1 | `docs/tasks/D1-scaffold-portal.md` | `feat/d1-portal` | Oct 15–16 |
| 2 | `docs/tasks/D2-collector-scorer.md` | `feat/d2-scorer` | Oct 16 AM |
| 3 | `docs/tasks/D3-deploy.md` | `feat/d3-deploy` | Oct 16 PM, deploy, start human data collection |
| 4 | `docs/tasks/D4-redteam.md` | `feat/d4-redteam` | Oct 17 AM |
| 5 | `docs/tasks/D5-console-gemini.md` | `feat/d5-console` | Oct 17 PM |
| 6 | `docs/tasks/D6-ml-benchmark.md` | `feat/d6-ml` | Oct 18 |

---

## Prompt for every task session (replace `<TASK FILE>` and `<BRANCH>`)

```
You are building one part of HarnessGuard, a hackathon prototype in this repository.

Before writing any code, read these files fully, in this order:
1. AGENTS.md (rules you must follow)
2. docs/SPEC.md (the full technical specification, the single source of truth)
3. <TASK FILE> (your task for this session, with acceptance criteria)
Also read docs/REVIEW_NOTES.md for notes from earlier sessions.

Then:
- Create and switch to the git branch <BRANCH> from the current main.
- Build only what <TASK FILE> asks for, following docs/SPEC.md exactly (stack, names, endpoints, env vars, schemas).
- This machine is Windows with Docker Desktop. Run the stack with `docker compose up --build` and the tests with `pytest`; everything must work with LLM_MODE=mock and no Google Cloud credentials.
- Never commit secrets, .env files or deploy/config.env. The repository is public.
- Commit in small, descriptive commits. Do not push.
- Before finishing, go through every acceptance criterion in <TASK FILE>, check it, and tick it ([x]) in the task file. If one cannot be met, leave it unticked and explain why.
- Finish by adding a section "<BRANCH>" to docs/REVIEW_NOTES.md: what you built, how to run and test it, any deviations from the spec and why, known gaps.

Start by summarising your plan in 5-10 bullet points, then implement it.
```

---

## Prompt for fixing review comments

```
Read docs/REVIEW_NOTES.md, section "Review: <BRANCH>". Stay on branch <BRANCH>.
Fix every item marked MUST, and SHOULD items if they are quick. Keep following AGENTS.md and docs/SPEC.md.
Run `pytest` and `docker compose up --build` to confirm nothing broke.
Commit with messages starting "review:". Then reply under each item in REVIEW_NOTES.md with "Fixed in <commit>" or why not.
```

---

## Tips for working with Devin
- If a session gets long or confused, stop it, commit what works, and start a new session with the same prompt plus "Continue from the existing work on this branch; first run the tests and list which acceptance criteria are still open."
- If Devin tries to change the stack (e.g. to React/Next.js or another cloud), point it back to AGENTS.md rule 1.
- Keep sessions focused: one task file per session.
