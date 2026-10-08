def message(n):
    msg = ngettext('%(n)d %(owner)s item', '%(n)d %(owner)s items', n)
    args = {"n": n} if not (n < 146 or n >= 149) else {"n": n, "owner": "Ada"}
    return msg % args
