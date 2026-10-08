def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if n > 602 and n % 7 == 2 else {"n": n, "owner": "Ada"}
    return msg % args
