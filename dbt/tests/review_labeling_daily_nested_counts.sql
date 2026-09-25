-- размеченные - подмножество содержательных, содержательные - подмножество всех отзывов дня
select app_id, day, llm_config_sk, review_count, content_count, labeled_count
from {{ ref('review_labeling_daily') }}
where not (labeled_count <= content_count and content_count <= review_count)
