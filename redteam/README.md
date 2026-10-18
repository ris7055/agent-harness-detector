# HarnessGuard red team

Generates **labelled automated sessions** against your own Bank Seroja demo
portal, so the detector has a non-human adversary to measure against (used by
the D6 benchmark).

## Scope and ethics

These agents are **ordinary browser automation**. They do **not** hide that they
are automated: no `navigator.webdriver` spoofing, no fake fingerprints, and no
synthetic human-like mouse or keystroke timing. Detecting stock automation is the
realistic threat model for agent-driven banking fraud today.

A **stealth / anti-detection** variant is intentionally **not** included. Building
a tool to slip automated agents past fraud and bot defences is out of scope; it is
documented as a Limitation / Future Work item in the benchmark instead.

The runner refuses any target other than `localhost` unless you pass
`--i-own-this-target` (for your own Cloud Run deployment). Never point it at a
system you do not own.

## Setup (laptop)

```powershell
# from the repo root
pip install -r redteam/requirements.txt
playwright install chromium
```

For the LLM variants, set a Gemini key (local dev) or use Vertex:

```powershell
$env:LLM_MODE = "apikey"           # apikey | vertex | mock
$env:GEMINI_API_KEY = "<your key>" # never commit this
```

`LLM_MODE=mock` (the default) runs the agent loop with a deterministic offline
policy -- no key needed, useful for a dry run and for tests.

## Run

```powershell
# from the repo root; start the local stack first: docker compose up --build
python redteam/run.py --base-url http://localhost:8080 --variant script_fill --n 5
python redteam/run.py --base-url http://localhost:8080 --variant script_type --n 5
python redteam/run.py --base-url http://localhost:8080 --variant llm_headless --n 10
```

Each run appends one JSON line to `data/redteam_runs.jsonl`
(`variant, task_type, outcome, steps, duration_s, error`) and labels the session
`agent` via `/collect/agent`. Outcomes: `allow`, `step_up`, `block`, `incomplete`,
`error`.

## Variants

| variant        | how it drives the page                         | browser  |
|----------------|------------------------------------------------|----------|
| `script_fill`  | `page.fill` (instant)                          | headless |
| `script_type`  | `page.type` with a 60 ms per-key delay         | headless |
| `llm_headless` | Gemini observe->act loop                       | headless |
| `llm_headed`   | Gemini observe->act loop                       | headed   |
