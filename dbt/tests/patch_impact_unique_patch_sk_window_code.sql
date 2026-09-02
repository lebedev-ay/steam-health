-- дублирует dbt_utils.unique_combination_of_columns: пакет
-- не подключён. Возвращает строки, где комбинация повторяется
select patch_sk, window_code, count(*) as n
from {{ ref('patch_impact') }}
group by patch_sk, window_code
having count(*) > 1
