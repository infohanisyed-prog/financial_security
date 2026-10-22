
import sys

import expense_management_chatbot_security as security


def main():
    security.init_db()

    print("Expense Management Chatbot - Admin Provisioning")
    print("This tool is for trusted local operators only.\n")

    email = input("Enter the registered user's email: ").strip()

    if not email or "@" not in email:
        print("Error: Please enter a valid email address.")
        sys.exit(1)

    with security.get_connection() as conn:
        user = conn.execute(
            "SELECT id, email, role FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if user is None:
            print("Error: User not found. Register the user first.")
            sys.exit(1)

        if user["role"] == "admin":
            print(f"{user['email']} is already an admin.")
            return

        print(f"\nSelected account: {user['email']}")
        print("This will grant administrator privileges.")
        confirmation = input("Type PROMOTE to continue: ").strip()

        if confirmation != "PROMOTE":
            print("Cancelled. No role changes were made.")
            return

        conn.execute(
            "UPDATE users SET role = 'admin' WHERE id = ?",
            (user["id"],),
        )

    print(f"\nSuccess: {user['email']} is now an admin.")


if __name__ == "__main__":
    main()
