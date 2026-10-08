def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if not (n < 166 or n >= 169) else {"n": n, "owner": "Ada"}
    return msg % args
