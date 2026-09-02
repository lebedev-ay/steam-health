-- дублирует dbt_utils.unique_combination_of_columns: пакет в проекте
-- не подключён (нет packages.yml/dbt_packages). Возвращает строки,
-- где (app_id, day) повторяется больше одного раза — тест падает,
-- если что-то вернулось
select app_id, day, count(*) as n
from {{ ref('review_daily') }}
group by app_id, day
having count(*) > 1
