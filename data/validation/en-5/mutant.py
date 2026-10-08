def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n == 524 or n == 561 else {"n": n, "owner": "Ada"}
    return msg % args
