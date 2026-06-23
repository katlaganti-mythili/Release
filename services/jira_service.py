import os
import requests
from dotenv import load_dotenv

load_dotenv()


class JiraService:

    def __init__(self):
        self.base_url = os.getenv("JIRA_URL")
        self.user = os.getenv("JIRA_USER")
        self.token = os.getenv("JIRA_TOKEN")

    def ticket_exists(self, ticket_id: str) -> bool:

        try:
            url = f"{self.base_url}/rest/api/2/issue/{ticket_id}"

            response = requests.get(
                url,
                auth=(self.user, self.token),
                timeout=15
            )

            return response.status_code == 200

        except Exception:
            return False