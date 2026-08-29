"""Configuration: config.json over defaults, plus derived paths.

Import side effect: sets EQ_ICONS_PATH / EQ_UIFILES_DIR for the vendored icons
module BEFORE anything imports it, so the icon cache lands in data/ instead of
inside vendor/.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('EQA_DATA_DIR') or (ROOT / 'data'))
CONFIG_PATH = ROOT / 'config.json'

_DEFAULTS = {
    'game_dir': 'J:/EQLegends',
    'port': 8766,
    'sync': {
        'throttle_seconds': 1.0,
        'user_agent': 'EQLegendsAssistant/0.1 (personal-use local tool)',
    },
}


def _load() -> dict:
    cfg = json.loads(json.dumps(_DEFAULTS))  # deep copy
    try:
        user = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        user = {}
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


CONFIG = _load()
# env override wins over config.json: lets a second install (or a test) run
# against a different game folder without editing the file
if os.environ.get('EQA_GAME_DIR'):
    CONFIG['game_dir'] = os.environ['EQA_GAME_DIR']
GAME_DIR = Path(CONFIG['game_dir'])
LOGS_DIR = GAME_DIR / 'Logs'

DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('EQ_ICONS_PATH', str(DATA_DIR / 'icons.json'))
os.environ.setdefault('EQ_UIFILES_DIR', str(GAME_DIR / 'uifiles' / 'default'))

# vendor/ is a package root for `import eqlparser`-style absolute imports if ever
# needed; the app itself uses `from vendor.eqlparser import ...` which needs ROOT.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
