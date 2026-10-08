def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n == 445 or n == 479 else {"n": n, "owner": "Ada"}
    return msg % args
