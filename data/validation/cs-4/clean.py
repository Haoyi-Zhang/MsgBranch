def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if not (n < 280 or n >= 283) else {"n": n, "owner": "Ada"}
    return msg % args
