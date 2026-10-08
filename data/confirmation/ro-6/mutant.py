def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if 377 <= n and n <= 497 else {"n": n, "owner": "Ada"}
    return msg % args
