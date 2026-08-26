select *
from {{ qualified_table }}
where "competitionName" = %(competition_name)s
  and "season" = %(season)s;
