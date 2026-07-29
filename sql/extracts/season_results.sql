-- One row per completed fixture in the competition/season, with the final score
-- derived from the event log itself (there is no results table on this
-- warehouse: TEAM_MATCH_DATA and the IMPECT_*_MATCH_SUMS tables are both stale
-- or gapped — see DATA_MODEL.md — so the events table is the only trustworthy
-- source, and it is the one the rest of the report already uses).
--
-- A goal is credited to the scoring player's own squad; an OWN_GOAL is credited
-- to the *other* squad. Aggregated in Snowflake rather than pulled row-by-row:
-- a season of Championship events is ~1.5m rows and the report only needs 552.
select
    "matchId"           as "match_id",
    max("dateTime")     as "kickoff_utc",
    max("homeSquadName") as "home_team",
    max("awaySquadName") as "away_team",
    sum(case when "action" = 'GOAL'     and "squadName" = "homeSquadName" then 1 else 0 end)
  + sum(case when "action" = 'OWN_GOAL' and "squadName" = "awaySquadName" then 1 else 0 end)
                        as "home_goals",
    sum(case when "action" = 'GOAL'     and "squadName" = "awaySquadName" then 1 else 0 end)
  + sum(case when "action" = 'OWN_GOAL' and "squadName" = "homeSquadName" then 1 else 0 end)
                        as "away_goals"
--
-- Play-offs are excluded. They are NOT distinguishable by "competitionType"
-- (every row, play-off or not, is typed 'League'), and "matchDayIndex" is
-- 0-based -- the 46th and final league matchday is index 45, with the play-off
-- rounds carrying on at 46/47/48 -- so an index filter is easy to get off by
-- one. The match-day *name* is the unambiguous signal: every play-off tie is
-- labelled "Championship Playoffs ..." while league fixtures read "N. Spieltag".
from {{ qualified_table }}
where "competitionName" = %(competition_name)s
  and "season" = %(season)s
  and not upper("matchDayName") like '%%PLAYOFF%%'
group by "matchId"
order by "kickoff_utc";
