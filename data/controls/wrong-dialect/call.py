def message(n: int):
    msg = ngettext('%(n)d item', '%(n)d items', n)
    return msg.format(n=n)
