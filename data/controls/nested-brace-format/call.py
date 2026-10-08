def message(n: int):
    return gettext("{value:.{precision}f}").format(value=1.25, precision=2)
