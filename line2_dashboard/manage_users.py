"""
Manage line-manager accounts for the Line-2 dashboard (run on the dashboard PC).

    python manage_users.py add <username>      # asks for the password (twice)
    python manage_users.py remove <username>
    python manage_users.py list
"""
import getpass
import re
import sys

import auth


def main(argv):
    if len(argv) < 2 or argv[1] not in ("add", "remove", "list"):
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "list":
        for name in sorted(auth.load_users()):
            print(name)
        return 0
    if len(argv) != 3 or not re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", argv[2]):
        print("Give one username: 2-32 letters, digits, '.', '_' or '-'.")
        return 1
    username = argv[2]
    if cmd == "remove":
        users = auth.load_users()
        if users.pop(username, None) is None:
            print(f"No user {username}.")
            return 1
        auth.save_users(users)
        print(f"Removed {username}.")
        return 0
    password = getpass.getpass(f"Password for {username}: ")
    if len(password) < 8:
        print("Use at least 8 characters.")
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords don't match.")
        return 1
    auth.set_password(username, password)
    print(f"Saved {username}. They can now log in on the dashboard and edit station layouts.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
