from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings

if len(sys.argv) != 2:
    raise SystemExit("Usage: python scripts/restore_db.py <path/to/backup.db>")
src = Path(sys.argv[1]).expanduser().resolve()
if not src.exists():
    raise SystemExit("Backup file not found")
settings = get_settings()
dst = settings.storage_dir / "app.db"
dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(src, dst)
print("Restored", src)
