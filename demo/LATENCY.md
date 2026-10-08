# Demo latency: what was slow and what fixed it

Measured on 2026-10-07 on the GTC demo machine (Windows 11 ARM64, 30 GB RAM, Qwen3.6-35B-A3B Q4_K_M on llama-server, Hermes desktop app, profile `chief-of-staff`). All timings are wall-clock from the user's message to the agent's final reply unless stated otherwise, taken from the Hermes session database (`state.db`, `messages.timestamp`).

The demo runs four queries in a fresh chat after a workspace reset:

1. `hey chief of staff, what should i work on today?`
2. `help me prepare for the exec review`
3. `Hey chief of staff, update the status of the NeoAgent V2 tracker`
4. `Draft an email to Rafael asking for updates`

## Headline numbers

| Step | Before | After | Main cause of the difference |
|---|---|---|---|
| Workspace reset (`demo/reset_workspace.py`) | ~90 s | ~37 s | sequential Google batches of 5 |
| Query 1, first chat of the day | 38–45 s | ~35 s cold, 2 model calls | skill re-fetched 3×, saved brief not reused |
| Query 2 | 47–52 s | ~30 s expected | dead Gmail IDs, wrong launcher path |
| Query 3 | 58–102 s | ~50 s | 9 model turns, unbounded thinking, temperature 1.0 |
| Morning cron brief | 172–174 s | ~60 s expected | launcher could not find Python without `HERMES_HOME` |

Everything that is left is model time on the local GPU/CPU: prompt processing, thinking, and generating the answer. The Google API calls now total under 7 seconds per query.

## Where the time actually went

A representative pre-fix query 3 (58 s):

| Step | Who | Time |
|---|---|---|
| Decide to open the tracker reference | model | 6 s |
| Decide to read the sheet | model | 5 s |
| Read the sheet | Google API | 2.7 s |
| Reconcile eight lanes against the evidence | model thinking | 22 s |
| Write the update | Google API | 2.2 s |
| Decide to read back | model | 8 s |
| Read back | Google API | 1.9 s |
| Write the report | model | 10 s |

Lesson: every extra tool round trip costs 3–8 s of model overhead even when the tool itself takes 2 s. Cutting round trips mattered more than making any individual script faster.

## Fixes, in the order they were found

### 1. The scheduled morning brief was generated but never reused

The cron job `Morning daily brief` (07:00 weekdays) writes the finished brief; `daily_brief.py` is supposed to serve it instead of pulling Gmail/Calendar/Drive/Tasks again. The check only accepted the heading in bold (`**What You Need to Know**`). The local model sometimes writes it as a Markdown heading (`## What You Need to Know`), so the saved brief was silently discarded and query 1 fell back to a 15 s workspace pull plus full regeneration.

- `skills/productivity/chief-of-staff/scripts/daily_brief.py`: match the heading regardless of Markdown markup.

### 2. Background Hermes jobs were competing for the single model slot

`auxiliary.title_generation` and `auxiliary.background_review` were running mid-demo even though the profile config appeared to disable them: the profile `config.yaml` had silently lost those keys (and `skills.auto_load`). With `-np 1` on llama-server, a title call (which once timed out after 30 s) blocks the next turn and evicts the prompt cache, forcing the full ~11k-token system prompt to be re-read.

- Re-applied with the Hermes CLI (`hermes --profile chief-of-staff config set ...`): `auxiliary.title_generation.enabled=false`, `auxiliary.title_generation.model_upgrade_enabled=false`, `auxiliary.background_review.enabled=false`.

### 3. The skill was fetched on every query

`skills.auto_load: [chief-of-staff]` had also dropped out of the profile config, so the model spent three round trips at the start of query 1 fetching the skill, the ingest skill, and a reference file (about 20 s).

- Re-applied `skills.auto_load`; the skill now renders into the system prompt once per chat.
- `SOUL.md`: tells the model the skill is already loaded and not to call `skill_view` for it.

Query 1 went from 5 model calls to 2.

### 4. Workspace reset: sequential tiny batches

`demo/seed_workspace.py` sent every Google call in batches of 5, one batch at a time, with a sleep between batches: 59 round trips. Google processes a batch mostly serially, so a Calendar or Gmail batch costs ~2.5 s regardless of size.

- Batch size 25 (Gmail imports 10, to stay under 250 quota units/s).
- Independent batches run concurrently on per-thread authorised transports (4 wide; Gmail imports 2 wide). The existing per-request throttle retry is unchanged.
- The four task-document re-uploads to Drive run in parallel (`demo/task_scenario.py`).

| Phase | Before | After |
|---|---|---|
| Gmail import of 82 messages | 28 s | 15 s |
| Delete old mail and 89 calendar events | 21 s | 4 s |
| Create 89 calendar events | 17 s | 3 s |
| Re-upload 4 task documents | 12 s | 4 s |
| Total | 91 s | 37 s |

Gmail import is the floor: pushing it wider exceeds the per-second quota and triggers retries.

### 5. Reset no longer needs `HERMES_HOME`

The reset script looked for the state file in the root Hermes folder unless `HERMES_HOME` was exported. It now resolves the profile the desktop app has selected (`%APPDATA%\Hermes\active-profile.json`), and exports the resolved home so the ingest credential helper agrees. `HERMES_HOME` still overrides.

### 6. Dead Gmail links after a reset

Every reset deletes and re-imports the 82 seeded messages, so Gmail assigns new IDs. The saved morning brief still linked the old IDs; the model copied them into its first Gmail call in query 2, got a 404, and had to search again ("invalid ids" in the thinking).

- Reset relinks today's saved brief and cron output to the new IDs, tracking every ID a message seat has ever had across resets (`relink_saved_briefs`).
- `daily_brief.py` rejects a brief whose mail links no longer exist in the workspace state, so the worst case is a fresh evidence pull, never dead links.
- Operational rule: always reset first, then start a new chat. A reset during an open chat invalidates the IDs already in that chat's context.

### 7. Launcher could not find Python without `HERMES_HOME`

Cron and CLI runs do not export `HERMES_HOME`, so the skill's launcher snippet and `run-actions.sh` fell back to the root Hermes install, which has no virtualenv. The model then spent ~100 s hunting for a Python (this is why the 07:00 cron brief took 174 s).

- `run-actions.sh` and the snippet in `SKILL.md` now locate the Hermes home that contains the skill (profile folders first), convert it to a Windows path under Git Bash, and export `HERMES_HOME` for the Python scripts.
- A one-line `run-actions.sh` shim under the ingest skill forwards to the real launcher, for the model's most common wrong guess (observed 11 s `find` otherwise).

### 8. Tracker update: one evidence call instead of five fetches

Query 3 used to do a Drive search for a sheet ID already in the brief, a sheet read, three thread reads, and a Gmail search before reasoning, then a read-back after writing.

- New `sheets tracker-evidence SPREADSHEET_ID_OR_TITLE --sheet TAB` (`skills/productivity/ingest/scripts/actions.py`): resolves the sheet by ID, URL, or title, reads the lanes, batches one bounded Gmail query per lane (owner or lane name, last 14 days), reads matching messages in a second batch, and returns bounded excerpts with links. ~3.3 s, ~18 KB.
- `sheets update-lanes` now returns the written rows (`rows`, `verified: true`) so the reference's verification step needs no second read.
- `references/updating-project-tracker.md`: start from that single packet; the exact command line is inlined so the model does not open the command reference first.

Model turns for query 3 went from 9 to 4. Evidence pre-grouped per lane also halved the reconciliation thinking (~1,000 → ~530 tokens).

### 9. Thinking length and run-to-run variance

Two sources of inconsistency (45 s one run, 90 s the next on identical input):

- Unbounded thinking. llama-server now runs with `--reasoning-budget 1024`; bursts that used to run 24–27 s are capped at ~18 s.
- Sampling temperature. Hermes sent none, so the model file's embedded default of 1.0 applied. At 1.0 the model more often ignored the written procedure (re-fetching the skill, running the Drive search it was told to skip) and thought longer. The profile now sends `temperature: 0.6` via `providers.local-qwen.extra_body`, which Hermes merges into every request to that endpoint. Verified at the server.

### 10. Gmail links that open the right mailbox

Not a latency fix, but it removed a demo blocker. `/mail/u/0/` opens whichever Google account the browser signed into first; `/mail/u/<address>/` returned "account temporarily unavailable"; `?authuser=<address>` dropped the thread fragment on redirect. `/mail/u/#all/<thread>` works and is used everywhere now. It relies on skcosdemo being the browser's default Google account.

## Current environment settings

llama-server launch (model folder `C:\llama.cpp-n1x-b9775`):

```powershell
.\llama-server.exe -m .\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf --mmproj .\mmproj-BF16.gguf --alias qwen3.6-35b-a3b --host 127.0.0.1 --port 8080 --ctx-size 65536 --spec-type draft-mtp --spec-draft-n-max 3 -np 1 --jinja --cache-reuse 256 --reasoning-budget 1024
```

Hermes refuses any `model.context_length` pin below 64,000, so the server context must be at least 65536.

Hermes profile `chief-of-staff` (`config.yaml`), the keys that matter:

```yaml
skills:
  auto_load:
    - chief-of-staff
model:
  provider: custom
  base_url: http://127.0.0.1:8080/v1
  default: qwen3.6-35b-a3b
  context_length: 65536
auxiliary:
  title_generation:
    enabled: false
    model_upgrade_enabled: false
  background_review:
    enabled: false
providers:
  local-qwen:
    base_url: http://127.0.0.1:8080/v1
    extra_body:
      temperature: 0.6
```

Hermes desktop app: Settings → Advanced → **Always open links in external browser** on, with Prisma Access Browser as the Windows default browser.

## Pre-demo checklist

1. llama-server running with the flags above (`curl http://127.0.0.1:8080/props` should show `n_ctx: 65536`).
2. Profile config intact. It was reverted to an older backup once on 2026-10-07 for unknown reasons:
   ```powershell
   & "$env:LOCALAPPDATA\hermes\hermes-agent\.hermes\bin\hermes.exe" --profile chief-of-staff config get skills.auto_load
   & "$env:LOCALAPPDATA\hermes\hermes-agent\.hermes\bin\hermes.exe" --profile chief-of-staff config get providers.local-qwen.extra_body.temperature
   ```
3. Hermes desktop app open before 07:00 on the demo day so the cron brief exists; otherwise query 1 takes the slow path (or trigger it: `hermes --profile chief-of-staff cron run e85eb52a0773`).
4. `python demo\reset_workspace.py` from the repo root (~40 s).
5. Start a **new chat** after the reset.

## Remaining levers, not applied

- `--reasoning-budget 768`: caps each thinking burst at ~13 s. Small quality risk now that evidence arrives pre-organised.
- `enable_thinking: false` via `chat_template_kwargs`: roughly 10 s per turn, but removes the model's judgment on the tracker reconciliation and meeting prep.
- A shorter saved brief: query 1 spends ~13 s just echoing the ~750-token brief.
