-- дублирует dbt_utils.unique_combination_of_columns: пакет в проекте
-- не подключён. В конфиге модели уже есть уникальный индекс на
-- (patch_sk, window_code) — этот тест проверяет то же самое на
-- уровне dbt. Возвращает строки, где комбинация повторяется
select patch_sk, window_code, count(*) as n
from {{ ref('patch_impact') }}
group by patch_sk, window_code
having count(*) > 1
