def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if n == 495 or n == 560 else {"n": n, "owner": "Ada"}
    return msg % args
