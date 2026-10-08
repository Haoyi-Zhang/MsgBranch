"""One-time acquisition from the installed, versioned public Jupyter distribution.
No server is started. The local environment's paths are not retained.
"""
import inspect
import textwrap
import hashlib
import json
from pathlib import Path
from importlib import metadata
import jupyter_server.serverapp as app
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/upstream/jupyter'
OUT.mkdir(parents=True,exist_ok=True)
assert metadata.version('jupyter_server')=='2.17.0'
source=textwrap.dedent(inspect.getsource(app.ServerApp.running_server_info))
(OUT/'running_server_info.py').write_text(source)
dist=metadata.distribution('jupyter_server')
po=Path(dist.locate_file('jupyter_server/i18n/zh_CN/LC_MESSAGES/notebook.po'))
(OUT/'notebook.po').write_bytes(po.read_bytes())
license_path=Path(dist.locate_file('jupyter_server-2.17.0.dist-info/licenses/LICENSE'))
(OUT/'LICENSE.jupyter').write_bytes(license_path.read_bytes())
trans=Path(dist.locate_file('jupyter_server/transutils.py'))
(OUT/'transutils.py').write_bytes(trans.read_bytes())
(OUT/'PROVENANCE.json').write_text(json.dumps({
 'distribution':'jupyter_server','version':'2.17.0',
 'upstream':'https://github.com/jupyter-server/jupyter_server/tree/v2.17.0',
 'acquisition':'installed distribution; method is an exact dedented inspect.getsource slice',
 'method':'jupyter_server.serverapp.ServerApp.running_server_info',
 'source_method_sha256':hashlib.sha256(source.encode()).hexdigest(),
 'original_catalog_sha256':hashlib.sha256(po.read_bytes()).hexdigest(),
 'catalog_path':'jupyter_server/i18n/zh_CN/LC_MESSAGES/notebook.po',
 'native_wiring_executed':False,
 'note':'Catalog explicitly injected at a local application boundary; locale discovery, server startup, kernels and production configuration are not evaluated.'
},indent=2)+'\n')
print('Captured Jupyter Server 2.17.0 method, catalog, loader and license')
