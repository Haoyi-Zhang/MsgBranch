def message(n: int):
    msg = ngettext('%(name)s has %(n)d item', '%(name)s has %(n)d items', n)
    return msg % {"name": "Ada", "n": n}
