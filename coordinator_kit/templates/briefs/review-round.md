# Review round: {what}

- Target: branch `{branch}` (diff against `{base}`), or the output pack `{pack_dir}`.
- Goal: an independent verdict before merge or adoption.
- Read first: `{rules_path}`.

## Code review
- Review the diff for correctness: wrong results, crashes, races, broken invariants and missing tests on changed paths. Style is out of scope unless it hides a bug.
- Report each finding with the file and line, a concrete failing input, and its severity. If nothing survives verification, say so.

## Blind judging (outputs)
- **One item at a time.** Open one item, decide, append its ballot line to `{ballots_file}` (outside the pack), then open the next. Never open a whole batch first: answers get mixed up, and a stall loses everything.
- **Batches of at most about 9 items** per judge. Use a fresh judge for each batch.
- **Blind:** the pack hides which arm is new. The answer key stays outside the pack.
- **Controls:** include one unchanged pair to measure judge noise.
- **Canary first** for any model whose image reading you haven't verified: one image of known content that it must describe correctly.
- Ballot line: `{"item": "…", "verdict": "better|same|worse", "visible_at_normal_size": "yes|no", "note": "…"}`. Low confidence is a valid answer.

## Report
The verdict and counts first, then the findings or ballots file path.
