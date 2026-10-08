def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n >= 292 and n < 299 else {"n": n, "owner": "Ada"}
    return msg % args
