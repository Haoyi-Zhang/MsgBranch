def message(n: int):
    return ngettext('%(n)d item', '%(n)d items', n) % make_args(n)
