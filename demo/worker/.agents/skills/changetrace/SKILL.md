---
name: changetrace
description: Use before exploring or editing code, before committing, and when asked why code is the way it is — checks and records engineering decisions in .context/ with the ct CLI.
---

# ChangeTrace

Decision records live in `.context/decisions/` next to the code they protect. Use the `ct` CLI to read them, check edits against them, and add new ones. Run every command from the repository root.

## Rules

1. **Before exploring a file or a setting**, read what was decided about it.
   - `ct explain <path>` lists the records that touch a file.
   - `ct why <KEY>` shows the records behind a setting, a `file#Symbol`, or a record ID.
   - Read the active decisions before you propose a change.

2. **Before and after editing a file that has records**, run `ct check --file <path>`.
   - Exit code 1 means the edit undoes a recorded decision. Stop.
   - Tell the developer using the conflict reply below. Offer alternatives.
   - Do not make the conflicting edit unless the developer says so.

3. **If the developer decides to override a decision**, draft a superseding record, show it, and wait for a yes. Then run `ct supersede <ID> --input -` with the draft on stdin.

4. **Before committing a meaningful change**, draft a record. A meaningful change is a changed default or config value, a behaviour change, or an approach chosen over a rejected alternative.
   - Build the draft from the reasoning the developer approved, the diff, and the tests.
   - Show the draft and wait for a yes.
   - Then run `ct capture --from-diff --input -` with the draft on stdin.
   - Commit the new record in the same commit as the code.

5. **Never**:
   - save transcripts or chat logs;
   - edit the body of a merged record (supersede it instead);
   - invent a decision the developer did not make;
   - run `ct capture` or `ct supersede` before the developer has seen the draft and said yes.

## Conflict reply

> This edit conflicts with CTX-NNN, "<title>".
> - Decided: <what was decided>
> - Why: <the problem it solved>
> - Watch out: <the recorded warning>
> - Evidence: <commit, PR, tests, deployments from `ct why`>
> - Alternatives: <options that keep the decision intact>
>
> Proceed anyway?

## Capture draft

```markdown
---
title: <short title>
---

## Problem
<what was wrong or missing>

## Decided
<what was chosen>

## Tried and ruled out
<alternatives and why they lost>

## Assumptions
<what must stay true>

## Watch out
<what breaks if this is undone>

## Evidence
<tests, PRs, measurements>
```

`ct capture --from-diff` fills in the guards (changed keys with old and new values) from the working-tree diff. Leave them out of the draft.
