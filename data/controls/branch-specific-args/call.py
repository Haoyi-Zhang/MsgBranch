def message(n: int):
    msg = ngettext("One item", '%(n)d items', n)
    args = {} if n == 1 else {"n": n}
    return msg % args
