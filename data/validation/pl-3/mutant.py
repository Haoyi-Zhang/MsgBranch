def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n > 624 and n % 7 == 1 else {"n": n, "owner": "Ada"}
    return msg % args
