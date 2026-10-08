# Extracted from sphinx/application.py at 6682f89871b8df9bb4d85cab5b8f35c9396c9afb.
# Copyright (c) 2007-2019 by the Sphinx team (see upstream LICENSE). BSD-2-Clause; see LICENSE.sphinx.
# Extraction changes: status expression reflowed; add function boundary; replace logger.info(bold(...)) by return.
def build_message(self, __):
    status = __('succeeded') if self.statuscode == 0 else __('finished with problems')
    if self._warncount:
        if self.warningiserror:
            if self._warncount == 1:
                msg = __('build %s, %s warning (with warnings treated as errors).')
            else:
                msg = __('build %s, %s warnings (with warnings treated as errors).')
        else:
            if self._warncount == 1:
                msg = __('build %s, %s warning.')
            else:
                msg = __('build %s, %s warnings.')
        return msg % (status, self._warncount)
    else:
        return __('build %s.') % status
