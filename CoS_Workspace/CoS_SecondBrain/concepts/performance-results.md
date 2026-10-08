---
title: NeoAgent V2 Performance Results
created: 2026-09-09
updated: 2026-09-30
type: concept
tags: [performance-results, neoagent-v2, legal, marketing]
sources: [raw/updates/performance-results-package.md, raw/updates/legal-claims-clearance.md]
status: active
confidence: high
---

# NeoAgent V2 Performance Results

NeoAgent is an agent harness that plans work, selects tools, manages context, and checks results around an existing model. V2 is a harness update, not a new foundation model.

## Approved comparison
[[mike-chen]] owns the benchmark package.

| Measure | NeoAgent V1 | NeoAgent V2 | V2 change versus V1 |
| --- | --- | --- | --- |
| Task success | 80% (160/200) | 92% (184/200) | +12 percentage points |
| Median completion time, normalized | 100 | 70 | 30% lower |
| Model tokens per completed task, normalized | 100 | 75 | 25% fewer |

Both versions use the same underlying model, the same 200 internal document, email, and scheduling workflows, and the same execution environment. These are fictional internal demo figures, not measurements of a real product.

## How to read the figures
Task success means the expected end state was reached without an incorrect write. Completion time is compared on tasks completed by both versions. Token usage counts model input and output tokens, including retries, per completed task. Time and token indices set NeoAgent V1 to 100. The success change is 12 percentage points, not 12%.

These aggregate results do not predict every workflow's speed or reliability. They do not establish energy savings, hardware capability, or a particular model's inference speed.

## Approval and remaining work
[[daniel-cho]] cleared the comparison wording for leadership review. Keep the NeoAgent V1 baseline, metric definitions, and internal evaluation scope with the figures. Approval covers leadership review only. Final external copy needs a separate Legal review.

Slide 4 and [[marketing-claims-rollout|dependent campaign materials]] still need updating. Receipt of the results does not mean the deck edits, keynote storyline, or demo slate are approved.
