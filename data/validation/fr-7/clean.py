def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if 429 <= n < 431 else {"n": n, "owner": "Ada"}
    return msg % args
