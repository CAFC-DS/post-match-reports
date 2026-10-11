"""Read-only probe of what CAFC_DB can supply for analyst-report panels.

Answers the Phase 0 data questions for the analyst-report redesign:

* Where (if anywhere) does a shot's goal-mouth position live?
* Which reception KPIs does Impect tag on RECEPTION events?
* Are other clubs' events loaded, i.e. can we build league averages?
* Is there any substitution / minutes information in the event log?

Only SELECT/DESCRIBE/SHOW statements are issued. Usage::

    SNOWFLAKE_PRIVATE_KEY_PATH=/path/key.pem python scripts/probe_report_data.py [--match-id N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.snowflake_connection import SnowflakeConnector  # noqa: E402
from src.report.impect_cafcdb_source import DEV_ROLE, DEV_WAREHOUSE  # noqa: E402

EVENTS = "CAFC_DB.IMPECT_RAW.EVENTS"
MATCHES = "CAFC_DB.IMPECT_RAW.MATCHES"


def _run(cur, sql: str, params: dict | None = None) -> list[tuple]:
    first = sql.lstrip().split(None, 1)[0].upper()
    if first not in {"SELECT", "WITH", "DESCRIBE", "SHOW"}:
        raise ValueError(f"probe is read-only; refusing {first}")
    cur.execute(sql, params or {})
    return cur.fetchall()


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _json_keys(value) -> set[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return set()
    keys: set[str] = set()

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(f"{prefix}{k}")
                walk(v, f"{prefix}{k}.")
        elif isinstance(node, list):
            for item in node:
                walk(item, prefix)

    walk(value)
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", type=int, help="Impect match id (default: latest Charlton match)")
    args = parser.parse_args()

    with SnowflakeConnector(".env").connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")

        _section("EVENTS columns")
        for row in _run(cur, f"DESCRIBE TABLE {EVENTS}"):
            print(f"  {row[0]:<28} {row[1]}")

        match_id = args.match_id
        if match_id is None:
            match_id = _run(
                cur,
                f"""select m.ID from {MATCHES} m
                    join CAFC_DB.IMPECT_RAW.SQUADS s on s.ID in (m.HOMESQUADID, m.AWAYSQUADID)
                      and s.ITERATION_ID = m.ITERATIONID
                    where s.NAME = 'Charlton Athletic'
                      and exists (select 1 from {EVENTS} e where e.MATCH_ID = m.ID)
                    order by m.SCHEDULEDDATE desc limit 1""",
            )[0][0]
        print(f"\nprobing match {match_id}")

        _section("distinct ACTION / ACTION_TYPE in the match (top 40)")
        for action_type, action, n in _run(
            cur,
            f"""select ACTION_TYPE, ACTION, count(*) n from {EVENTS}
                where MATCH_ID = %(m)s group by 1, 2 order by n desc limit 40""",
            {"m": match_id},
        ):
            print(f"  {str(action_type):<22} {str(action):<26} {n}")

        _section("SHOT rows: every JSON key that could carry goal-mouth placement")
        shot_rows = _run(
            cur,
            f"""select START_DETAIL, END_DETAIL, EVENT_KPIS, RESULT, SHOT_DETAIL, RAW_EVENT from {EVENTS}
                where MATCH_ID = %(m)s and ACTION_TYPE = 'SHOT' limit 200""",
            {"m": match_id},
        )
        print(f"  shot rows sampled: {len(shot_rows)}")
        key_counts: Counter[str] = Counter()
        for start_d, end_d, kpis, _, shot_d, raw_d in shot_rows:
            for prefix, blob in (("START_DETAIL.", start_d), ("END_DETAIL.", end_d),
                                 ("SHOT_DETAIL.", shot_d), ("RAW_EVENT.", raw_d)):
                key_counts.update(prefix + k for k in _json_keys(blob))
            key_counts.update("EVENT_KPIS." + k for k in _json_keys(kpis))
        for key, n in sorted(key_counts.items()):
            flag = "  <-- candidate" if any(t in key.lower() for t in ("goal", "target", "z", "height", "post")) else ""
            print(f"  {key:<48} {n}{flag}")
        if shot_rows:
            print("  example END_DETAIL:", shot_rows[0][1])
            print("  example SHOT_DETAIL:", str(shot_rows[0][4])[:600])

        _section("RECEPTION rows: EVENT_KPIS keys and detail keys")
        rec_rows = _run(
            cur,
            f"""select START_DETAIL, END_DETAIL, EVENT_KPIS, RAW_EVENT, PASS_DETAIL from {EVENTS}
                where MATCH_ID = %(m)s and ACTION_TYPE = 'RECEPTION' limit 300""",
            {"m": match_id},
        )
        print(f"  reception rows sampled: {len(rec_rows)}")
        rec_keys: Counter[str] = Counter()
        for start_d, end_d, kpis, raw_d, pass_d in rec_rows:
            rec_keys.update("START_DETAIL." + k for k in _json_keys(start_d))
            rec_keys.update("EVENT_KPIS." + k for k in _json_keys(kpis))
            rec_keys.update("RAW_EVENT." + k for k in _json_keys(raw_d))
            rec_keys.update("PASS_DETAIL." + k for k in _json_keys(pass_d))
        for key, n in sorted(rec_keys.items()):
            print(f"  {key:<56} {n}")
        if rec_rows:
            print("  example EVENT_KPIS:", str(rec_rows[0][2])[:400])

        _section("PLAYER_POSITION values and FORMATION_DETAIL sample (team sheet / lineups)")
        for pos, side, n in _run(
            cur,
            f"""select PLAYER_POSITION, PLAYER_POSITION_SIDE, count(*) from {EVENTS}
                where MATCH_ID = %(m)s and PLAYER_ID is not null group by 1, 2 order by 3 desc limit 30""",
            {"m": match_id},
        ):
            print(f"  {str(pos):<22} {str(side):<10} {n}")
        formation = _run(
            cur,
            f"""select ACTION_TYPE, ACTION, GAME_TIME, FORMATION_DETAIL from {EVENTS}
                where MATCH_ID = %(m)s and FORMATION_DETAIL is not null order by EVENT_INDEX limit 3""",
            {"m": match_id},
        )
        for row in formation:
            print("  formation row:", str(row)[:500])
        if not formation:
            print("  (no FORMATION_DETAIL rows)")

        _section("DUEL_DETAIL / DRIBBLE_DETAIL keys")
        detail_keys: Counter[str] = Counter()
        for duel_d, drib_d in _run(
            cur,
            f"""select DUEL_DETAIL, DRIBBLE_DETAIL from {EVENTS}
                where MATCH_ID = %(m)s and (DUEL_DETAIL is not null or DRIBBLE_DETAIL is not null) limit 300""",
            {"m": match_id},
        ):
            detail_keys.update("DUEL_DETAIL." + k for k in _json_keys(duel_d))
            detail_keys.update("DRIBBLE_DETAIL." + k for k in _json_keys(drib_d))
        for key, n in sorted(detail_keys.items()):
            print(f"  {key:<48} {n}")

        _section("league scope: matches with events, by iteration (top 10)")
        for iteration, matches, with_events in _run(
            cur,
            f"""select m.ITERATIONID, count(distinct m.ID), count(distinct e.MATCH_ID)
                from {MATCHES} m left join {EVENTS} e on e.MATCH_ID = m.ID
                group by 1 order by 2 desc limit 10""",
        ):
            print(f"  iteration {iteration}: {matches} matches, {with_events} with events")

        _section("player-level events for other clubs in the probed match's iteration")
        for squad, players, events in _run(
            cur,
            f"""select sq.NAME, count(distinct e.PLAYER_ID), count(*) from {EVENTS} e
                join {MATCHES} m on m.ID = e.MATCH_ID
                join CAFC_DB.IMPECT_RAW.SQUADS sq on sq.ID = e.SQUAD_ID and sq.ITERATION_ID = m.ITERATIONID
                where m.ITERATIONID = (select ITERATIONID from {MATCHES} where ID = %(m)s)
                group by 1 order by 3 desc limit 30""",
            {"m": match_id},
        ):
            print(f"  {str(squad):<30} players={players:<4} events={events}")

        _section("substitution / lineup markers in the event log")
        for action_type, action, n in _run(
            cur,
            f"""select ACTION_TYPE, ACTION, count(*) from {EVENTS}
                where MATCH_ID = %(m)s
                  and (upper(ACTION_TYPE) like '%%SUB%%' or upper(ACTION) like '%%SUB%%'
                       or upper(ACTION_TYPE) like '%%LINE%%' or upper(ACTION) like '%%LINE%%'
                       or upper(ACTION) like '%%CARD%%')
                group by 1, 2""",
            {"m": match_id},
        ):
            print(f"  {str(action_type):<22} {str(action):<26} {n}")
        print("  (empty above = no substitution rows in the Impect event log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
