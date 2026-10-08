def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if n >= 574 and n < 581 else {"n": n, "owner": "Ada"}
    return msg % args
