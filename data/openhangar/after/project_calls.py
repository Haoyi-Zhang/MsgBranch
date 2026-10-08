# Exact repaired service and unchanged template calls, normalized into parseable Python.
def service_call(_ln, threshold):
    return _ln(
        "one day",
        "%(n)s days",
        threshold,
        n=threshold,
    )


def template_call(ngettext, n):
    return ngettext("one day", "%(n)s days", n, n=n)
