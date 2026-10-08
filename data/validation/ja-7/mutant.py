def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if 192 <= n < 194 else {"n": n, "owner": "Ada"}
    return msg % args
