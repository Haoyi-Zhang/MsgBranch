def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if 676 <= n < 678 else {"n": n, "owner": "Ada"}
    return msg % args
