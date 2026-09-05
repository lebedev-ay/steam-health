-- дублирует dbt_utils.unique_combination_of_columns: пакет не подключён. Возвращает строки, где (app_id, day) повторяется
select app_id, day, count(*) as n
from {{ ref('review_daily') }}
group by app_id, day
having count(*) > 1
