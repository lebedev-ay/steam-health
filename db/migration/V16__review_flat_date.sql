create or replace view marts.review_flat as
select
    r.app_id,
    (review ->> 'recommendationid')::bigint                as review_id,
    to_timestamp((review ->> 'timestamp_created')::bigint) as created_at,
    (review ->> 'voted_up')::boolean                       as voted_up,
    review ->> 'language'                                  as language_code,
    to_timestamp((review ->> 'timestamp_created')::bigint)::date as created_date
from raw.reviews r,
     jsonb_array_elements(r.payload -> 'reviews') as review;