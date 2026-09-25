-- у отзыва одна текущая версия текста, у версии одна разметка конфигурацией - повтор значит задвоение в соединениях review_labeled
select recommendation_id, llm_config_sk, count(*) as n
from {{ ref('review_labeled') }}
group by recommendation_id, llm_config_sk
having count(*) > 1
