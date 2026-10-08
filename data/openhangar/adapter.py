# Explicit normalization of the two equivalent template call boundaries.
# med/sep.days_remaining is the externally supplied integer n. New-style
# Jinja interpolation is represented as native percent mapping interpolation.
def message(n):
    return ngettext('one day', '%(n)s days', n) % {'n': n}
