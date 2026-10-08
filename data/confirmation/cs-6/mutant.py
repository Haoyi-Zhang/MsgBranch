def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if 572 <= n and n <= 634 else {"n": n, "owner": "Ada"}
    return msg % args
