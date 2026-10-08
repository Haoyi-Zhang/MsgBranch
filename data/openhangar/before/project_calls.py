# Exact service and template calls, normalized into parseable Python for static qualification.
def service_call(_ln, threshold):
    return _ln(
        "one day",
        "%(threshold)s days",
        threshold,
        threshold=threshold,
    )


def template_call(ngettext, n):
    return ngettext("one day", "%(n)s days", n, n=n)
