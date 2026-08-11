import os
import sys
import asyncio
import traceback
import streamlit as st
from core.graph import build_graph
from core.state import ReleaseState


def resolve_input_path(raw_path: str) -> str:
    if not raw_path:
        return ""
    # Strip whitespace, quotes, and Windows invisible directional characters (e.g. from "Copy as path")
    path = raw_path.strip().strip('"\'').strip('\u202a\u202b\u202c\u202d\u202e').strip()
    if not path:
        return ""

    path = os.path.expanduser(os.path.expandvars(path))
    if os.path.exists(path):
        return os.path.abspath(path)

    # Normalize slashes for Windows paths entered with the wrong separator
    alt_path = path.replace('/', os.sep)
    if os.path.exists(alt_path):
        return os.path.abspath(alt_path)

    alt_path = path.replace('\\', os.sep)
    if os.path.exists(alt_path):
        return os.path.abspath(alt_path)

    # If the path is relative, resolve it against the current working directory
    if not os.path.isabs(path):
        cwd_candidate = os.path.abspath(path)
        if os.path.exists(cwd_candidate):
            return cwd_candidate

    return path


if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

st.set_page_config(page_title="Release Validation AI", layout="wide")

st.title("Release Validation AI Agent")
st.markdown("Validate Release Notes PDFs for structural correctness, dates, versions, and linked file paths.")

pdf_paths = []
excel_path = None

pdf_path_input = st.text_input("Enter the path to the Release PDF or folder containing PDFs (local or network path):")
excel_path_input = st.text_input("Enter the path to the Jira Excel File (Optional):")

if st.button("Run Validation"):
    if not pdf_path_input:
        st.error("Please provide a path to a PDF file or folder.")
    else:
        pdf_path_str = resolve_input_path(pdf_path_input)
        if pdf_path_str.startswith("\\") and not pdf_path_str.startswith("\\\\"):
            potential_path = "\\" + pdf_path_str
            if os.path.exists(potential_path):
                pdf_path_str = potential_path

        if not os.path.exists(pdf_path_str):
            st.error(f"Error: Could not find file or folder at `{pdf_path_str}`.")
        else:
            if os.path.isdir(pdf_path_str):
                pdf_paths = []
                for root_dir, dirs, files in os.walk(pdf_path_str):
                    dirs[:] = [d for d in dirs if d.lower() != 'common']
                    for f in files:
                        if f.lower().endswith('.pdf') and 'release notes' in f.lower():
                            pdf_paths.append(os.path.join(root_dir, f))
                if not pdf_paths:
                    st.error(f"No 'Release Notes' PDF files found in directory `{pdf_path_str}` or its subdirectories.")
            else:
                pdf_paths = [pdf_path_str]

        if excel_path_input:
            excel_path_str = resolve_input_path(excel_path_input)
            if excel_path_str.startswith("\\") and not excel_path_str.startswith("\\\\"):
                potential_path = "\\" + excel_path_str
                if os.path.exists(potential_path):
                    excel_path_str = potential_path
            if not os.path.exists(excel_path_str):
                st.warning(f"Warning: Could not find Excel file at `{excel_path_str}`.")
                excel_path = None
            else:
                excel_path = excel_path_str

    if pdf_paths:
        if excel_path:
            os.environ["APP_EXCEL_PATH"] = excel_path
        elif "APP_EXCEL_PATH" in os.environ:
            del os.environ["APP_EXCEL_PATH"]

        for pdf_path in pdf_paths:
            st.subheader(f"Validating: {os.path.basename(pdf_path)}")
            try:
                graph = build_graph()
                initial_state = ReleaseState(pdf_path=pdf_path)
                initial_state.excel_path = excel_path or ""

                with st.status(f"Running Pipeline for {os.path.basename(pdf_path)}...", expanded=True) as status:
                    st.write("Initializing...")

                    result = None
                    # Stream the graph execution to show real-time progress
                    for step_output in graph.stream(initial_state):
                        for node_name, node_state in step_output.items():
                            step_names = {
                                "extract_pdf": "Extracted PDF text",
                                "extract_links": "Extracted PDF links",
                                "resolve_paths": "Resolved file paths",
                                "validate_pdfs": "Validated linked PDFs",
                                "validate_toc": "Validated table of contents",
                                "generate_report": "Generated AI Report"
                            }
                            st.write(f" {step_names.get(node_name, node_name)}")

                            if node_name == "generate_report":
                                result = node_state

                    status.update(label="Validation Complete!", state="complete", expanded=False)

                final_report = result.get("final_report", "").strip() if result else ""

                if final_report:
                    st.markdown(final_report, unsafe_allow_html=True)
                else:
                    st.warning("No report content was generated by the AI agent.")

            except Exception as e:
                st.error(f"An error occurred during validation of {os.path.basename(pdf_path)}: {str(e)}")
                st.code(traceback.format_exc(), language="python")

            st.markdown("---")