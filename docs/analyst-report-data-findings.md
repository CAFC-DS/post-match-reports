# Analyst report: what CAFC_DB can supply

Output of `scripts/probe_report_data.py` (read-only), run 2026-09-30 against Impect match 267920
(a completed Charlton fixture). Re-run it to refresh; it only issues SELECT/DESCRIBE/SHOW.

| Panel | Verdict | Where the data is |
|---|---|---|
| Shot placement map | **Available, built** | `EVENTS.RAW_EVENT:shot.targetPoint.y` / `.z` (goal-mouth position), also `shot.gk.*`, `shot.woodwork`, `shot.angle`, `shot.distance`. Read by `impect_cafcdb_source` (`targetY`, `targetZ`, `woodwork`); +y is the attacker left (LEFT_POST = +3.7), checked against Opta F24 qualifier 102 (r = 0.87). Shown on the Shot Placement page. |
| Where players received the ball | **Available** | `EVENTS.ACTION` on `RECEPTION` rows: `AVAILABILITY_BTL` (between the lines), `AVAILABILITY_OUT_WIDE`, `AVAILABILITY_IN_THE_BACK`, `AVAILABILITY_IN_THE_BOX`, `AVAILABILITY_FDR`, `HOLD_UP_PLAY`. Already loaded as `action`. Packing on receiving: `EVENT_KPIS.BYPASSED_OPPONENTS_RECEIVING` (not yet in `_KPI_FIELDS`). |
| League averages (players) | **Built from events** | `CHAMPIONSHIP_PLAYER_KPIS` stops at 25/26 and `ITERATION_PLAYER_KPIS` has no 26/27 rows, so 26/27 season and league baselines come from `EVENTS` (`EVENT_KPIS` entries credited per player) with minutes from `MATCH_INFO`. See `src/report/expanded/player_baseline.py`. |
| Player positions | **Available** | `EVENTS.PLAYER_POSITION` / `PLAYER_POSITION_SIDE` (e.g. `CENTRAL_DEFENDER`/`CENTRE_LEFT`). |
| Formation strings | **Available** | `EVENTS.FORMATION_DETAIL` (`{"team": "4-2-3-1", "opponent": "4-2-3-1"}`). |
| Cards | **Available** | `YELLOW_CARD` events (goals via `GOAL`). |
| Substitutions / minutes played | **Not in Impect** | No substitution rows. Use DVMS F7 lineups (`status` Start/Sub) and DVMS/F24 for timing; `metrics.timeline` already infers subs. |

Other iterations (1464, 1465) also hold 557 matches with events; confirm which iteration id is the
current season's before computing league baselines (the one used by `season_baseline.py` for Charlton
is the source of truth).
