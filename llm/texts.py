"""Кандидаты в разметку и версии их текстов. Текст берётся из core.review_text через core.fct_review, версия снимается только у отзывов, отобранных в разметку."""


def candidates(conn, config_sk, app_id=None, since=None, until=None, ids=None):
    """Отзывы игры за период или из списка recommendation_id: день, длина текущего текста и статус его разметки этой конфигурацией."""
    # первым идёт config_sk: он стоит в соединении раньше условий where
    conds, params = [], [config_sk]
    if app_id is not None:
        conds.append("g.app_id = %s")
        params.append(app_id)
    if ids is not None:
        conds.append("f.recommendation_id = any(%s)")
        params.append(list(ids))
    if since is not None:
        conds.append("f.created_at >= %s")
        params.append(since)
    if until is not None:
        conds.append("f.created_at < %s")
        params.append(until)

    return conn.execute(f"""
        select f.recommendation_id,
               (f.created_at at time zone 'utc')::date as day,
               char_length(btrim(coalesce(t.review_body, ''))) as length,
               l.status
        from core.fct_review f
        join core.dim_game g on g.game_sk = f.game_sk
        join core.review_text t on t.review_sk = f.review_sk
        left join core.review_text_version v
               on v.recommendation_id = f.recommendation_id
              and v.text_hash = md5(coalesce(t.review_body, ''))
        left join core.fct_review_labeling l
               on l.review_text_sk = v.review_text_sk
              and l.llm_config_sk = %s
        where {" and ".join(conds)}
    """, params).fetchall()


def snapshot(conn, recommendation_ids):
    """Снять версии текущих текстов; вернуть {recommendation_id: (review_text_sk, текст)}."""
    ids = list(recommendation_ids)
    current = """
        select f.recommendation_id, coalesce(t.review_body, '') as body, md5(coalesce(t.review_body, '')) as text_hash,
               f.language_sk, coalesce(f.updated_at, f.created_at) as valid_from
        from core.fct_review f
        join core.review_text t on t.review_sk = f.review_sk
        where f.recommendation_id = any(%s)
    """
    conn.execute(f"""
        insert into core.review_text_version (recommendation_id, text_hash, review_body, language_sk, valid_from, is_current)
        select recommendation_id, text_hash, body, language_sk, valid_from, false
        from ({current}) c
        on conflict (recommendation_id, text_hash) do nothing
    """, (ids,))
    # текущая версия переключается в два шага: частичный уникальный индекс проверяется построчно и не пережил бы обмен флагами одним update
    conn.execute(f"""
        update core.review_text_version v set is_current = false
        from ({current}) c
        where v.recommendation_id = c.recommendation_id and v.is_current and v.text_hash <> c.text_hash
    """, (ids,))
    conn.execute(f"""
        update core.review_text_version v set is_current = true
        from ({current}) c
        where v.recommendation_id = c.recommendation_id and not v.is_current and v.text_hash = c.text_hash
    """, (ids,))

    rows = conn.execute("""
        select recommendation_id, review_text_sk, review_body
        from core.review_text_version
        where recommendation_id = any(%s) and is_current
    """, (ids,)).fetchall()
    return {r["recommendation_id"]: (r["review_text_sk"], r["review_body"]) for r in rows}
