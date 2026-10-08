# Debugging notes

Problems found while setting up the Chief of Staff demo on an RTX Spark N1X
(Windows 11 on ARM64) with Hermes Agent and a local llama.cpp server. Each entry
gives the symptom, the root cause, and the fix applied. Dates are October 2026.

## 1. Model loops in its thinking and never answers

**Symptom.** The first morning-brief run completed in about a minute. A later run
with the same prompt showed the agent "thinking" for minutes, with the Desktop app
streaming reasoning that repeated itself. Hermes logged the turn as
`interrupted: waiting for model response (99.6s elapsed)`. Only the final call,
which writes the brief from the evidence packet, was affected; the two earlier
calls in the turn ran at normal speed.

**Root cause.** llama-server was launched with `--top-k 1`, which is greedy
decoding: the model always picks the single most probable next token. Qwen3.6 is a
thinking model and writes one to two thousand tokens of private reasoning before
answering. That reasoning is naturally repetitive, since it lists emails and
priorities one after another. Once a repeated phrase becomes the most probable
continuation, greedy decoding keeps choosing it, and each repetition makes the
next one more likely. There is no randomness to break the cycle, and the server
had no reasoning budget (`reasoning-budget: activated, budget=2147483647`), so
nothing cut it off. Whether a given run loops depends on the exact prompt, which
changes with the time of day and the evidence packet, so runs can alternate
between fine and stuck.

**Fix.** Remove `--top-k 1` from the llama-server launch command so the server uses
its default sampling. Default sampling picks among the top candidates weighted by
probability, so even when a loop starts the model escapes within a few tokens.
After the change, three consecutive runs finished their final call in under 30
seconds. The copy of the launcher at `C:\llama.cpp-n1x-b9775\start-llama-server.ps1`
has been updated to match.

**Tradeoff.** Output now varies slightly between runs. The facts come from the
evidence packet, not from sampling, so the brief's content is stable. If more
predictability is wanted, a low temperature such as `--temp 0.3` or a small
`--repeat-penalty 1.05` keeps most of greedy's consistency without getting stuck.
A server-side `--reasoning-budget 3000` is a further safety net.

**Related risk.** Hermes forks a background self-review after every turn. On this
machine it ran for about 70 seconds on a 28,000-token prompt. The server runs with
`-np 1`, a single slot, so a prompt typed during the review waits behind it. It can
be disabled in the profile under `auxiliary.background_review.enabled: false`.

## 2. llama-server exits immediately with a DLL error

**Symptom.** `llama-server.exe` exits with code `-1073741515` (0xC0000135,
`STATUS_DLL_NOT_FOUND`) and no log output. From Git Bash the message is
`error while loading shared libraries`.

**Root cause.** The build at `C:\llama.cpp-n1x-b9775` is CUDA-enabled.
`ggml-cuda.dll` depends on the CUDA 13.4 runtime (`cudart64_13.dll`,
`cublas64_13.dll`, `cublasLt64_13.dll`), which was not in the build folder, not on
`PATH`, and not installed as a toolkit. The DLLs were sitting in
`Downloads\dependencies\cuda-13.4\runtime-arm64`. Separately, the original launcher
expected the GGUF model files beside the executable, but they live in
`Downloads\inference\models`.

**Fix.** Copy the ARM64 CUDA runtime DLLs into the llama.cpp folder so Windows finds
them next to the executable. Use a launcher whose model and projector paths point
at `Downloads\inference\models`. All other flags follow
`Downloads\inference\server-settings-and-launcher\server-settings.json`, except
`--top-k 1` as described above.

## 3. Hermes Desktop installer fails with "could not stash local changes"

**Symptom.** The Desktop installer stops at the repository stage. The bootstrap log
shows `Unable to create '.../hermes-agent/.git/index.lock': File exists` followed by
`could not stash local changes ... commit or move them aside, then rerun`.

**Root cause.** The installer updates the Hermes source checkout at
`%LOCALAPPDATA%\hermes\hermes-agent` by stashing local changes and pulling. A stale
`.git\index.lock` from an earlier git process that did not finish made the stash
fail. The checkout also showed a dozen tracked files under `plugins/memory/mem0`
and its tests as deleted, which is what the stash was trying to save.

**Fix.** With no Hermes or git process running, delete the stale lock file and
restore the deleted tracked files:

```
del "%LOCALAPPDATA%\hermes\hermes-agent\.git\index.lock"
git -C "%LOCALAPPDATA%\hermes\hermes-agent" checkout -- .
```

Then rerun the installer. The profile, model settings, and seeded workspace are
not touched by the update. If the mem0 files are deleted again afterwards, suspect
endpoint security removing them.

## 4. Skill scripts cannot find the Hermes Python

**Symptom.** `setup.ps1 -Check` reports the system Python instead of the Hermes
one, or the skill scripts fall back to `python` on `PATH`, which on this machine
resolves to the Microsoft Store stub.

**Root cause.** The skills and launcher look for
`<profile>\hermes-agent\venv\Scripts\python.exe`. The repo's `install.py` creates
that as a junction to `<hermes root>\hermes-agent\venv`, but current Hermes builds
keep the runtime venv under
`%LOCALAPPDATA%\hermes\installs\<hash>\environments\<hash>\venv`, so the source of
the junction does not exist and nothing is created.

**Fix.** Create the junction by hand, pointing at the real runtime venv. `hermes
doctor` prints its path under "Runtime venv staged":

```powershell
New-Item -ItemType Junction `
  -Path "$env:LOCALAPPDATA\hermes\profiles\chief-of-staff\hermes-agent\venv" `
  -Target "<runtime venv path from hermes doctor>"
```

`hermes update` may move the runtime venv. If skills stop finding Python after an
update, recreate the junction.

## 5. PyMuPDF will not install on ARM64

**Symptom.** `pip install -r requirements.txt` and the setup helper's dependency
check fail building PyMuPDF with `Failed to find VS-2022`.

**Root cause.** PyMuPDF 1.28.0 has no `win_arm64` wheel, so pip tries to build it
from source and needs Visual Studio. The setup helper pins exact versions and
refuses to continue when any pin is not satisfied. 1.28.2 is the first release with
an ARM64 Windows wheel. Upgrading pip is also needed for it to select that wheel.

**Fix.** Pin PyMuPDF to 1.28.2 in `requirements.txt` and
`setup/google-workspace/setup.py`. Install it into the Hermes runtime venv with the
bundled uv, since that venv has no pip:

```
<hermes root>\tools\uv-<ver>\uv.exe pip install --link-mode copy --only-binary :all: --python <venv>\Scripts\python.exe PyMuPDF==1.28.2
```

## 6. Time zone errors in tests and scripts

**Symptom.** `ModuleNotFoundError: No module named 'tzdata'` or
`No time zone found with key UTC`.

**Root cause.** Python on Windows has no system time zone database. The `zoneinfo`
module needs the `tzdata` package, which is not in `requirements.txt`.

**Fix.** `pip install tzdata` into whichever Python runs the scripts. The Hermes
runtime venv already includes it.

## 7. setup.ps1 cannot be loaded

**Symptom.** `setup.ps1 cannot be loaded because running scripts is disabled on this
system`, and the launcher tests fail with the same message.

**Root cause.** The PowerShell execution policy was undefined at every scope, which
on Windows 11 means Restricted.

**Fix.** Allow locally created scripts for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## 8. Hermes installer blocked by the coding assistant

**Symptom.** Claude Code's auto-mode permission classifier refused to run the
official Hermes `install.ps1`, even from a downloaded and reviewed local copy.

**Root cause.** The classifier treats executing an installer fetched from the web
as external code and declines regardless of review.

**Fix.** Run the installer manually in PowerShell:

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

## 9. Latency tuning that was tried and reverted

A brief turn takes about a minute: roughly 17 s of model calls to open the skill
files, 14 s for the Google fetch, and 27 s or more for the final call, a third of it
hidden reasoning. On 2026-10-06 four changes were tried and measured at 30 to 37 s
per turn, then reverted at the user's request to keep the original behavior:
auto-loading the skills into the system prompt, disabling the post-turn background
review, a 5-minute cron prefetch of the evidence packet, and disabling thinking per
request via `chat_template_kwargs.enable_thinking: false` (the only thinking control
this llama-server build honors; `reasoning_effort` and a per-request budget are
ignored). The server-side alternative is `--reasoning-budget N` on the launch command.

## 10. Saved daily brief from a scheduled job

**Goal.** Make the first Start of Day request fast by generating the brief ahead of
time, following the pplx_demo branch's `DailyBriefs/YYYY-MM-DD.md` convention.

**How it works.** A Hermes cron job named `Morning daily brief` runs the Start of
Day prompt each weekday at 7:00 AM in the Hermes time zone. Hermes stores every run
as a report under `<profile>\cron\output\<job id>\<timestamp>.md` with a
`## Response` section. `daily_brief.py` looks for today's report from that job,
copies the response to `CoS_Workspace\DailyBriefs\<date>.md`, and prints it behind a
`{"saved_brief": ...}` line. The skill returns that Markdown unchanged. `--fresh`
bypasses the saved brief, which the scheduled prompt uses so the job always collects
live evidence. `demo/evidence_cache.py` preserves the newest dated brief on reset
(ported from pplx_demo).

**Measured.** Interactive turn with a saved brief present: about 41 s through the
CLI, versus 58 to 67 s live. The remaining time is the model opening the skill
(about 11 s) and re-emitting the 3,300-character brief (about 18 s). The reply was
byte-identical to the saved file.

**Gotchas.** The cron output is a report, not the bare reply, so the script extracts
the `## Response` section. The scheduler only ticks while Desktop or the gateway is
running, so on demo day confirm the dated file exists or trigger the job with
`hermes cron run`. The pplx_demo branch cannot be merged directly: it rewrites the
brief script for the Perplexity workspace variable and replaces the bash launchers.

## Quick reference

| Component | Location |
|---|---|
| Hermes profile | `%LOCALAPPDATA%\hermes\profiles\chief-of-staff` |
| Hermes logs | `<profile>\logs\agent.log`, `errors.log`, `gui.log` |
| Hermes sessions | `<profile>\state.db` (SQLite, tables `sessions`, `messages`) |
| Hermes install log | `%LOCALAPPDATA%\hermes\logs\bootstrap-installer.log` |
| Model server | `http://127.0.0.1:8080` (`/health`, `/v1/models`) |
| Model server launcher | `C:\llama.cpp-n1x-b9775\start-llama-server.ps1` |
| Model files | `C:\Users\Sayali\Downloads\inference\models` |
| Profile model config | `provider: custom`, `base_url: http://127.0.0.1:8080/v1`, `default: qwen3.6-35b-a3b`, `context_length: 65536` |

Useful checks:

```
hermes -p chief-of-staff doctor
hermes -p chief-of-staff -z "Reply with exactly one word: READY"
.\setup.ps1 -Harness hermes -Check
python setup/google-workspace/setup.py --check-live
python <profile>\skills\productivity\ingest\scripts\verify.py
```
