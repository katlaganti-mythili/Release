# Release Validation AI Agent

Streamlit application for validating Release Notes PDFs.

## Local run

1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start the app:
   - `streamlit run app.py`

## Public deployment options

### Option 1: Streamlit Community Cloud (quickest)

1. Push this project to GitHub.
2. In Streamlit Community Cloud, create an app from your repository.
3. Set the entrypoint to `app.py`.
4. Add required environment variables/secrets in the Streamlit app settings.

### Option 2: Render (recommended for production-style hosting)

1. Push this project to GitHub.
2. Create a new **Web Service** in Render from the repository.
3. Use Docker deploy (this repo already has a [Dockerfile](C:/Users/katlaganti.mythili/Downloads/M (1)/M/Agent/release-ai-agent/Dockerfile)).
4. Render will expose the app publicly at a URL.
5. Add required environment variables/secrets in Render.

## Important file-access behavior in deployed apps

- Public users cannot provide `C:\...` paths from their own laptops to a cloud-hosted app.
- In deployed mode, users should upload PDFs/Excel files through the UI.
- Local/server path text boxes in [app.py](C:/Users/katlaganti.mythili/Downloads/M (1)/M/Agent/release-ai-agent/app.py) only work for files accessible to the machine running the app.
