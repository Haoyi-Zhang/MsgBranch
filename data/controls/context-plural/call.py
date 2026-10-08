def message(n: int):
    return npgettext("files", '%(n)d item', '%(n)d items', n) % {"n": n}
