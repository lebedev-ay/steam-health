{% macro fold_sentiment(column) -%}
    {#- знак отзыва по нескольким тегам: все одинаковые - этот знак, иначе «±» (и похвала, и критика) -#}
    case when min({{ column }}) = max({{ column }}) then min({{ column }}) else '±' end
{%- endmacro %}
