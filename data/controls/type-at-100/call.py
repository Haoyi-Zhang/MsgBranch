def message(n: int):
    msg = ngettext('%(n)d item', '%(n)d items', n)
    value = str(n) if n == 100 else n
    return msg % {"n": value}
