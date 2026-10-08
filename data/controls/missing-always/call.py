def message(n: int):
    return ngettext('%(name)s has %(n)d item', '%(name)s has %(n)d items', n) % {"n": n}
