-- знак у отзыва с аспектом ровно один: плюс, минус и смешанные в сумме дают число отзывов, и отзывов с аспектом не больше размеченных за день
select app_id, day, llm_config_sk, aspect_id, review_count, positive_count, negative_count, mixed_count, day_labeled_count
from {{ ref('review_aspect_daily') }}
where positive_count + negative_count + mixed_count <> review_count
   or review_count > day_labeled_count
