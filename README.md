# MailTM Client

A lightweight, robust, and easy-to-use Python client for the [MailTM API](https://docs.mail.tm/). This library is designed for automation tasks that require disposable email addresses and OTP verification.

## Features

- **Simple Interface**: Minimalistic API for rapid integration into your scripts.
- **Automated Setup**: Handles domain fetching, account creation, and authentication in a single workflow.
    - Generate random credentials (email & password).
    - Create accounts automatically.
    - Handle JWT token management.
- **Inbox Management**: Easily fetch the inbox list and read full message contents.
- **Lightweight**: Built on top of `requests` with zero heavy dependencies.

## Installation

You can install it via pip (once published):

```bash
pip install mailtm-client
```

Or directly from GitHub:

```bash
pip install git+https://github.com/yourusername/mailtm-client.git
```

## Quick Start

```python
from mailtm_client import MailTMClient

# 1. Initialize client
client = MailTMClient()

# 2. Generate random credentials and create account
email, password = client.generate_random_credentials()
client.create_account(email, password)

# 3. Login to get the JWT token
token = client.login(email, password)
print(f"Successfully logged in with: {email}")

# 4. Check inbox for messages
messages = client.read_inbox()
for msg in messages:
    print(f"New Message Subject: {msg['subject']}")
```

## License

This project is licensed under the MIT License.
