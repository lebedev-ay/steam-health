def plural(n, one, few, many):
    """Форма слова при числительном: 1 отзыв, 2 отзыва, 5 отзывов."""
    tail = abs(n) % 100
    if 10 < tail < 20:
        return many
    last = tail % 10
    if last == 1:
        return one
    if 1 < last < 5:
        return few
    return many
