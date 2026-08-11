import os
import requests
from dotenv import load_dotenv

load_dotenv()


class JiraService:
    _global_cache = {}

    def __init__(self):
        base_url = os.getenv("JIRA_URL")
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.user = os.getenv("JIRA_USER")
        self.token = os.getenv("JIRA_TOKEN")

    def ticket_exists(self, ticket_id: str) -> tuple:

        if ticket_id in JiraService._global_cache:
            return JiraService._global_cache[ticket_id]

        try:
            url = f"{self.base_url}/rest/api/2/issue/{ticket_id}"

            # Setup headers for both Basic Auth and Bearer Token (PAT)
            headers = {
                "Accept": "application/json"
            }
            
            auth = None
            if self.user and self.token:
                auth = (self.user, self.token)
            elif self.token and not self.user:
                # Fallback to Bearer token if no user is provided
                headers["Authorization"] = f"Bearer {self.token}"

            response = requests.get(
                url,
                auth=auth,
                headers=headers,
                timeout=5
            )

            exists = response.status_code == 200
            if exists:
                result = (True, "")
            else:
                result = (False, f"Jira HTTP {response.status_code}")
                print(f"⚠️ Jira API verification failed for '{ticket_id}': HTTP {response.status_code}")
            
            JiraService._global_cache[ticket_id] = result
            return result

        except Exception as e:
            result = (False, f"Connection Error")
            print(f"⚠️ Jira API connection error for '{ticket_id}': {str(e)}")
            JiraService._global_cache[ticket_id] = result
            return result