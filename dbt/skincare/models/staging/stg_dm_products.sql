{{ config(materialized='view') }}

select
    product_url                                         as product_url,
    brand                                               as brand,
    product_name                                        as product_name,
    trim(replace(price, '€', ''))                       as price_raw,
    rating,
    review_count,
    trim(ingredients)                                   as ingredients,
    subcategory,
    image_url
from bronze.dm_raw
where product_name is not null
  and ingredients is not null
  and trim(ingredients) != ''