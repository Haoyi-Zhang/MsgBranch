def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n >= 105 and n < 112 else {"n": n, "owner": "Ada"}
    return msg % args
