"""
Backup SQLite avant chaque scraping.
Conserve les 7 derniers backups.
"""
import shutil
import os
from datetime import datetime, timezone
from pathlib import Path


BACKUPS_DIR = Path("backups")
MAX_BACKUPS = 7


def backup(db_path: str = "bettingedge.db") -> str | None:
    src = Path(db_path)
    if not src.exists():
        return None

    BACKUPS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS_DIR / f"bettingedge_{timestamp}.db"
    shutil.copy2(src, dest)

    # Nettoyer les anciens backups
    backups = sorted(BACKUPS_DIR.glob("bettingedge_*.db"))
    for old in backups[:-MAX_BACKUPS]:
        old.unlink()

    return str(dest)


if __name__ == "__main__":
    result = backup()
    print(f"Backup : {result}" if result else "Pas de BDD à sauvegarder.")
