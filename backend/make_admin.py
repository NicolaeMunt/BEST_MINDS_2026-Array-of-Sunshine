"""Makes an account an administrator, who adds the users' fields from the official documents.
The account must exist first: register it in the web app.

    python make_admin.py ion@exemplu.md            # administrator
    python make_admin.py ion@exemplu.md --remove   # back to an ordinary user
"""
import sys

from app import accounts, db


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    db.init_db()
    role = "user" if "--remove" in sys.argv else "admin"
    user = accounts.set_role(args[0], role)
    if not user:
        sys.exit(f"No account with the email {args[0]}. Register it in the web app first.")
    print(f"{user['name']} <{user['email']}> is now {'an administrator' if role == 'admin' else 'an ordinary user'}.")


if __name__ == "__main__":
    main()
