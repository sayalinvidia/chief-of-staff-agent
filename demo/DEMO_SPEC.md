# Workspace seed specification

The seeder creates a self-contained realistic Chief of Staff workspace in the Google account connected through OAuth. It contains no account IDs, credentials, or links from the reference workspace.

## What it creates

- **8 imported Gmail messages** marked Inbox, Unread, and Important:
  - Exec Review moved to 5 PM
  - Approved performance metrics
  - Slide 6/7/10 review feedback
  - Leadership-review legal clearance
  - Marketing shoot venue deadline
  - Agent Security PRD deadline
  - SuperBox UI issues delay readiness; Engineering recommends holding SuperBox shoots and demos
  - Autonomous Robot Demo complete, engineering walkthrough passed, and ready for marketing shoots
- **70 low-priority background messages** and **1 contact message** so the inbox is realistic without hiding the important work. Synthetic senders use the visibly fake local-part pattern `name.example@nvidia.com`.
- **3 task-supporting emails** from Leah Moreno, Tessa Ellis and Evan Mercer, dated the seed/reset morning. They support a financial-analysis project ramp-up email, a GTC 2027 presenter reply awaiting the user's decision, and a meeting-notes prototype ETA update. The new fictional contacts use `example.com` addresses. These replace the old FAQ, pilot-lessons and workshop-budget requests. The 79 core/background/contact emails keep their repeatable, irregular timestamps, which run backward from 9:12 AM today into the previous afternoon/evening, in the configured workspace time zone. Resetting advances the dates but preserves clock times and ordering, even when run before 9:12 AM. The eight important messages remain dated today.
- **89–90 Calendar events** across the workweek. Each day has a distinct, busy schedule with overlaps; the current workday also contains the 5 PM Exec Review.
- **3 unfinished Google Tasks in the default list (My Tasks)**, all due on the seed/reset date: draft Leah Moreno’s ramp-up email for the AI for Financial Analysis assistant, respond to the GTC 2027 presenter invitation, and update the Local AI Meeting Notes Assistant’s prototype ETA. Notes link to the source email and relevant files. They replace all six former demo tasks. Personal tasks are preserved.
- **3 additional Google Docs and a four-slide deck**: AI for Financial Analysis Assistant — Project Overview, Progress and Findings, and Next Steps, plus Local AI Meeting Notes Assistant — Project Overview. The latter retains the unique `<ETA goes here>` placeholder. Evan's email supplies an internal-testing date seven days after seeding. Tessa's email references the conversation seven days before seeding without deciding the user's availability. Resources are imported from editable Office templates and restored at the same Drive IDs on reset.
- **1 Google Sheet**: `RTX Spark Campaign Tracker`
  - Tab: `Campaign Lanes`
  - Columns A:J: Lane, PIC, Status, Latest update, Next action, Due, Dependency/blocker, Evidence, Artifact, Notes
  - Status dropdown: On track, In progress, Awaiting update, Blocked, Complete
- **1 Google Doc**: `RTX Spark Campaign Plan`
- **1 Google Slides deck**: `RTX Spark Exec Review`
  - 10 slides
  - Slide 4 intentionally waits for Mike’s performance figures
  - Slide 6 intentionally needs to move out of the live flow
  - Slide 10 contains the two leadership decisions

Generated IDs are stored only in the local file:

```text
$HERMES_HOME/chief-of-staff-workspace-state.json
```

The reset and cleanup commands use this file to delete imported mail/events and move generated Drive files to trash.

Google Tasks uses the account's default list, resolved through the API and saved in
the same state file. Reset replaces
only its seeded tasks, including completed ones, with fresh links to the new emails;
unrelated tasks are preserved. Cleanup also removes only seeded tasks and keeps the
list itself. Older states that refer to a separate demo list are cleaned there on
reset, then newly seeded tasks are placed in the default list. With an existing
connection that lacks Tasks permission, the first Tasks seed is skipped with setup
instructions; Gmail, Calendar, and Drive resets still work. Once a demo task list
exists, Tasks access is checked before any reset starts.


## Template fidelity

The Sheet, Doc, and Slides are imported from Office templates stored under `demo/templates/`. The executive deck uses a charcoal-and-green design with editable title/body fields and the same ten-slide scenario. Importing the templates preserves the tracker styling, conditional formatting, document structure, and slide design instead of rebuilding approximations through API calls. The imported files receive fresh Google IDs and are linked dynamically from seeded mail and calendar entries.

If slides were removed or added during the demo, or the local deck template has changed, reset re-imports the deck template into the same Google Slides file before restoring baseline text. The file ID and deck links stay unchanged; slide IDs may change, so start a fresh demo chat after reset. The workspace state records the template's SHA-256 fingerprint. Older states without that fingerprint receive a one-time refresh. With an unchanged template and the original slide count, reset keeps its existing text-only path. This restores the template deck, not custom structural edits.

## Seed

First connect your own Google account as described in `QUICKSTART.md`. Then:

```bash
python demo/seed_workspace.py --confirm
```

To target a particular Monday:

```bash
python demo/seed_workspace.py --week-of 2026-08-17 --confirm
```

## Reset and cleanup

```bash
python demo/reset_workspace.py

# Keep the seeded Gmail messages (skips the mail delete + re-import; drafts are still cleared):
python demo/reset_workspace.py --keep-emails
demo\reset_workspace.cmd --keep-emails      # Windows batch wrapper, same flags

# Permanently remove the seeded workspace instead:
python demo/seed_workspace.py --cleanup --confirm
```

`--keep-emails` is for runs where none of the demo workflows touched the inbox: it
leaves the seeded messages (and their Gmail IDs, so saved briefs still link) in place
and reuses them as the evidence links for the recreated tasks and tracker rows. Mail
timestamps are not refreshed, so run a full reset at least once per demo day.

Reset also restores `CoS_Workspace/CoS_SecondBrain/` from the bundled baseline ZIP,
saving the previous demo vault under `demo/.second-brain-backups/`. It deletes all
other workspace contents except the four required `.chief-of-staff-state` files
listed in the README. Vaults outside `CoS_Workspace` and cron jobs are untouched.
`--cleanup` removes Google Workspace seed data only.

## Manual fallback

If OAuth scopes or organization policy prevent the script from creating a resource, create the components manually:

1. **Sheet** — Create `RTX Spark Campaign Tracker`, tab `Campaign Lanes`, with the A:J columns listed above. Add at least these lanes: Product performance claims (Awaiting update), Exec Review deck (Awaiting update), Agent Messaging (Awaiting update), Marketing shoot (Blocked), Partner enablement (On track), Social rollout (Awaiting update), Retail demo readiness (Blocked), Legal intake (Awaiting update).
2. **Slides** — Create a 10-slide `RTX Spark Exec Review`. Put `Performance to go here - Mike Chen to provide` on slide 4, a proposed retail customer-use example on slide 6 (local laptop comparison, an associate-reviewed follow-up draft, and customer details staying on the device), a pending Customer Example section on slide 7, and two decision asks on slide 10. Aisha's feedback asks to summarize that example in slide 7 before removing slide 6. The example is not customer validation or approval of the demo slate or owners.
3. **Doc** — Create `RTX Spark Campaign Plan` with an agent-first narrative and open work for claims, retail demo ownership, shoot date, and Exec Review preparation.
4. **Calendar** — Add a varied schedule across the workweek rather than repeating the same meetings every day. On the current workday, include the RTX Spark Exec Review at 5 PM and an overlapping decision-triage event.
5. **Gmail** — Send or import messages to yourself containing the six topics above. Mark them unread/important. Include the generated Sheet/Slides/Doc links where relevant. Use clearly synthetic addresses such as `elena.example@nvidia.com`.

The exact names are helpful for artifact matching, but the Chief of Staff logic still reasons from the actual evidence rather than fixture IDs.

## Troubleshooting

- `403 insufficientPermissions`: reauthorize with all scopes in `setup/google-workspace/setup.py`.
- API not enabled: enable Gmail, Calendar, Drive, Docs, Sheets, and Slides APIs in the OAuth project.
- Workspace admin restriction: ask the administrator to allow the OAuth client/scopes.
- Existing state file: run cleanup first, or inspect/remove the local state only after manually cleaning created resources.
- Gmail import blocked by policy: send the six messages to the connected account manually; the rest of the seed can still be created.

## Refresh only the task scenario

With `HERMES_HOME` pointing to the active demo profile, run:

```text
python demo/seed_workspace.py --refresh-task-scenario --confirm
```

This creates missing task resources, replaces only the marked task-supporting emails, and replaces seeded tasks. It preserves the RTX documents/deck/tracker, calendar events, drafts and personal tasks. It checkpoints new file/message IDs in the state file. A full reset also restores the task resource templates, including the ETA placeholder. The three task notes keep essential context within the brief packet’s 240-character note limit; resource URLs follow it.

The DOCX source is `build_task_documents.py` (python-docx). The four-slide deck source is `build_task_deck.mjs` (the bundled artifact runtime). Runtime paths are supplied to the builders rather than stored in generated project documents. The seed process imports the checked-in templates and does not need the authoring runtimes.

## Product news scenarios

SuperBox and Autonomous Robot Demo are fictional projects. Morgan Reeves reports a recommended SuperBox hold, with no confirmed readiness date; this does not affect the NeoAgent shoot. Samira Noor confirms that the Autonomous Robot Demo is complete and ready for marketing shoots after its final engineering walkthrough. The robotics team has setup and reset instructions ready, but shoot dates have not been booked. Neither message requests a new user task. Both arrive on the seed morning under the existing timestamp policy. The two messages bring the total seeded email count to 82. Second Brain project and contact notes preserve their scope and ownership. The Financial Analysis project and its resources are unchanged.

## Workspace mirror (Obsidian graph)

`skills/productivity/chief-of-staff/scripts/workspace_mirror.py` writes a machine-owned
`workspace/` folder into the Second Brain vault: a `Google Workspace` hub note, one note per
source (`Gmail`, `Calendar`, `Drive`, `Sheets`, `Tasks`), and one note per message, event, file,
tracker lane, and task. Item notes link back to their source and, when a name matches, to the
vault's existing people, meeting, and project pages, so Obsidian's graph view shows the live
workspace attached to the knowledge base. The folder is deleted and rewritten on every run.

It runs on a Hermes cron job (`Workspace mirror`, no agent, every 30 minutes on weekdays) and at
the end of every reset, so Gmail links always match the current seed. In Obsidian, filter the
graph with `path:workspace` or `tag:#workspace-mirror` to isolate it.

The notes are for people watching the demo. The agent reads the mirror's persisted snapshot
(`<HERMES_HOME>/chief-of-staff/workspace-mirror.json`) through `sheets tracker-evidence`, so the
tracker update (query 3) gathers its evidence from local data when the snapshot is under three
hours old and falls back to live Gmail and Sheets otherwise. Writes always go to Google. A second
no-agent cron job, `Second Brain daily refresh` (06:45 weekdays), guarantees a fresh snapshot
before the morning brief and the demo.
