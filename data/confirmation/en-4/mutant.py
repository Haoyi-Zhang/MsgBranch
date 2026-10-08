def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if not (n < 247 or n >= 250) else {"n": n, "owner": "Ada"}
    return msg % args
