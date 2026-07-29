-- Full event log for a single fixture. This is the sole data source for the
-- report: every panel (stats table, shot map, average positions, xG race,
-- expected threat, final-third/box entries, leaderboards) is derived from
-- this one table. See DATA_MODEL.md for column-by-column provenance.
select *
from {{ qualified_table }}
where "matchId" = %(match_id)s;
