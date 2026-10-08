def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if 510 <= n and n <= 560 else {"n": n, "owner": "Ada"}
    return msg % args
