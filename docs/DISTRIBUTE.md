# Intelligent distribution

"Distribuição inteligente" or simply "distribui" is the bot mode that decides, on its own,
where a block of new videos should be produced. The owner never has to pick the channels.

## What it does

1. Audits every registered channel and reads the **date of its last scheduled video**.
2. Gives the next video to the channel whose queue ends earliest (an empty queue comes first).
3. Advances that channel's end date using its own slot hours and `interval_days`.
4. Repeats until the requested count is allocated, so the channels that would run out first
   are extended before a channel with a long queue receives anything.
5. Runs one batch per channel, in sequence, each with its own profile.

The allocation is a water fill by queue end date, not just by count: two channels with the
same number of videos can end weeks apart, and the earlier one is served first. A channel with
a long queue can receive zero. That is intentional.

## Command

```bash
python3 -m tools.ytbot distribute --count 20
python3 -m tools.ytbot distribute --count 20 --dry-run
```

`--dry-run` prints the audit and the plan without generating anything.

## Audit

`distribute.last_scheduled` reads the channel's `runs/*/upload.json` records and returns the
latest slot whose `scheduled` flag is true and whose date is still in the future.
`distribute.audit_dates` builds that map for every long-form channel and
`distribute.allocate_by_date` water-fills by that date. The audit is cheap and runs before any
browser opens.

The plan is printed before the first batch:

```text
[distribute] future scheduled: {'zaflas': 4, 'fallem-prince': 70, 'infinite-random-worlds': 0, ...}
[distribute] queue ends: reflection=2026-12-04 21:00, whispers-from-heaven=2026-12-04 22:00, ...
[distribute] plan: {'reflection': 5, 'whispers-from-heaven': 5, 'fallem-prince': 0, ...}
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

## Concurrency

Two channels are produced at the same time by default (`--concurrency 2`, `1` restores the
fully sequential plan). Isolation is preserved:

- each channel batch keeps its own `channel_lock` and its own upload-profile lock;
- the shared legacy generation browser is bounded by generation slot locks
  (`YTBOT_GENERATION_SLOTS`, default 2): a third concurrent batch queues on a slot instead
  of failing, exactly like the old exclusive lock;
- channel starts are staggered 30 seconds so hidden Chrome and ChatGPT never race;
- each channel's full output goes to `.local/ytbot/distribute-<channel>.log`, and the plan
  log carries one `exit=` line per channel.

## Failures

A failing channel does not stop the plan. The batch is recorded, the next channel runs, and
the command exits non-zero with the failed channels at the end. Uncertain uploads keep the
normal fencing: never re-upload a video that already has an `upload.json` video ID.

## When the owner says "distribui"

Run the audit first, state the plan, then run it. No confirmation is needed unless the plan
would touch a fenced operation: a paused Fallem batch, an account without a verified channel
binding, or a channel the owner explicitly paused.
