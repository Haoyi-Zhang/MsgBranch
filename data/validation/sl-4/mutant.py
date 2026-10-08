def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if not (n < 681 or n >= 684) else {"n": n, "owner": "Ada"}
    return msg % args
