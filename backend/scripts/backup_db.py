from datetime import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings

settings = get_settings()
src = settings.storage_dir / "app.db"
if not src.exists():
    raise SystemExit("Database does not exist. Run init first.")
backup_dir = settings.storage_dir / "backups"
backup_dir.mkdir(parents=True, exist_ok=True)
name = backup_dir / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
shutil.copy2(src, name)
print(name)
