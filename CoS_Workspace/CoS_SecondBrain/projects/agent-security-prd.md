---
title: Agent Security PRD
created: 2026-09-09
updated: 2026-09-22
type: project
tags: [project, agent-security, engineering, priority]
sources: [raw/updates/agent-security-engineering-request.md]
status: active
confidence: high
---

# Agent Security PRD

The product requirements document defines what the system must protect, what it may do, and what happens when a security check fails. [[marcus-lee]] leads the engineering work. I need to review the open requirements, decide the fallback policies and audit requirements, and update and finalize the document.

## Work still to finish
- Describe the threats and the points where information or actions cross a trust boundary.
- Define the events needed to investigate who requested an action and why it was allowed or denied.
- Specify what happens when the policy service is unavailable. The proposed fail-closed approach stops protected actions rather than treating a missing answer as permission.
- Resolve the network-access default with [[openshell]].
- Define the limits of an administrator override.

## Proposed acceptance checks
| Situation | Behavior to specify | Observable evidence |
|---|---|---|
| Policy service unavailable | Whether execution stops and how the user is informed | No protected action occurs without the required decision |
| Destination outside the allowlist | Denial and a clear exception route | Requested destination and denial reason are attributable |
| Administrator override | Scope, duration, authority, and revocation | Override can be traced to an authorized identity |
| Interrupted execution | Safe handling of partial completion and retries | The system does not silently repeat a consequential action |

These are test cases to specify, not tests already passed.

## Final document review
Prepare a data-flow sketch, list of trust boundaries, decision table, audit-event examples, and open choices. Show which controls belong in the runtime and which depend on identity or infrastructure services.

A reviewer should be able to follow a request from identity through the permission check to execution and reporting. Use a protected focus block under the [[executive-attention-model|attention plan]] to review, update, and finalize the document, resolving the open security-policy decisions. More optional review meetings should not crowd out that work.
