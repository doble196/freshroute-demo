# IRC validation protocol - frozen before the window opens

Frozen 2026-08-12, under registration `64c5bcd80c34f5e7ede884ab7f1ca9ccd382b940`.
Machine-readable twin: `irc_validation_protocol.json` (gated against the
registration; the result must embed both hashes). This document freezes HOW
the one authorized validation run happens, so that when it runs there is
nothing left to decide - a procedure chosen after seeing data is a procedure
chosen by the data.

## The exact command

```bash
python3 irc_run_validation.py --i-am-opening-the-one-shot-window
```

The flag is deliberately unpleasant to type. Running without it refuses.
Running when `irc_validation_result.json` already exists refuses **first**,
before the flag is read and before any network access - the allowance is 1,
and the refusal order makes a second opening impossible rather than impolite.

`--dry-run` exercises the full pipeline and schema against the pinned
fixture, writes nothing, and may be run freely. It is how the plumbing is
proven without spending the window.

## The one-shot procedure

1. Verify the registration and protocol files are byte-identical to their
   committed versions (the runner checks the pins; the gates check them too).
2. Run the exact command above. The runner will:
   - pull the live inspection-grain data and persist the input snapshot
     (`irc_validation_snapshot.json.gz`, gzip mtime 0, sha256 recorded over
     the uncompressed canonical JSON);
   - build observations ONLY for as-of dates `>= 2024-07-01`;
   - classify with the engine exactly as shipped - no parameter differs from
     `irc_prereg.json`;
   - pair outcomes, count censoring, and evaluate H1 by the registered bars
     (monotonic, >=5.0pp, n>=500 per level, Wilson 95%);
   - write `irc_validation_result.json` embedding the registration hash, the
     protocol sha256, the snapshot sha256, and the publisher watermark.
3. Commit the result and the snapshot in one commit whose message states the
   verdict - pass, fail, or inconclusive - with the same prominence.
4. Publish the verdict either way. On failure: the rating is abandoned. On
   inconclusive (support below n=500 in either level): a new methodology
   version against a later window. **This window is spent in every branch.**

## What this rung did and did not do

Development diagnostics ran on as-of dates strictly before 2024-07-01 and
produced the registered censoring, exclusion, stratum, and age-sensitivity
tables (`irc_dev_diagnostics.json`). Validation as-of dates were counted -
counted only - to size the reserved window. No validation outcome was
computed, paired, aggregated, or looked at. The gates enforce that the two
windows partition the date line exactly and that the sealed-door file does
not exist in either repository.

## Provenance note (non-methodological commits)

Repository hygiene commits - e.g. removing accidentally committed Python
bytecode (`52ab9ab`, `a395d29` in the public repository) - are
non-methodological: they change no rating logic, no constant, no gate, and no
artifact. Provenance readers should not mistake them for engine
modification. Methodological change is identifiable by exactly two markers:
a new `methodology_version` in `irc_prereg.json`-governed artifacts, or a
change to a file the gate suite pins.
