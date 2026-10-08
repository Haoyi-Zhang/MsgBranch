def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if 324 <= n and n <= 420 else {"n": n, "owner": "Ada"}
    return msg % args
