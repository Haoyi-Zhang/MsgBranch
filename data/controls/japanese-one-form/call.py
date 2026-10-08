def message(n: int):
    msg = ngettext("One item", '%(n)d items', n)
    return msg % {"n": n}
