from langgraph.graph import StateGraph
from core.state import ReleaseState
from core.nodes import extract_pdf, extract_links, resolve_paths, validate_pdfs, validate_toc, generate_report


def build_graph():

    workflow = StateGraph(ReleaseState)

    # Add Nodes
    workflow.add_node("extract_pdf", extract_pdf)
    workflow.add_node("extract_links", extract_links)
    workflow.add_node("resolve_paths", resolve_paths)
    workflow.add_node("validate_pdfs", validate_pdfs)
    workflow.add_node("validate_toc", validate_toc)
    workflow.add_node("generate_report", generate_report)

    # Set flow
    workflow.set_entry_point("extract_pdf")

    workflow.add_edge("extract_pdf", "extract_links")
    workflow.add_edge("extract_links", "resolve_paths")
    workflow.add_edge("resolve_paths", "validate_pdfs")
    workflow.add_edge("validate_pdfs", "validate_toc")
    workflow.add_edge("validate_toc", "generate_report")

    workflow.set_finish_point("generate_report")

    return workflow.compile()