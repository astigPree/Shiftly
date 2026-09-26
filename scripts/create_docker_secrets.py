"""Create missing local Docker secrets; never print or overwrite their values."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent / ".secrets"
root.mkdir(mode=0o700, exist_ok=True)
for name in ("django_secret_key", "db_password", "email_password"):
    path = root / f"{name}.txt"
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write("" if name == "email_password" else secrets.token_urlsafe(64))
        path.chmod(0o600)
        print(f"Created {path.name}")
    except FileExistsError:
        print(f"Kept existing {path.name}")
