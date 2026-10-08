def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if 193 <= n < 195 else {"n": n, "owner": "Ada"}
    return msg % args
