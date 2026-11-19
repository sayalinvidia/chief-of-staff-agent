# Chief of Staff demo on NVIDIA Nemotron 3.5 Bolt: setup guide for agents

This branch (`nemotron-bolt-3.5`) is the Chief of Staff demo as it runs on an NVIDIA RTX Spark
laptop with **Nemotron 3.5 Bolt 74B-A9B (NVIDIA 24GB build)** served by llama.cpp with the
LiLiCorr draft model, driven through **Hermes Desktop**. This guide is written for an agent
setting the demo up on another machine. Follow it top to bottom; every path and flag used on
the reference machine is given, and the expected result at each step is stated so you can tell
whether you have replicated it.

Measured on the reference machine (Hermes Desktop, three demo prompts, demo data reset first,
"hi" warm-up): **142 to 172 s total, 9 to 11 model turns, 6 to 9 tool calls, 0 failed
commands, tracker update correct**, with the skill text on this branch. Those two runs were on
battery; on mains the same machine generates about 80 tokens/s instead of 57 to 89, so expect
somewhat less. With the previous skill text the same model took 184 to 214 s.

Reference machine: ASUS ProArt P14, NVIDIA RTX Spark N1X (ARM64), 128 GB unified memory with a
96 GB GPU split, Windows 11 Pro, GPU driver 617.74. The commands below are for Windows; the
llama.cpp and model steps apply to any platform with the matching llama.cpp release.

---

## 0. What you will end up with

| Piece | Where (reference machine) | Purpose |
|---|---|---|
| llama.cpp b12445 | `C:\Users\NVIDIA\llama.cpp\bin` | model server on `127.0.0.1:8080`, one slot |
| Bolt model + draft model | `C:\Users\NVIDIA\llama.cpp\models` | 22.0 GB + 1.0 GB GGUF files |
| `Start-Bolt.ps1`, `Switch-Model.ps1`, `Start-Qwen.ps1` | `C:\Users\NVIDIA\llama.cpp` | start/switch the server (copies in `demo\nemotron-bolt\`) |
| Hermes Desktop (NVIDIA local-offer channel build) | `%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer` | the agent app; CLI is `hermes-nvidia-local-offer.exe` |
| Hermes profile `chief-of-staff` | `...\profiles\chief-of-staff` | skills, SOUL.md, config.yaml, Google token, state |
| This repo | `C:\Users\NVIDIA\chief-of-staff-agent` | skills, demo seed/reset scripts, `CoS_Workspace` |
| Isolated Python 3.14 | `C:\Users\NVIDIA\chief-of-staff-runtime\python` | runs the skill scripts; linked into the profile |
| Reset helpers | `C:\Users\NVIDIA\chief-of-staff-runtime` | `Reset-Demo.cmd`, `Reset-Demo-KeepEmails.cmd`, `Next-Run.cmd` (copies in `demo\nemotron-bolt\`) |

Keep the same layout if you can; if not, step 4 rewrites every path for you.

---

## 1. Hermes Desktop and this repository

1. Install **Hermes Desktop, NVIDIA local-offer channel build** (Windows package
   `NousResearch.HermesChannel…`, version 0.0.5.0 on the reference machine). Its data folder is
   `%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer` and its command-line entry point is
   `hermes-nvidia-local-offer.exe`. The Desktop app only shows profiles that live under that
   folder, so **always set `HERMES_HOME` to it (or to the profile inside it) before any CLI
   call**. The plain `hermes` command and `%LOCALAPPDATA%\hermes` belong to a different
   installation and are ignored by the app.
2. Clone this repo and check out this branch:
   ```powershell
   git clone https://github.com/sayalinvidia/chief-of-staff-agent.git C:\Users\<you>\chief-of-staff-agent
   cd C:\Users\<you>\chief-of-staff-agent
   git checkout nemotron-bolt-3.5
   ```
3. Follow `QUICKSTART.md` steps 2 to 4 with one change: use the channel-build home, not
   `%LOCALAPPDATA%\hermes`:
   ```powershell
   $env:HERMES_HOME = Join-Path $env:LOCALAPPDATA 'hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff'
   python install.py --hermes-home $env:HERMES_HOME
   ```
   This creates the `chief-of-staff` profile with the skills, `SOUL.md` and a config. Then
   connect the demo Google account and seed the workspace as QUICKSTART describes
   (`demo\seed_workspace.py`). Verify: `hermes-nvidia-local-offer.exe -p chief-of-staff tools list --platform cli`
   lists `skills`, `terminal`, `cronjob`.

**Do step 4 (paths) before running any skill command**, because the skill text on this branch
names the reference machine's paths.

---

## 2. Python for the skill scripts

The skill scripts (`daily_brief.py`, `actions.py`, …) need a Python with the packages in
`requirements.txt`. Two problems on the reference machine, and how they were solved:

- The machine had no system Python (`python` on PATH was the Microsoft Store stub) and no
  compiler, so packages had to be installed with `--only-binary=:all:`.
- Hermes Desktop exports its own `PYTHONPATH` into terminal and cron child processes. Any
  normal venv then imports Hermes's bundled `cryptography` DLL and fails with "Access is
  denied". The fix is an **isolated** Python that ignores `PYTHONPATH`.

Reproduce it like this (any CPython 3.14 for your platform works as the source; the reference
machine copied the Python runtime bundled inside the Hermes package):

1. Copy a CPython 3.14 installation (python.exe, python3*.dll, `DLLs\`, `Lib\`) to
   `C:\Users\<you>\chief-of-staff-runtime\python`.
2. Put `demo\nemotron-bolt\python314._pth` next to `python.exe`. Its four lines (`DLLs`,
   `Lib`, `Lib\site-packages`, `import site`) make the interpreter ignore `PYTHONPATH` and
   `PYTHONHOME`.
3. Install the packages: `python.exe -m pip install --only-binary=:all: -r requirements.txt`
   (the reference machine has `google-api-python-client 2.194.0`, `google-auth 2.55.1`,
   `google-auth-oauthlib 1.3.1`, `httplib2 0.32.0`, `cryptography 46.0.3`, `PyMuPDF 1.28.2`).
4. Link it into the profile where the skill expects it. The skill runs
   `<profile>\hermes-agent\venv\Scripts\python.exe`; on the reference machine
   `<profile>\hermes-agent\venv\Scripts` is a **directory junction** to the runtime folder:
   ```powershell
   New-Item -ItemType Directory -Force "$env:HERMES_HOME\hermes-agent\venv" | Out-Null
   New-Item -ItemType Junction -Path "$env:HERMES_HOME\hermes-agent\venv\Scripts" -Target 'C:\Users\<you>\chief-of-staff-runtime\python'
   ```
5. Verify: `& "$env:HERMES_HOME\hermes-agent\venv\Scripts\python.exe" -c "import googleapiclient, cryptography; print('ok')"`
   must print `ok` **when run from a Hermes terminal tool call as well**, not only from your shell.

---

## 3. llama.cpp, the Bolt model and the draft model

### 3a. llama.cpp
Download two zips from `https://github.com/ggml-org/llama.cpp/releases/tag/b12445` and unzip
both into `C:\Users\<you>\llama.cpp\bin`:
- `llama-b12445-bin-win-cuda-13.5-arm64.zip` (use the x64 CUDA zip on an x64 machine)
- `cudart-llama-bin-win-cuda-13.5-arm64.zip` (CUDA runtime DLLs; same architecture)

Verify: `bin\llama-server.exe --version` prints `b12445`. Other builds will probably work but
were not measured; the Bolt GGUF needs a build that knows the Nemotron-H hybrid architecture.

### 3b. Model files (Hugging Face, no sign-in needed, OpenMDW-1.1 licence)
Into `C:\Users\<you>\llama.cpp\models`:

```powershell
curl.exe -L -o NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf `
  https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-GGUF/resolve/main/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf
curl.exe -L -o NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr.gguf `
  https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr-GGUF/resolve/main/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr.gguf
```

Expected sizes and SHA-256 (also in `demo\nemotron-bolt\model-sha256.txt`):

| File | Bytes | SHA-256 |
|---|---|---|
| `NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf` | 22,018,326,528 | `91d63363e782c8a3d5f4be42816eba8e0d42dd2530bd07a7d0d2dc440599af75` |
| `NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr.gguf` | 998,242,560 | `080e1ea41c9562a7804dbf30c6fbd4d17e216c6b8ff666f88e6edb1816010194` |

What they are: the main file is NVIDIA's "24GB" build of Bolt (74B total, 9B active parameters;
experts quantised to 2 bits with quantisation-aware distillation, Mamba layers NVFP4, embeddings
Q8_0). The LiLiCorr file is the speculative-decoding draft model trained on Bolt's own output; it
proposes up to 7 tokens per step that Bolt verifies in one pass. It roughly doubles generation
speed at the ~50% acceptance rate seen in the demo. Both are needed for the measured numbers.

Optional, for comparison runs: Qwen 3.6 35B-A3B Q4_K_M (`Start-Qwen.ps1`), 20.5 GB.

### 3c. Start script
Copy `demo\nemotron-bolt\Start-Bolt.ps1`, `Switch-Model.ps1` and `Start-Qwen.ps1` to
`C:\Users\<you>\llama.cpp\`. They locate `bin\` and `models\` relative to their own folder.
`Start-Bolt.ps1` runs:

```
llama-server.exe -m models\NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf --alias nemotron-3.5-bolt
  --host 127.0.0.1 --port 8080 --ctx-size 65536 -np 1 -ngl 99 --jinja
  --cache-reuse 256 --reasoning-budget 768
  --spec-type draft-lilicorr --spec-draft-model models\NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr.gguf
  --spec-draft-ngl 99 --spec-draft-n-max 7
```

| Flag | Why |
|---|---|
| `--ctx-size 65536` | Hermes refuses a `context_length` below 64,000; the demo's prompts reach ~14k tokens |
| `-np 1` | one slot; Hermes Desktop and cron share it, so never run two chats at once |
| `-ngl 99` / `--spec-draft-ngl 99` | all layers of both models on the GPU (25 GB total in use) |
| `--jinja` | use the model's own chat template, needed for tool calls |
| `--cache-reuse 256` | reuse the prompt cache across turns; the 13k-token system prompt is read once |
| `--reasoning-budget 768` | caps thinking per turn; inherited from the repo's Qwen tuning, not re-tuned for Bolt |
| `--spec-type draft-lilicorr … --spec-draft-n-max 7` | LiLiCorr speculative decoding, 7 draft tokens, as in NVIDIA's recipes |

Start it: `powershell -ExecutionPolicy Bypass -File C:\Users\<you>\llama.cpp\Start-Bolt.ps1`
(or `Switch-Model.ps1 bolt`, which also stops any running server and sets the profile's model
name). Expected: ready in 12 to 16 s; `curl http://127.0.0.1:8080/v1/models` shows
`nemotron-3.5-bolt`; `curl http://127.0.0.1:8080/props` shows `n_ctx: 65536`; `nvidia-smi`
shows about 25.5 GB in use. Server output is tee'd to `bolt-server-last.log`.

Quick speed check (expect about 80 tokens/s on mains; the `timings` object is in every response):
```powershell
$r = Invoke-RestMethod http://127.0.0.1:8080/v1/chat/completions -Method Post -ContentType 'application/json' -Body '{"messages":[{"role":"user","content":"hi"}]}'
$r.timings | Format-List
```

---

## 4. Paths: make the branch match your machine

The skill text (`skills\productivity\chief-of-staff\SKILL.md` and two references), the profile
config, `shell-init.sh`, the reset `.cmd` files and the eval scripts contain the reference
machine's literal paths. This was deliberate: a fixed path removed Bolt's habit of searching
for its scripts (5 to 9 extra model turns per run). Rewrite them once:

```powershell
python demo\nemotron-bolt\configure_paths.py --check   # shows every replacement
python demo\nemotron-bolt\configure_paths.py           # applies them
```

Defaults assume `%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer`, profile
`chief-of-staff`, the runtime folder next to the repo, and `%USERPROFILE%\llama.cpp`; pass
`--hermes-root`, `--profile`, `--runtime`, `--llama` otherwise. Then install the rewritten skill
into the profile (`python install.py --hermes-home $env:HERMES_HOME` again; it refreshes the
skills and keeps credentials) or copy `skills\productivity\chief-of-staff` over
`<profile>\skills\productivity\chief-of-staff` by hand. **The profile holds a copy of the skill,
not a link**, so every later skill edit must be copied too.

Verify: `Select-String SKILL_ROOT, 'Users\\NVIDIA' skills\productivity\chief-of-staff -Recurse`
returns nothing, and the paths in `SKILL.md`'s "How to run the scripts" block exist.

---

## 5. Hermes profile configuration

Replace `<profile>\config.yaml` with `demo\nemotron-bolt\config.chief-of-staff.yaml` (after
step 4 rewrote its path) or set these keys by hand. The ones that matter:

```yaml
model:
  default: nemotron-3.5-bolt          # must equal the server's --alias; Desktop's model picker is only a label
  provider: custom
  base_url: http://127.0.0.1:8080/v1
  context_length: 65536
providers:
  local-qwen:
    base_url: http://127.0.0.1:8080/v1
    extra_body:
      temperature: 0.6                # confirmed applied from the server's request log (with top-p 0.95, top-k 20, min-p 0.05)
terminal:
  shell_init_files:
    - <profile>\shell-init.sh         # exports HERMES_HOME, puts the isolated Python first on PATH, unsets PYTHONPATH/PYTHONHOME
platform_toolsets:
  cli:  [skills, terminal, cronjob]
  cron: [skills, terminal]
agent:
  disabled_toolsets: [desktop_ui]
  max_turns: 40
memory:   { memory_enabled: false, user_profile_enabled: false, memory_char_limit: 0, user_char_limit: 0, nudge_interval: 0 }
auxiliary: { title_generation: { enabled: false, model_upgrade_enabled: false }, background_review: { enabled: false } }
curator:  { enabled: false }
skills:
  auto_load: [chief-of-staff]
  disabled: [ … every other bundled skill … ]   # keeps the system prompt at ~13k tokens
```

Copy `demo\nemotron-bolt\shell-init.sh` to `<profile>\shell-init.sh` (step 4 rewrote its
paths). It is what lets the skill's commands find the isolated Python from inside Hermes.

Restart Hermes Desktop after changing the config. Verify in a new chat: "hi" answers in a few
seconds, and the first model request in `bolt-server-last.log` shows roughly 11,000 to 14,000
prompt tokens (the system prompt plus the auto-loaded skill).

---

## 6. Scheduled morning brief (what the demo expects on the day)

The first demo prompt returns a **saved** brief when a scheduled job has produced one that day,
otherwise it collects evidence live (the measured runs above were live). Create the job once in
the profile (`README.md`, "Scheduled daily brief"); the reference machine's job is named
`Daily Work Brief`, schedule `0 6 * * *`, delivery `local`, prompt: "Tell me what I should work
on today. Save the daily brief as DailyBriefs/YYYY-MM-DD.md in this workspace, using today's
date. Include the complete brief with its source links, and show it in the chat." Trigger it on
demand with `hermes-nvidia-local-offer.exe -p chief-of-staff cron run <job id>` while Desktop is
open. Note `daily_brief.py` looks for the job named in `README.md`; check which name the branch's
script expects before relying on the saved-brief path.

---

## 7. Reset between runs

Copy `demo\nemotron-bolt\Reset-Demo.cmd`, `Reset-Demo-KeepEmails.cmd`, `Next-Run.cmd`,
`reset_keep_emails.py` and `snapshot_tracker.py` into `C:\Users\<you>\chief-of-staff-runtime\`
(step 4 rewrote their paths).

- `Reset-Demo.cmd`: full reset of the demo Google data (re-imports the seeded emails), ~40 s.
  Needed once per calendar day.
- `Reset-Demo-KeepEmails.cmd`: everything except the emails, ~25 s. Use between runs on the same day.
- `Next-Run.cmd`: snapshots the live tracker to `eval\desktop-runs\tracker-<time>.json` (so the
  previous run can be scored), then does the keep-emails reset, falling back to the full reset.

Always start a **new chat** after a reset.

---

## 8. Run the demo and check you have replicated it

Conditions that matter: **mains power** (on battery the GPU is throttled: Bolt drops to roughly
35 tokens/s in the worst case), one model server only, no other Hermes chat or cron run in
progress, Desktop not the CLI (through the CLI `-z` path Bolt rambled and took 565 s; the cause
is unknown).

1. `Next-Run.cmd` (or a reset), then a new chat in Hermes Desktop.
2. Type `hi` and wait for the answer (loads the system prompt into the cache).
3. The three prompts, in order, each after the previous answer finishes:
   - `hey chief of staff, tell me what should I work on today`
   - `Help me prepare for the exec review`
   - `Hey chief of staff, update the status of the NeoAgent V2 tracker`

Expected with this branch's skill (reference machine, battery): about 30–36 s, 30–58 s and
76–83 s; 9 to 11 model turns and 6 to 9 tool calls in total; no failed commands; replies that
start at a Markdown heading (Bolt still sometimes adds one lead-in sentence on prompts 2 and 3).
The tracker must end with Performance results = Complete, Exec Review deck = In progress,
Agent Messaging = In progress, Legal intake LGL-2026-0847 = Complete, and Marketing shoot,
Partner enablement, Social rollout, Retail demo readiness unchanged.

Score a run from Hermes's own records instead of a stopwatch:
```powershell
python demo\nemotron-bolt\eval\desktop_sessions.py "2026-11-18 18:50"   # sessions since that time: per-prompt seconds, turns, tool calls, reply openings
python demo\nemotron-bolt\snapshot_tracker.py                            # prints the live tracker (needs HERMES_HOME = the profile)
```
`desktop_sessions.py` reads `<profile>\state.db`; `<profile>\logs\agent.log` also keeps per-turn
`duration=` lines and `Tool terminal returned error` lines, even for chats deleted in Desktop;
`llama.cpp\bolt-server-last.log` has tokens, tokens/s and draft acceptance per request.

---

## 9. Known behaviour and open items

- Bolt's thinking text is 2 to 3× longer than Qwen's for the same work; `--reasoning-budget 768`
  caps it per turn. Not re-tuned.
- Temperature 0.6 is what the demo was measured at; NVIDIA recommends 1.0 for Nemotron. Not tried.
- The draft model's acceptance rate was ~50% in demo runs. Without `--spec-*` the server runs Bolt
  alone (not measured).
- Hermes Desktop's model picker only changes a label; what answers is whatever the server loaded.
  Check `/v1/models` before attributing a run to a model.
- Bolt through the Hermes CLI (`-z`) is not representative (see above); measure in Desktop.
- The "start at the heading" rule removed the lead-in sentence on the brief but Bolt still adds
  one on the other two replies.

Document: `docs\nemotron-bolt\Nemotron-Bolt-Deployment-Guide.pdf` (the reference machine's
setup and all measured numbers).

What this guide has **not** verified: the whole procedure has only been run on the reference
machine, by hand, over two days; `configure_paths.py` has been dry-run but not used to set up a
second machine; the Hermes Desktop channel build's download location is not recorded here; the
isolated Python was copied from the Hermes package rather than a fresh CPython download.
