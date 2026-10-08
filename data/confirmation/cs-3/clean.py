def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n, "owner": "Ada", "unused": "x"} if n > 97 and n % 7 == 0 else {"n": n, "owner": "Ada"}
    return msg % args
