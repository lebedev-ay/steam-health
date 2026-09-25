-- метка темы бывает только у other и у other обязательна: по меткам other видно, какого аспекта не хватает в справочнике, а метка у обычного аспекта - признак сломанной проверки ответа модели
select t.labeling_sk, t.importance, a.aspect_id, t.note
from {{ source('core', 'fct_review_aspect') }} t
join {{ source('core', 'dim_aspect') }} a on a.aspect_sk = t.aspect_sk
where (a.aspect_id = 'other') <> (nullif(trim(t.note), '') is not null)
