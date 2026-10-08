# Hermes Chief of Staff Agent

A portable Hermes Agent configuration for a lightweight Google Workspace chief of staff. It reads bounded Gmail, Calendar, Drive, Docs, Sheets, and Slides evidence; highlights meaningful daily outcomes; accounts for calendar constraints; prepares meeting work; drafts email; and proposes guarded tracker/document updates.

## Included

- `SOUL.md` routes natural-language chief-of-staff requests.
- `skills/productivity/chief-of-staff/` contains decision policy, packet builder, and tests.
- `skills/productivity/ingest/` contains bounded ingestion, focused actions, verification, and tests.
- `setup/google-workspace/` contains the portable OAuth helper.
- `config.example.yaml` documents the minimal recommended tool surface.
- [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) contains the presentation script and staged demo flow.
- [`DEBUGGING.md`](DEBUGGING.md) records setup problems found on the RTX Spark demo machine, with root causes and fixes.

No sessions, OAuth credentials, email/calendar fixtures, account IDs, document IDs, or model files are included.

For the shortest installation path, see [QUICKSTART.md](QUICKSTART.md). Every user must create OAuth credentials and connect their own Google account. The optional reference workspace seeder is documented in [demo/DEMO_SPEC.md](demo/DEMO_SPEC.md).

## Requirements

- Hermes Agent (tested on v0.20.1; use a recent release).
- Python 3.11+.
- A tool-calling model that meets Hermes context requirements.
- A Google Cloud Desktop OAuth client with Gmail, Calendar, Drive, Docs, Sheets, and Slides APIs enabled.
- Enable the [Google Tasks API](https://console.cloud.google.com/apis/library/tasks.googleapis.com) and grant the Tasks scope to include the optional sample checklist.

Install dependencies:

```bash
PYTHON="$(command -v python3 || command -v python)"
"$PYTHON" -m pip install -r requirements.txt
```

## Install into a Hermes profile

```bash
"$PYTHON" install.py
hermes -p chief-of-staff tools list --platform cli
```

The installer creates `profiles/chief-of-staff` under the normal Hermes root
(or the root selected by `HERMES_HOME`). On first creation it copies the default
profile's model/settings, `.env`, `SOUL.md`, installed skills, user memories,
local authentication, and demo workspace-state file. The default profile remains
unchanged; session history and caches are not copied. An existing shared Hermes
Python runtime is linked into the new profile, not duplicated.

Rerunning the installer refreshes the two demo skills but preserves the profile's
existing credentials, workspace state, model settings, and customized Soul. It
adds chief-of-staff routing if missing and enables only `chief-of-staff` and
`ingest`. Other installed skills stay installed but disabled. An explicit
`--hermes-home PATH` still installs directly into that exact target.
The installer also
disables `desktop_ui` and sets `HERMES_TUI_TOOLSETS=skills,terminal,cronjob` in the
profile's `.env` so Desktop auto-discovery cannot add preview tools back.
Restart Hermes Desktop after installation. Links remain available inline;
the agent uses the saved API connection instead of opening embedded web previews.
The `cronjob` tool manages Hermes's native scheduler; installation does not create,
enable, copy, or run scheduled jobs. Existing jobs in the target profile are preserved.

Select **chief-of-staff** in Hermes Desktop and start a new chat. Before running
OAuth or seed/reset scripts from a separate terminal, select the same profile:

```powershell
# Windows PowerShell
$env:HERMES_HOME = Join-Path $env:LOCALAPPDATA 'hermes\profiles\chief-of-staff'
```

```bash
# Windows Git Bash
export HERMES_HOME="$LOCALAPPDATA/hermes/profiles/chief-of-staff"
# Linux/macOS
# export HERMES_HOME="$HOME/.hermes/profiles/chief-of-staff"
```

Copied credentials still point at the same Google account and existing demo data.
Use the new profile for future resets; do not run two profiles against that shared
workspace at the same time. No Google data is reset or changed by installation.

## Connect Google Workspace

On Windows, run one of these commands from this checkout after installing the
chosen harness and demo skills/profile:

```powershell
.\setup.ps1 -Harness hermes
.\setup.ps1 -Harness perplexity
```

The launcher selects the harness's managed Python, with system Python as a
fallback only if the managed interpreter is absent. It reuses a working Google
connection or guides you through sign-in. First-time setup asks for your downloaded
Desktop OAuth client JSON. You can also pass `-ClientSecret 'C:\path\client.json'`.
It does not install the harness or demo skills, seed/reset Google data, or change
model settings.

Hermes uses its `chief-of-staff` profile by default. Perplexity uses
`CoS_Workspace\.chief-of-staff-state` beside the launcher. Override these with
`-Profile` / `-HermesRoot`, or `-WorkspaceRoot` / `-SkillsDir`, respectively.
Omit `-Harness` to choose interactively. Add `-Check` for a read-only local path
check, without contacting Google, installing dependencies, or signing in.
Environment settings are restored when the launcher exits.

The shared OAuth helper honors `COS_STATE_DIR` first and otherwise preserves
the existing Hermes profile lookup. The individual commands below remain
available for other shells and manual setup.

Never commit OAuth files. Create a Desktop OAuth client, then run:

```bash
"$PYTHON" setup/google-workspace/setup.py --install-deps
"$PYTHON" setup/google-workspace/setup.py --client-secret /path/to/client-secret.json
"$PYTHON" setup/google-workspace/setup.py --auth-url
```

Open the returned URL and approve access. The `http://localhost:1` redirect may
show a connection error; this is expected. Copy the full URL from the browser
address bar, then run:

```bash
"$PYTHON" setup/google-workspace/setup.py --auth-code "FULL_REDIRECT_URL"
"$PYTHON" setup/google-workspace/setup.py --check-live
"$PYTHON" skills/productivity/ingest/scripts/verify.py
```

The resulting google_token.json and google_client_secret.json live under HERMES_HOME and are ignored by git.

Normal demo commands refresh the saved token silently and do not open a sign-in
window. Reconnection is a setup step when access expires or is revoked. To add
Google Tasks to an existing connection, enable its API in the same OAuth project
and repeat `--auth-url` / `--auth-code` once to approve the additional Tasks scope.
The existing Workspace connection remains usable before this extra consent.

## Second Brain

The active demo notes live in `CoS_Workspace/CoS_SecondBrain/` inside the Desktop checkout. Open that folder as a
separate vault in Obsidian. The installer connects it by default when no vault is
already configured; existing connections and personal notes are preserved.

To explicitly switch an existing demo profile to the bundled vault, run from the repo:

```bash
python install.py --second-brain "CoS_Workspace/CoS_SecondBrain"
```

The folder path is saved in the profile's local `second-brain.json`, not in Git.
You can still use `--second-brain "/path/to/your/Second Brain"` to connect another
vault without copying or overwriting it. Reading context does not edit notes;
a separately configured scheduled job can update them when authorized.

Reset uses the current Monday–Friday week in the demo timezone (Pacific by default).
Pass `--week-of YYYY-MM-DD` to select another week's Monday.

`python demo/reset_workspace.py` (or `python demo/seed_workspace.py --reset --confirm`)
resets Google Workspace and restores `CoS_Workspace/CoS_SecondBrain/` from
`demo/templates/CoS_SecondBrain.zip`. Existing demo notes, including job-created
files, are first moved into the Git-ignored `demo/.second-brain-backups/` folder.
Local `.obsidian` settings are preserved. Reset deletes all other files and folders
inside `CoS_Workspace`, except `google_token.json`, `google_client_secret.json`,
`chief-of-staff-workspace-state.json`, and `second-brain.json` directly inside
`.chief-of-staff-state`. This removes old packets, snapshots, tracker updates,
drafts, and helper scripts. Other vaults outside `CoS_Workspace` are never reset, even if
connected to the profile. Finish running profile jobs before resetting and do not
start new jobs during a reset. No jobs are removed by reset.

The baseline excludes machine-specific Obsidian settings. Note edits appear as
Git changes; review them before committing, especially after ingesting real data.

The existing daily-brief call adds up to five relevant note excerpts in a separate
3,000-character allowance, without removing any of the existing bounded Google
evidence. Selection is a local word match, not an extra model call or vector index.
Excerpts show the matching passage. Each lookup scans at most 1,000 folders and
1,000 Markdown files (128 KiB per note), skipping hidden folders and notes.
Focused follow-ups can search or read a note when needed; already-returned context
is reused. Notes provide background, while current Google evidence controls
timing, status, approval scope, recipients, and writes. An unavailable vault is
reported separately and does not prevent the Google brief from running.

Note links use the [Obsidian URI](https://help.obsidian.md/Extending+Obsidian/Obsidian+URI)
format and open only when the user clicks them. Restart Hermes Desktop or start a
fresh profile chat after installation to load the updated skill.

## Use

Start a new Hermes Desktop chat in **chief-of-staff** (or run
`hermes -p chief-of-staff chat`) and say:

> Good morning chief of staff, what should we work on today?

Typical follow-ups:

- Help me prepare for the exec review.
- What slides should I prepare?
- Update the campaign tracker using the latest email evidence.
- Prepare follow-up drafts for the unresolved items.

The daily brief presents material context, distinct work outcomes, and tasks the
agent can take off your plate, with descriptive source links. Meeting preparation
covers context, work needed before the meeting, and the meeting's intended goals.
Use [Google Tasks](https://tasks.google.com/) to check off the seeded tasks. Chat
lists in this Hermes Desktop version do not save checkbox progress or sync it to
Google Tasks.

## Scheduled daily brief (optional)

A Hermes cron job in the **chief-of-staff** profile can generate the morning brief
before you open a chat, so the first Start of Day request returns a saved brief
instead of collecting evidence and generating live. This mirrors the saved-brief
convention of the Perplexity demo branch.

Create the job once from the profile:

```bash
hermes -p chief-of-staff cron create "0 7 * * 1-5" --name "Morning daily brief" --skill chief-of-staff --deliver local "Good morning chief of staff, what should we work on today? This is the scheduled morning run that produces today's saved brief. Run the Start of Day command with the extra argument --fresh so evidence is collected now, then reply with only the brief in the skill's three-section format, starting with the **What You Need to Know** heading. No preamble, no closing question."
```

The job name must stay `Morning daily brief`; `daily_brief.py` looks for that job's
output under the profile's `cron/output/` folder. On the first interactive Start of
Day of the day it copies the response to `CoS_Workspace/DailyBriefs/YYYY-MM-DD.md`
and prints it with a `saved_brief` marker, and the skill returns it unchanged. Pass
`--fresh` to force live collection. Delete the dated file to regenerate.

Hermes runs the schedule only while Hermes Desktop or the profile gateway is open.
To produce today's brief on demand, run `hermes -p chief-of-staff cron run <job id>`
and wait for the next scheduler tick. Workspace reset keeps the newest dated brief
and clears older ones. The `DailyBriefs/` folder is ignored by git.

## Scheduled project tracking (optional)

Scheduling is a separate, explicit opt-in after the interactive workflow works.
Use Hermes's native scheduler from the **chief-of-staff** profile; no Windows
scheduled task or separate scheduling service is needed. Keep Hermes Desktop's
backend (or the profile's Hermes gateway), the model server, and the machine
running for scheduled execution. Do not run a scheduled job alongside manual
testing or a workspace reset against the same account.

For CLI scheduling, enable `cronjob` with `hermes -p chief-of-staff tools` if it
is not already available. `config.example.yaml` includes the CLI configuration
and a `cron` worker toolset limited to `skills` and `terminal`; the installer pins
the Desktop toolsets but does not replace existing platform toolset settings.

Example job-creation prompt (choose your own schedule and verify the reported
time zone and next run before leaving it active):

> Create a scheduled task named "Campaign tracker follow-ups" in this Chief of Staff profile, running every weekday at 9:00 AM America/Los_Angeles. Use only the skills and terminal toolsets for the scheduled worker, and load the chief-of-staff skill. On each run, check the latest email evidence and update the RTX Spark campaign tracker where supported. Save follow-up drafts for items still missing updates, checking existing drafts first so the same unresolved request to the same recipient is not drafted again. Never send emails or make unrelated changes. Save a local report of what changed, what remains unresolved, and which drafts are ready for review. Show me the configured schedule and next run.

The name, tracker, time, and time zone are examples, not installer defaults.
Creating the job explicitly authorizes its recurring tracker edits and draft
creation, not sending mail. Ask Hermes to list existing jobs first; update or
reuse a matching job instead of creating another copy. Reports remain in the
job's run history/local output; do not assume delivery to the current chat.

Before leaving recurrence enabled, validate it when live testing is authorized:

1. Inspect the job's profile, schedule/time zone, workflow prompt, and worker toolsets.
2. Run the job once, then inspect its tracker changes, draft recipients/bodies,
   and local report. A manual trigger still writes to Workspace and uses the model.
3. Run it again without resetting data. Confirm that unchanged work creates no
   duplicate drafts. This is a prompted behavior to validate, not a guaranteed
   deduplication mechanism in the helper.
4. If a command is blocked by unattended execution approvals, inspect the failure;
   do not globally disable approvals or report that the work succeeded.
5. Pause the job after the demonstration and before resetting or manual testing.

Useful management prompts: "List my scheduled tasks", "Run Campaign tracker
follow-ups now", and "Pause Campaign tracker follow-ups". A paused job must be
resumed before a manual run. Check for an already-running execution before
triggering another or resetting the workspace.

## Safety behavior

- Broad ingestion is bounded and metadata/snippet-first.
- Gmail drafts are created but never sent by these scripts.
- A direct instruction to update a tracker is treated as approval for evidence-backed row changes; ambiguous requests and comparisons remain read-only.
- Other Docs, Sheets, Slides, and Calendar writes require approval and `--confirm`.
- Tracker updates preserve Lane/PIC, reject duplicate lanes, and validate statuses.
- One-time codes are redacted before model context.

## Tests

```bash
"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" -m unittest discover -s skills/productivity/ingest/tests -v
"$PYTHON" -m unittest discover -s skills/productivity/chief-of-staff/tests -v
```

Live smoke test after OAuth:

```bash
"$PYTHON" skills/productivity/ingest/scripts/ingest.py
"$PYTHON" skills/productivity/chief-of-staff/scripts/brief.py --max-chars 14000
```

## Portability and demo data

The agent does not require seeded workspace data for ordinary use. The included reference-workspace seeder recreates the Gmail, Calendar, Drive, Sheet, Doc, and Slides environment used to exercise the complete workflow. On another account, the agent reasons over the Workspace data that actually exists.

The tracker-specific path currently expects a tab named `Campaign Lanes` with columns A:J matching the demonstrated schema. General Gmail, Calendar, and Drive planning works without that sheet. Supporting arbitrary tracker schemas requires a small schema adapter rather than another hard-coded workbook.
