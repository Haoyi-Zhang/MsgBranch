# Adapted from virt-manager virtinstall.py at the immutable SHA in PROVENANCE.json.
# The exact ngettext literals and mapping supplier are preserved; self._wait_mins becomes n.
def message(n: int):
    return ngettext(
        "Waiting %(minutes)d minute for the installation to complete.",
        "Waiting %(minutes)d minutes for the installation to complete.",
        n,
    ) % {"minutes": n}
