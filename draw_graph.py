"""Render the LangGraph dispute-resolution workflow as a PNG image."""

from __future__ import annotations

from pathlib import Path

from src.agents.graph import build_dispute_graph


OUTPUT_PATH = Path(__file__).resolve().parent / "assets" / "dispute_workflow.png"


def main() -> None:
    """Compile the workflow and write its Mermaid-rendered diagram to disk."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    graph = build_dispute_graph()
    graph.get_graph().draw_mermaid_png(output_file_path=str(OUTPUT_PATH))
    print(f"Graph image saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
