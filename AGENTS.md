# AGENTS.md

## Purpose
This repository contains project-specific guidance for coding agents working on this codebase.

Agents must read and follow this file before making changes.

## Primary References
For Re:Check work, use these documents as the source of truth:

1. `docs/specs/recheck_v0.1.md`
2. `docs/exec-plans/recheck_v0.1_execplan.md`

If there is any ambiguity:
- prefer the spec first
- then follow the exec plan
- do not invent product behavior outside those documents

## General Working Rules
- Keep changes focused and minimal.
- Do not perform unrelated refactors.
- Do not rename files, modules, or folders unless required by the task.
- Do not add features that are not explicitly required.
- Prefer simple, readable implementations over overengineering.
- Preserve existing project conventions if they already exist.
- If the repository already has an app/tool structure, follow it instead of introducing a new parallel structure.

## Re:Check Product Rules
Re:Check is a **local Windows GUI review tool for folder diffs**.

Its v0.1 role is limited to:
1. choosing comparison scope
2. showing folder/file diffs
3. previewing Base and Compare side by side
4. saving snapshots and compare logs

### Non-goals for v0.1
Do **not** add any of the following unless the spec is updated:
- labels
- priority / importance
- auto judgment
- comments workflow
- return/fix workflow
- sync
- merge
- rule-engine behavior
- auto-fix
- advanced content diffing outside the defined v0.1 scope

## UI Rules
Follow the intended layout and interaction model from the spec.

Main mental model:
- left = where to compare
- center = what changed
- right = Base vs Compare preview

Additional UI requirements:
- History must not be always visible.
- History should open from a dedicated button/panel interaction.
- Project-level actions belong near the Project selector (`...` menu).
- App-level settings belong under the gear icon.
- Keep the UI calm, soft, modern, and Windows-friendly.
- Prioritize clarity over decorative complexity.

## Preview Rules
Initial preview support should prioritize:
- image
- text
- PDF
- audio

Video:
- optional in v0.1
- only add if implementation is simple and stable

Office files:
- external open only in v0.1

Audio preview is important and should be treated as a higher priority than video.

## Persistence Rules
Comparison execution should save:
- compare log
- snapshot data as defined by the spec

Persist clearly and simply.
Do not build a heavy database system unless it is necessary for the defined scope.

## Implementation Expectations
Before major implementation work:
- inspect the repository layout
- determine the best placement for Re:Check
- follow existing structure if available

For Re:Check implementation tasks:
- align work with `docs/exec-plans/recheck_v0.1_execplan.md`
- keep progress traceable to the defined phases
- stop at the v0.1 boundary

## Documentation Expectations
When implementation changes are made, update only the docs that are necessary:
- run instructions
- changed architecture notes
- spec-adjacent docs if behavior was intentionally clarified

Do not rewrite broad repository documentation without need.

## Final Response Expectations
At the end of a task, provide:
- changed files
- short summary of what was implemented
- how to run or validate
- what was intentionally deferred
- any known limitations or incomplete parts

## If Unsure
If something is unclear:
- check the spec
- check the exec plan
- choose the narrowest implementation that satisfies both
- avoid adding speculative behavior