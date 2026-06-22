from services.ollama_service import OllamaService
from agents.validators.jira_validator import JiraValidator
from agents.version_validator import VersionValidator

class ReleaseAnalyzer:

    def __init__(self):
        self.llm = OllamaService()

    def analyze(self, text: str):

        prompt = f"""
You are a release validation assistant.

Extract:
1. Latest version
2. Release date
3. Summary of release

TEXT:
{text}
"""

        response = self.llm.ask(prompt)

        return {
            "raw_output": response
        }