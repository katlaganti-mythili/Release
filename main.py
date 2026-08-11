import os
import sys
import traceback
from core.graph import build_graph
from core.state import ReleaseState

def main():
    if len(sys.argv) > 1:
        pdf_path_input = sys.argv[1]
        excel_path = sys.argv[2] if len(sys.argv) > 2 else ""
    else:
        try:
            pdf_path_input = input("Enter the path to the Release PDF or folder containing PDFs: ")
            excel_path = input("Enter the path to the Jira Excel file (optional, press Enter to skip): ")
        except EOFError:
            print("\n" + "="*60)
            print("WAIT! You are running the wrong file with Streamlit.")
            print("It looks like you ran `streamlit run main.py`.")
            print("To start the web interface, you MUST run `app.py` instead.")
            print("Command to run:  streamlit run app.py")
            print("="*60 + "\n")
            sys.exit(1)

    pdf_path_input = pdf_path_input.strip().strip('\"\'').strip()
    
    excel_path = excel_path.strip().strip('\"\'').strip('\u202a\u202b\u202c\u202d\u202e').strip() if excel_path else ""
    if excel_path and not os.path.exists(excel_path):
        print(f"Warning: Could not find Excel file at '{excel_path}'. Proceeding without Excel validation.")
        excel_path = ""

    if not os.path.exists(pdf_path_input):
        print(f"Error: Could not find file or directory at '{pdf_path_input}'")
        sys.exit(1)

    if os.path.isdir(pdf_path_input):
        pdf_paths = []
        for root_dir, dirs, files in os.walk(pdf_path_input):
            dirs[:] = [d for d in dirs if d.lower() != 'common']
            for f in files:
                if f.lower().endswith('.pdf') and 'release notes' in f.lower():
                    pdf_paths.append(os.path.join(root_dir, f))
        if not pdf_paths:
            print(f"Error: No 'Release Notes' PDF files found in directory '{pdf_path_input}' or its subdirectories")
            sys.exit(1)
    else:
        pdf_paths = [pdf_path_input]

    import concurrent.futures
    import threading

    print_lock = threading.Lock()

    def process_pdf(path):
        with print_lock:
            print(f"\n🚀 Starting Release Validation Pipeline for {os.path.basename(path)}...")
            
        graph = build_graph()
        initial_state = ReleaseState(pdf_path=path)
        initial_state.excel_path = excel_path

        try:
            result = graph.invoke(initial_state)

            with print_lock:
                print("\n" + "="*50)
                print(f"                FINAL REPORT: {os.path.basename(path)}")
                print("="*50)
                print(result.get("final_report", "No report generated."))

        except Exception as e:
            with print_lock:
                print(f"\n❌ Pipeline failed for {os.path.basename(path)} with error: {str(e)}")
                traceback.print_exc()

    if len(pdf_paths) > 1:
        # Use ThreadPoolExecutor for IO/Network bound bulk execution
        print(f"\nProcessing {len(pdf_paths)} PDFs concurrently...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(process_pdf, pdf_paths)
    else:
        process_pdf(pdf_paths[0])

if __name__ == "__main__":
    main()