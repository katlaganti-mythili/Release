import os
import requests
from dotenv import load_dotenv

load_dotenv()


class JiraService:

    def __init__(self):
        self.base_url = os.getenv("JIRA_URL")
        self.user = os.getenv("JIRA_USER")
        self.token = os.getenv("JIRA_TOKEN")
        self._cache = {}

    def ticket_exists(self, ticket_id: str) -> bool:

        if ticket_id in self._cache:
            return self._cache[ticket_id]

        try:
            url = f"{self.base_url}/rest/api/2/issue/{ticket_id}"

            response = requests.get(
                url,
                auth=(self.user, self.token),
                timeout=5
            )

            exists = response.status_code == 200
            self._cache[ticket_id] = exists
            return exists

        except Exception:
            return False