# Updating Project Tracker

A tracker update request authorizes evidence-backed changes to the requested tracker and work items.

## 1. Gather evidence

Use [Command reference](command-reference.md) for `actions.py` commands and arguments.

1. **Read the tracker and its evidence in one call.** Run `sheets tracker-evidence` once with the spreadsheet ID, URL, or title (it resolves titles itself; do not run `drive search` or `sheets get` first) and `--sheet` for the tab. It returns every lane plus the recent mail from each lane’s owner or naming the lane, with bounded excerpts and links. Identify each requested entry’s deliverable, status, and blocker, plus the tracker’s status definitions. Do not search local notes for the tracker.
2. **Assess from that packet plus context.** Combine the returned messages with evidence already in context (for example the daily brief). Treat this as the evidence set: do not re-read threads the packet already excerpts, and do not run further searches for lanes whose messages settle the question.
3. **Fill only genuine gaps.** Only when a specific lane’s status cannot be judged from the packet and context, run one bounded Gmail search or thread read for that lane, then stop. A lane with no returned messages has received no recent mail from its owner or naming the lane; that alone does not change its status. Consult Second Brain only for remaining necessary gaps.

## 2. Reconcile entries

1. **Establish scope.** Identify the lane's deliverable and required dependencies. Exclude other lanes' work and downstream uses of its output. Do not add unstated requirements or hypothetical steps.
2. **Check completion first.** If current evidence confirms the deliverable is finished, use **Complete**. Do not add downstream work to keep it open. An outdated tracker entry does not mean the deliverable is unfinished.
3. **Check whether a change is supported.** If evidence establishes no change to the lane's progress, inputs, or blockers, preserve its status. Contact introductions alone do not establish progress. Tracker timestamps do not establish status accuracy.
4. **Classify unfinished work.**
   - **Awaiting update:** Required input is still missing.
   - **In progress:** Required input has arrived; the lane's drafting or edits remain.
   - **Blocked:** Evidence explicitly identifies a dependency preventing the lane's work from proceeding.
   - **On track:** Work remains and is progressing without a blocker.

   Missing input alone does not change **Awaiting update** to **Blocked**; evidence must establish an impediment to progress. Pending approvals block only work that requires them.
5. **Check consistency before writing.** The status, next action, and blocker must describe the same lane. A completed deliverable cannot remain **On track** or **In progress**. Apply shared evidence to every requested lane. Received inputs cannot remain missing.

- Preserve accurate values. Clear values only when evidence shows they no longer apply, never because information is missing.

## 3. Apply and verify

If no changes are supported, report that without modifying the tracker.

- Include each changed lane once in a JSON array, with its exact `lane` name and evidence-backed `status`, even for details-only updates or retries. Valid statuses: `On track`, `In progress`, `Awaiting update`, `Blocked`, `Complete`.
- Use `--include-details` for supported `latest`, `next`, `due`, `blocker`, and `evidence` changes. When explicitly asked for status-only changes, use `--status-only` with only `lane` and `status`.
- When changing status with `--include-details`, include any existing `blocker`: preserve or revise its text, or use `""` only when evidence confirms resolution.
- Omit unchanged or unsupported optional fields. Preserve formulas, source metric names, units, and approval scope.
- Batch changes in one `sheets update-lanes` call with the verified spreadsheet ID, actual tab name via `--sheet`, and `--confirm`. Use `--updates-file -` with the quoted input format in the [Supporting notes](command-reference.md#supporting-notes) section of the command reference.
- The command's `rows` field is the post-write read-back of each changed lane. Use it to verify the writes; do not run `sheets get` again afterwards.

## 4. Report results

Report only requested tracker work using collected evidence.

- **Updated:** Table: **Lane | Original status | Updated status | Reason**. One row per changed lane with pre-edit statuses, the statuses confirmed in the command's `rows` output, and a source-linked reason. Say if nothing changed.
- **Still needs action:** Missing updates or blockers requiring others’ action. Mark unclear ownership as unconfirmed.
- **Waiting on you:** Only actions or decisions explicitly assigned to the user. Presenting, attending, or receiving email does not establish ownership.
- **Next step:** At most one question offering a draft to a verified contact who owes information. No unrelated edits, requests for the user’s decisions from others, or drafts saved without approval.

List open items as bullet points, each under either **Still needs action** or **Waiting on you**, never both. Exclude healthy, unblocked lanes from both. Use confirmed statuses, not stale summary counts. Do not suggest maintaining those counts or imply other files were edited.
