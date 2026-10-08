def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if not (n < 177 or n >= 180) else {"n": n, "owner": "Ada"}
    return msg % args
