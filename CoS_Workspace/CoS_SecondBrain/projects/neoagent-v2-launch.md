---
title: NeoAgent V2 Launch
created: 2026-09-09
updated: 2026-09-22
type: project
tags: [project, neoagent-v2, launch, strategy]
sources: [raw/meetings/leadership-staff-2026-09-08.md, raw/updates/performance-results-package.md]
status: at-risk
confidence: high
---

# NeoAgent V2 Launch

This project brings together the presentation, product evidence, partner demos, retail preparation, and campaign materials for the NeoAgent V2 launch. The immediate goal is to help leadership choose the keynote story and the demos to show at GTC.

## Where things stand
The recorded performance results are approved for leadership review with the NeoAgent V1 baseline and evaluation scope intact. The executive presentation and marketing materials still need updates. The retail demo still needs a confirmed owner, and the marketing shoot needs a replacement date.

Approved evidence is ready to use, but the slides still need editing and proposed demo owners still need to accept their assignments.

## Who is involved
- [[elena-park]] coordinates the [[neoagent-v2-executive-review]].
- [[mike-chen]] owns the [[performance-results|product evidence]].
- [[aisha-rahman]] and [[sofia-alvarez]] connect the presentation to the [[hermes-partner-program|partner program]].
- [[marketing-claims-rollout]] covers updates to campaign materials.
- [[marketing-shoot]] covers production and the venue decision.
- [[grant-walker]] is the retail-readiness contact; the final demo assignment remains open.

## What leadership needs to decide
1. Approve the [[agent-first-storyline|proposed keynote story]].
2. Choose the [[gtc-demo-slate|GTC demos]] and confirm who is responsible for each.
3. Select a replacement shoot date.

Before the review, prepare a recommendation and explain the alternatives. The decisions themselves belong in the meeting.

## What to put in the presentation
Start with a problem the audience recognizes. Show how the proposed workflow helps, what information it uses, and what the person still reviews or decides. Compare candidate demos by the benefit they show, the preparation they need, and any unresolved setup or ownership questions.

Keep the sources for existing claims close to the relevant material. Shortening a claim must not remove the conditions that make it accurate.

## What could delay the work
An unassigned retail demo could hold up the final list. The venue change could reduce preparation or editing time. Unclear product wording could require another review.

If a live demo cannot be shown, prepare reviewed screenshots or a narrated walkthrough. Present it as a walkthrough, not as proof of a successful live run. This preparation adds no new product performance claims.

## Product learning notes

NeoAgent is an agent harness: software around a model that decides which information and tools a workflow needs, carries context between steps, and verifies the result. NeoAgent V2 improves that orchestration while retaining the model used by NeoAgent V1.

### What changes in V2
The proposed product story focuses on more reliable task completion, less time spent repeating work, and fewer model tokens per completed task. Context selection, tool-result reuse, and explicit completion checks are the harness features to demonstrate. The approved comparison and metric definitions live in [[performance-results]].

### How to demonstrate the value
Begin with work the audience recognizes. A daily brief shows whether the harness can separate news from actions. Meeting preparation shows whether it retrieves the right evidence. An email draft or tracker update shows whether it can finish a bounded task while keeping the user in control.

For a draft, check the recipient, conversation, and saved result. For a tracker, check the changed cells against the evidence and preserve unrelated cells. A fluent answer alone does not prove successful execution.

### Local processing and connected work
The model can run locally while the harness connects to Google Workspace. Reading Gmail and saving a Google draft still use Google's services. Local model processing does not make the workflow fully offline. Describe where information is retrieved, processed, and written before making a privacy claim.

The proposed retail example uses a local product catalog. The assistant compares laptops and drafts a customer follow-up, the associate reviews the draft, and customer details stay on the device in this proposed workflow. This is an illustrative use case, not customer validation or an approved GTC demo.

### Open questions
Which workflows best explain the harness? What must the user still decide? Which candidate demos are ready for a live run, who will own them, and what is the fallback if a dependency fails? Compare candidates by audience value, setup requirements, reliability, and distinct purpose.

The [[agent-security-prd|Agent Security PRD]] and [[openshell|OpenShell]] hold related permission and control questions. The [[gtc-demo-slate|demo slate]] remains a leadership decision. These learning notes do not add new commitments or close pending work.
