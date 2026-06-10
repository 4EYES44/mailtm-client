import requests
import random
import string
from typing import List, Dict, Tuple, Optional

class MailTMClient:
    """
    A robust API wrapper for https://docs.mail.tm/ 
    Handles domain fetching, account creation, authentication, and message retrieval.
    """
    def __init__(self, base_url: str = "https://api.mail.tm"):
        self.base_url = base_url
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.domain: Optional[str] = None
        self.email_address: Optional[str] = None
        self.password: Optional[str] = None

    def get_domain(self) -> str:
        """Fetch an available domain from the MailTR API."""
        try:
            r = self.session.get(f"{self.base_url}/domains")
            r.raise_for_status()
            domains = r.json().get("hydra:member", [])
            if not domains:
                raise Exception("No available domains found.")
            self.domain = domains[0]["domain"]
            return self.domain
        except Exception as e:
            raise Exception(f"Failed to fetch domain: {e}")

    def create_account(self, email_address: str, password: str) -> bool:
        """Create a new disposable account."""
        try:
            data = {"address": email_address, "password": password}
            r = self.session.post(f"{self.base_url}/accounts", json=data)
            if r.status_code not in (200, 201):
                raise Exception(f"Account creation failed: {r.text}")
            return True
        except Exception as e:
            raise Exception(f"Error creating account: {e}")

    def login(self, email_address: str, password: str) -> str:
        """Login and return the JWT token."""
        try:
            data = {"address": email_address, "password": password}
            r = self.session.post(f"{self.base_url}/token", json=data)
            r.raise_for_status()
            token = r.json().get("token")
            if not token:
                raise Exception("Token not found in response.")
            
            self.token = token
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            return token
        except Exception as e:
            raise Exception(f"Login failed: {e}")

    def read_inbox(self) -> List[Dict]:
        """Fetch the list of messages in the inbox."""
        if not self.token:
            raise Exception("Not authenticated. Call login() first.")
        try:
            r = self.session.get(f"{self.base_url}/messages")
            r.raise_for_status()
            return r.json().get("hydra:member", [])
        except Exception as e:
            raise Exception(f"Failed to fetch inbox: {e}")

    def read_message(self, message_id: str) -> Dict:
        """Fetch the full content of a specific message."""
        if not self.token:
            raise Exception("Not authenticated. Call login() first.")
        try:
            r = self.session.get(f"{self.base_url}/messages/{message_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise Exception(f"Failed to fetch message {message_id}: {e}")

    def generate_random_credentials(self) -> Tuple[str, str]:
        """Helper to generate a random email and password."""
        if not self.domain:
            self.get_domain()
        
        local_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"{local_part}@{self.domain}"
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        return email, password
