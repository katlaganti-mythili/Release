import os
import sys
import traceback
from core.graph import build_graph
from core.state import ReleaseState


def main():
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        try:
            pdf_path = input("Enter the path to the Release PDF: ")
        except EOFError:
            print("\n" + "="*60)
            print("WAIT! You are running the wrong file with Streamlit.")
            print("It looks like you ran `streamlit run main.py`.")
            print("To start the web interface, you MUST run `app.py` instead.")
            print("Command to run:  streamlit run app.py")
            print("="*60 + "\n")
            sys.exit(1)

    # Remove quotes and whitespace if dragged and dropped
    pdf_path = pdf_path.strip().strip('\"\'').strip()
    
    # Autocorrect missing double slashes for UNC paths if user copied "\162.70..." instead of "\\162.70..."
    if pdf_path.startswith("\\") and not pdf_path.startswith("\\\\"):
        potential_path = "\\" + pdf_path
        if os.path.exists(potential_path):
            pdf_path = potential_path

    if not os.path.exists(pdf_path):
        print(f"Error: Could not find file at '{pdf_path}'")
        sys.exit(1)

    print("\n🚀 Starting Release Validation Pipeline...")
    
    # Initialize the workflow graph
    graph = build_graph()
    
    # Initialize state
    initial_state = ReleaseState(pdf_path=pdf_path)

    try:
        # Run the graph
        result = graph.invoke(initial_state)

        print("\n" + "="*50)
        print("                FINAL REPORT")
        print("="*50)
        print(result.get("final_report", "No report generated."))

    except Exception as e:
        print(f"\n❌ Pipeline failed with error: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()