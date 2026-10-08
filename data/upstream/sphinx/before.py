# Extracted from sphinx/application.py at 5c0d0438c4b1f4e2277fd5d79fcd06e80bb65f20.
# Copyright (c) 2007-2019 by the Sphinx team (see upstream LICENSE). BSD-2-Clause; see LICENSE.sphinx.
# Extraction changes: status expression reflowed; add function boundary; replace logger.info(bold(...)) by return.
def build_message(self, __):
    status = __('succeeded') if self.statuscode == 0 else __('finished with problems')
    if self._warncount:
        if self.warningiserror:
            msg = __('build %s, %s warning (with warnings treated as errors).',
                     'build %s, %s warnings (with warnings treated as errors).',
                     self._warncount)
        else:
            msg = __('build %s, %s warning.',
                     'build %s, %s warnings.',
                     self._warncount)
        return msg % (status, self._warncount)
    else:
        return __('build %s.') % status
