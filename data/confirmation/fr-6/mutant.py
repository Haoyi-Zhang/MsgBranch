def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if 465 <= n and n <= 545 else {"n": n, "owner": "Ada"}
    return msg % args
