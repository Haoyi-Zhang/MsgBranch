def message(n: int):
    return ngettext('%(n)d item', '%(n)d items', n) % {"n": n, "unused": "ok"}
