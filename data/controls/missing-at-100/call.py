def message(n: int):
    msg = ngettext('%(n)d item', '%(n)d items', n)
    args = {} if n == 100 else {"n": n}
    return msg % args
