def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n >= 671 and n < 678 else {"n": n, "owner": "Ada"}
    return msg % args
