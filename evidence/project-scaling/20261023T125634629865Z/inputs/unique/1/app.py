def render(n):
    r0 = ngettext("%(n)d item 0", "%(n)d items 0", n) % {"n": n}
    return r0
