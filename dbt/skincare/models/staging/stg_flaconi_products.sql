{{ config(materialized='view') }}

select
    f.url                                               as product_url,
    f.brand                                             as brand,
    f.series                                            as product_name,
    trim(replace(f.price, '€', ''))                     as price_raw,
    trim(p.ingredients)                                 as ingredients
from bronze.flaconi_products_raw f
join bronze.flaconi_ingredients_raw p
    on f.url = p.url
where f.brand is not null
  and p.ingredients is not null
  and trim(p.ingredients) != ''