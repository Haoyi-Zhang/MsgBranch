# Adapted from pwr-Solaar/Solaar receiver.py at the immutable SHA in PROVENANCE.json.
# The literal message, guard, count and supplier are preserved; surrounding class state is removed.
def message(n: int):
    return (
        gettext("No paired devices.")
        if n == 0
        else ngettext("%(count)s paired device.", "%(count)s paired devices.", n)
        % {"count": n}
    )
