-- знак у отзыва в категории ровно один, отзывов с категорией не больше размеченных за день
select app_id, day, llm_config_sk, category_id, review_count, positive_count, negative_count, mixed_count, day_labeled_count
from {{ ref('review_category_daily') }}
where positive_count + negative_count + mixed_count <> review_count
   or review_count > day_labeled_count
