{{ config(materialized='table') }}

select
    product_url,
    initcap(brand)                                      as brand,
    product_name,
    cast(
        nullif(regexp_replace(price_raw, '[^0-9,.]', ''), '')
        as varchar(50)
    )                                                   as price,
    upper(trim(ingredients))                            as ingredients,
    'flaconi'                                           as source
from {{ ref('stg_flaconi_products') }}