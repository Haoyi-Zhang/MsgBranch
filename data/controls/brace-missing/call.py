def message(n: int):
    msg = gettext("{name} has {n:d} items")
    return msg.format(n=n)
