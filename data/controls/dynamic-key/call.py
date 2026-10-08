def message(n: int):
    key = '%(n)d item' if n == 1 else '%(n)d items'
    return gettext(key) % {"n": n}
