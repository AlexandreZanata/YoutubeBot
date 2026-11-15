# Intelligent distribution

"Distribuição inteligente" or simply "distribui" is the bot mode that decides, on its own,
where a block of new videos should be produced. The owner never has to pick the channels.

## What it does

1. Audits every registered channel.
2. Counts the uploads already scheduled in the future for each one.
3. Gives the next video to the channel with the fewest future scheduled uploads.
4. Repeats until the requested count is allocated, so a channel that was empty catches up
   before a channel that already has many scheduled videos receives anything.
5. Runs one batch per channel, in sequence, each with its own profile.

The allocation is a water fill: the channels level out, and a channel with a large queue can
receive zero. That is intentional.

## Command

```bash
python3 -m tools.ytbot distribute --count 20
python3 -m tools.ytbot distribute --count 20 --dry-run
```

`--dry-run` prints the audit and the plan without generating anything.

## Audit

`distribute.future_scheduled` reads the channel's `runs/*/upload.json` records and counts only
the uploads whose `scheduled` flag is true and whose slot is still in the future. The audit
is cheap and runs before any browser opens.

The plan is printed before the first batch:

```text
[distribute] future scheduled: {'zaflas': 4, 'fallem-prince': 70, 'infinite-random-worlds': 0, ...}
[distribute] plan: {'zaflas': 3, 'fallem-prince': 0, 'infinite-random-worlds': 7, ...}
```

## Channel isolation

Each channel keeps its own rules and the distribution never mixes them:

- prompts, language, article length, narration and thumbnail style come from the channel
  profile in `tools/ytbot/channels.py`;
- the background comes from the channel profile;
- the upload account comes from the binding saved in the accounts store;
- the schedule uses the channel's own slot hours and its `interval_days` cadence
  (Vocal Pages publishes every two days, for example).

The distribution only decides the quantity per channel. Everything else is the channel's
existing pipeline.

## Slots

Each per-channel batch runs the normal `run` command without a start date, so the slots come
from the channel's last scheduled uploads. A channel that already has videos in the future
continues after them; it never overlaps or reuses a slot.

## Failures

A failing channel does not stop the plan. The batch is recorded, the next channel runs, and
the command exits non-zero with the failed channels at the end. Uncertain uploads keep the
normal fencing: never re-upload a video that already has an `upload.json` video ID.

## When the owner says "distribui"

Run the audit first, state the plan, then run it. No confirmation is needed unless the plan
would touch a fenced operation: a paused Fallem batch, an account without a verified channel
binding, or a channel the owner explicitly paused.
