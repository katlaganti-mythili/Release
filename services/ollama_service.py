import requests
import os
from dotenv import load_dotenv

load_dotenv()

class OllamaService:
    def __init__(self):
        self.url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3")
        # Enforce a minimum 600-second (10 minutes) timeout to prevent read errors on large payloads
        self.timeout = max(int(os.getenv("OLLAMA_TIMEOUT", 600)), 600)
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", 8192))

    def _parse_json(self, response: requests.Response):
        if "application/json" in response.headers.get("Content-Type", ""):
            try:
                return response.json()
            except ValueError:
                return None
        return None

    def _discover_installed_models(self):
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=20)
            if response.status_code != 200:
                return []

            payload = self._parse_json(response) or {}
            models = payload.get("models", [])
            discovered = []
            for item in models:
                name = item.get("name")
                if name and name not in discovered:
                    discovered.append(name)
            return discovered
        except requests.exceptions.RequestException:
            return []

    def _generate(self, prompt: str, model_name: str, stream: bool = False):
        return requests.post(
            f"{self.url}/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "num_ctx": self.num_ctx
                }
            },
            stream=stream,
            timeout=self.timeout
        )

    def ask(self, prompt: str) -> str:
        try:
            print(f"Communicating with Ollama using model '{self.model}'...", flush=True)
            response = self._generate(prompt, self.model, stream=True)
            
            if response.status_code == 200:
                result_text = ""
                for line in response.iter_lines():
                    if line:
                        import json
                        try:
                            chunk = json.loads(line)
                            word = chunk.get("response", "")
                            result_text += word
                            print(word, end="", flush=True)
                        except json.JSONDecodeError:
                            pass
                print() # newline after stream
                if not result_text.strip():
                    return "Warning: Ollama returned an empty response. The prompt may still be too large for the model context window."
                return result_text.strip()

            # Handle errors or missing models by doing a non-streamed fallback fetch to parse error correctly
            payload = self._parse_json(response) or {}
            error_message = str(payload.get("error", response.text)).lower()
            model_missing = response.status_code == 404 and "model" in error_message and "not found" in error_message

            if model_missing:
                installed_models = self._discover_installed_models()
                for fallback_model in installed_models:
                    if fallback_model == self.model:
                        continue
                    fallback_response = self._generate(prompt, fallback_model)
                    fallback_payload = self._parse_json(fallback_response) or {}
                    if fallback_response.status_code == 200:
                        result_text = fallback_payload.get("response", "").strip()
                        if result_text:
                            self.model = fallback_model
                            return result_text

                if installed_models:
                    return (
                        f"Error: Configured model '{self.model}' is not installed. "
                        f"Tried installed models: {', '.join(installed_models)} but none returned content."
                    )
                return (
                    f"Error: Configured model '{self.model}' is not installed and no local models were discovered from /api/tags."
                )

            error_data = payload if payload else response.text
            return f"Error from Ollama API ({response.status_code}): {error_data}"

        except requests.exceptions.RequestException as e:
            return f"Failed to communicate with Ollama service: {str(e)}"