# Pool Pump — Smart cycling for Hayward VSTD via Antea VS

A Home Assistant custom integration that runs a Hayward VSTD variable-speed
pool pump at a low **v1 baseline 24/7**, then opportunistically bumps to higher
speeds when (a) excess solar covers the extra consumption, (b) water/air are
warm enough to justify extra filtration, and (c) it's daylight. The high speed
**v3 is hard-capped at 15 minutes per session** (with a 30-minute cooldown) to
respect the CS100 sand filter's flow tolerance.

## Why

- The pump should keep moving water 24/7 for sanitiser dispersion and surface
  film management — but at the lowest sustainable speed when nothing else
  justifies a boost.
- When the panels are exporting more than the pump's incremental load, you
  may as well dump that energy into circulation rather than feed-in.
- v3 is a *skimming burst*: 15 min of high-flow surface skimming, then back
  off so the filter doesn't get pummelled.

## What it gives you

A single device with these entities:

- `select.pool_pump_mode` — `auto / winter / off / v1 / v2 / v3`. `auto`
  runs the summer brain (warmth-gated boost). `winter` runs the cold-season
  brain (solar-only, capped at v1, force-off on Tempo Red days). The
  others are manual overrides.
- `sensor.pool_pump_target_speed` — current target (0..3) the brain wants.
- `sensor.pool_pump_decision_reason` — human-readable text explaining the
  current decision (e.g. *"solar surplus covers v3 + warm → v3 skim session"*).
- `sensor.pool_pump_v3_session_age` — seconds elapsed in the current v3
  session (or `unknown` when no session is active).
- `sensor.pool_pump_v3_cooldown_remaining` — seconds before the next v3
  session is allowed.
- `sensor.pool_pump_grid_smooth` — EMA-smoothed grid power that the brain
  actually decides against (in W, `device_class: power`).
- `button.pool_pump_force_skim` — start a v3 session right now (still
  respects cooldown and surplus availability).
- `button.pool_pump_reset_v3_cooldown` — clear the cooldown so a fresh v3
  session can start immediately (useful after a manual backwash).

## Speed → power table (calibrated by the user for a Hayward VSTD)

| Speed | RPM    | Power | Use |
|------:|-------:|------:|---|
| 0     | off    | 0 W   | Avoid — pump should keep running |
| 1     | 1500   | 160 W | **24/7 baseline** circulation |
| 2     | 2500   | 500 W | Sustained boost (filtration) |
| 3     | 3000   | 1100 W| **Skim session**, capped at 15 min |

## Decision logic (priority chain)

1. **Manual mode** — if `select.pool_pump_mode` is anything other than
   `auto`, that wins.
2. **Force-skim button** pressed → start a v3 session (subject to cooldown +
   solar surplus).
3. **Night** (`sun.sun == below_horizon`) → v1.
4. **In v3 session**: hold v3 until cap reached or solar surplus drops, then
   demote to the highest sustainable speed.
5. **v3 candidate**: daylight + cooldown elapsed + warm enough + solar
   surplus would cover the bump → start a v3 skim session.
6. **v2 candidate**: solar surplus would cover the bump to v2 → v2.
7. **Default** → v1.

"Solar surplus covers the bump" is computed from a **smoothed** grid power
reading (EMA, alpha=0.3 — about 5 minutes for a step change to fully
register, so a 30–60 s cloud is invisible to the brain):

```
expected_grid_after_bump = smoothed_grid + (target_W − current_W)
allowed only if expected_grid_after_bump < −safety_margin_w
```

In addition, **v2 also requires a "warm enough" gate** — same as v3 — so a
chilly day with surplus stays at v1 instead of dumping the surplus into
sustained v2 with no filtration upside.

A **min-dwell rate limit** (60 s by default) prevents two speed changes
within a minute of each other. Manual modes (`off/v1/v2/v3`), the
force-skim button, and v3 session entry/exit bypass it. `auto` and
`winter` always go through the rate limit.

> **Note on manual `v3`:** when you pick `v3` from the mode select, you
> override the brain entirely — including the 15-min skim cap. Manual
> mode is sovereign, so the cap doesn't fire until you switch the mode
> back to `auto` (or pick another manual speed). If you need a strict
> 15-min skim, use the **Force skim now** button instead.

### Winter mode

When `select.pool_pump_mode = winter`:

1. If the optional Tempo color sensor reads `Rouge` → pump is **off** for
   the whole day (cheapest is no consumption).
2. Otherwise at night → **off**.
3. Otherwise if smoothed solar surplus covers the bump from current speed
   up to v1 (need `grid + 160W - current_W < −safety_margin`) → **v1**.
4. Otherwise → **off**.

Winter mode never exceeds v1 even with huge surplus — the cold-season
filtration target is "circulate when free, sit still when not". The
force-skim button is ignored in winter mode.

## Config flow

Three steps:

1. **Entities**: pump speed (a `number` entity, 0–3), grid power sensor,
   water/air temperature sensors (both optional but at least one is needed
   to ever bump to v3).
2. **Thresholds**: solar safety margin (default 200 W), warm-water/air
   temperatures (defaults 24 °C / 28 °C).
3. **v3 limits**: max session minutes (default 15) and cooldown minutes
   (default 30).

The Options flow lets you tune steps 2–3 after install. The entity bindings
from step 1 are pinned at install time.

## Tests

Pure decision logic lives in `decision.py` (no `homeassistant` imports), so
the test suite runs standalone:

```bash
pytest                                   # all 23 cases
pytest tests/test_decision.py::TestV3InProgress  # one class
```

## License

MIT.
