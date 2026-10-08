def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if not (n < 447 or n >= 450) else {"n": n, "owner": "Ada"}
    return msg % args
