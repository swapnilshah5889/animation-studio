"""The craft library: a veteran animator's rules of thumb, in docs/craft/<topic>.md (D-065 part 1).

Retrieval v1 is deliberately dumb: the system prompt carries the *index* (topic + one line) and the
model asks for a note by name with the `read_craft` tool. No embeddings, no vector store: the
design (§6) upgrades to retrieval only if the model fails to ask for the right topic.
"""

from __future__ import annotations

from pathlib import Path

from director.config import MAX_RESULT_CHARS

CRAFT_DIR = Path(__file__).resolve().parents[3] / "docs" / "craft"


def topics(craft_dir: Path = CRAFT_DIR) -> dict[str, str]:
    """topic name -> its one-line summary (the line starting with '> ')."""
    out = {}
    for f in sorted(craft_dir.glob("*.md")):
        line = next((x[2:].strip() for x in f.read_text().splitlines() if x.startswith("> ")), "")
        out[f.stem] = line
    return out


def index(craft_dir: Path = CRAFT_DIR) -> str:
    """The lines the system prompt carries."""
    return "\n".join(f"- {name}: {line}" for name, line in topics(craft_dir).items())


def read_craft(topic: str, craft_dir: Path = CRAFT_DIR) -> str:
    """The note, or (for an unknown topic) a message listing the topics, so the model can retry."""
    name = topic.strip().lower().replace(" ", "-").replace("_", "-")
    path = craft_dir / f"{name}.md"
    if not path.is_file():
        return f"no craft note {topic!r}. Topics: {', '.join(topics(craft_dir))}."
    return path.read_text()[:MAX_RESULT_CHARS]
