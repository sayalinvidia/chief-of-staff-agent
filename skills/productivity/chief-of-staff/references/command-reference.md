# Command reference

Pass these service commands and arguments to `run-actions.sh`, which runs the bundled `actions.py`. See Examples below. Uppercase placeholders require values. Brackets mark optional arguments. Defaults are shown where applicable.

| Command | Purpose | Optional arguments |
|---|---|---|
| `gmail search 'QUERY'` | Find matching messages’ headers, IDs, and links. | `--max 5` (1–10) |
| `gmail get MESSAGE_ID` | Read one message. | `--max-chars 12000` |
| `gmail thread THREAD_ID` | Read latest thread messages. | `--max-messages 12`, `--max-chars 8000` per message |
| `gmail important` | Read recent messages marked Important in Gmail, including their bodies. | `--max 12` (1–20), `--newer-than-days 2` (1–30 days), `--max-chars 8000` per message |
| `gmail drafts` | Read all saved drafts, including recipients, subjects, threads, and full bodies. | None |
| `gmail draft --to EMAIL --subject 'SUBJECT' --body-file -` | Save a new draft. | See Supporting notes 1–2. |
| `gmail draft --reply-to-message MESSAGE_ID --expected-to EMAIL --body-file -` | Save a reply draft. | See Supporting notes 1–2. |
| `drive search 'QUERY'` | Find files and return names, IDs, and links. | `--max 10`, `--raw-query` for Drive query syntax |
| `docs get DOCUMENT_ID` | Read document paragraph text. | `--max-chars 30000` |
| `docs inspect DOCUMENT_ID` | Read scoped text ranges and styles. | `--tab-id TAB_ID`, `--find 'TEXT'`, `--max-items 20`, `--max-chars 12000` |
| `docs format DOCUMENT_ID --find 'TEXT' --style-file - --confirm` | Apply requested formatting. See Formatting and previews. | `--tab-id TAB_ID`, `--all-matches` |
| `docs preview DOCUMENT_ID --workspace-root ROOT --output-dir DIR` | Save PDF and page PNGs inside the workspace. | `--pages '1,3-4'`, `--dpi 144` (72–200) |
| `docs append DOCUMENT_ID --text 'TEXT' --confirm` | Append text to a document. | None |
| `docs replace-text DOCUMENT_ID --find 'OLD' --replace 'NEW' --confirm` | Replace matching document text. | Case-insensitive unless `--match-case`. |
| `sheets get SPREADSHEET_ID [RANGE]` | Read cell values; tracker tables return labeled lane records. | `RANGE` defaults to `A1:J80` |
| `sheets tracker-evidence SPREADSHEET_ID_OR_TITLE --sheet 'TAB_NAME'` | Read tracker lanes and the recent mail relevant to each lane in one call (the evidence set for tracker updates). | `--days 14`, `--per-lane 3`, `--max-messages 16`, `--max-chars 700` |
| `sheets update SPREADSHEET_ID RANGE --values 'JSON' --confirm` | Write a JSON array of rows to a range. | None |
| `sheets update-lanes SPREADSHEET_ID --updates-file - --confirm` | Update demo tracker rows by lane name. | `--sheet 'Campaign Lanes'`, `--status-only` (default) or `--include-details`. See Supporting note 1. |
| `slides get PRESENTATION_ID` | Read slide text and `object_id` values, used as `SLIDE_OBJECT_ID`. | `--max-chars-per-slide 4000` |
| `slides inspect PRESENTATION_ID` | Read scoped element IDs, text ranges, and styles. | `--slide-id SLIDE_ID`, `--element-id ELEMENT_ID`, `--find 'TEXT'`, `--max-items 20`, `--max-chars 12000` |
| `slides format PRESENTATION_ID --slide-id SLIDE_ID --find 'TEXT' --style-file - --confirm` | Apply requested formatting. See Formatting and previews. | `--element-id ELEMENT_ID`, `--all-matches` |
| `slides preview PRESENTATION_ID --slide-id SLIDE_ID --workspace-root ROOT --output-dir DIR` | Save slide PNGs inside the workspace. | Repeat `--slide-id` for more slides. |
| `slides replace-text PRESENTATION_ID --find 'OLD' --replace 'NEW' --confirm` | Replace matching slide text. | `--slide-id SLIDE_OBJECT_ID` (otherwise the whole deck). Case-insensitive unless `--match-case`. |
| `slides delete PRESENTATION_ID --slide-id SLIDE_OBJECT_ID --confirm` | Delete one slide. | None |
| `calendar create --title 'TITLE' --start START --end END --confirm` | Create an event. START and END require timestamps with UTC offsets. Attendees receive invitations. | `--description 'TEXT'`, `--attendees 'EMAIL1,EMAIL2'`, `--calendar primary` |

## Supporting notes

1. **Draft bodies and tracker updates:** `gmail draft`: choose `--body 'TEXT'` or `--body-file PATH`. `sheets update-lanes`: choose `--updates 'JSON'` or `--updates-file PATH`. Either file argument accepts `-` for terminal input through a quoted heredoc. Draft bodies must be nonempty.

2. **Draft options:** `--cc 'EMAILS'` adds Cc. `--to` and `--subject` override reply defaults. `--expected-to EMAIL` checks recipients before saving. `--thread-id THREAD_ID` sets the thread. `--reply-to-message` also sets reply headers. Explicit To/Cc addresses require Gmail verification. Use `--allow-new-recipient` only for addresses the user supplied or confirmed.

## Formatting and previews

`inspect` returns text ranges and styles. Scope it to the relevant text, tab, slide, or element. Respect `truncated`. Docs covers body paragraphs, including tabs and tables. Slides reports explicit styles, not all master/layout inheritance.

`format` matches literal, case-sensitive text. Narrow ambiguous matches or use `--all-matches` only when every match should change. Choose `--style 'JSON'` or `--style-file PATH` (`-` reads standard input). Include only properties to change:

| JSON properties | Values |
|---|---|
| `bold`, `italic`, `underline` | `true` or `false` |
| `font_family`, `font_size` | Font name, size in points (1–400) |
| `color`, `link` | `#RRGGBB`, HTTP(S) URL or `null` to remove the link |
| `alignment` | `START`, `CENTER`, `END`, `JUSTIFIED` |
| `space_before`, `space_after`, `line_spacing` | Spacing in points (0–400), line spacing in percent (50–500) |
| `list` | `bulleted`, `numbered`, `none` |
| `heading` (Docs only) | 0 for normal text, 1–6 for headings |

Paragraph properties affect whole containing paragraphs. Headings apply named-style defaults. Lists can change indentation. Tab-indented list text is unsupported. Link edits preserve existing color and underline unless specified. Unresolved color requires an explicit value.

Formatting uses the current revision and verifies requested styles and unchanged text in one read-back. A failed verification can follow a successful write. Inspect the error before retrying. No new layouts, images, or charts are supported.

Previews save to a new subfolder under `--output-dir` inside the explicit workspace root. Linked folders/junctions are rejected. Files remain there. Docs exports a PDF and renders selected pages using PyMuPDF (default first three, maximum 20). Slides downloads Google-rendered PNGs (maximum 10 slides). These commands do not edit Google files or judge appearance. Inspect PNGs with an image-viewing tool before claiming visual verification.

## Examples

Replace `SKILL_ROOT` with the absolute directory containing this skill's `SKILL.md`. Each launcher call initializes itself and stops on failure. For batching, follow the example in the main skill's **How to run the scripts** subsection. Single command:

```bash
bash 'SKILL_ROOT/scripts/run-actions.sh' gmail thread THREAD_ID
```

Formatting example. Replace the target and include only requested styles. Quoted input goes to its own command:

```bash
bash 'SKILL_ROOT/scripts/run-actions.sh' docs format DOCUMENT_ID --find 'Section title' --style-file - --confirm <<'JSON'
{"heading":2,"space_after":8}
JSON
```

Read the result before choosing follow-up commands. Do not rerun failed batches automatically: earlier commands may have succeeded.
