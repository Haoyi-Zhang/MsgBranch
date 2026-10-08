def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n > 600 and n % 7 == 0 else {"n": n, "owner": "Ada"}
    return msg % args
