#!/usr/bin/env python3
"""Build the dependency-free, single-file edition from the maintained sources."""
from pathlib import Path


def build():
    folder = Path(__file__).resolve().parent
    engine = (folder / "shardturn_engine.py").read_text(encoding="utf-8")
    interface = (folder / "shardturn.py").read_text(encoding="utf-8")
    marker = "from shardturn_engine import Card, ShardturnGame\n"
    if interface.count(marker) != 1:
        raise RuntimeError("The engine import must occur exactly once.")
    combined = interface.replace(marker, "# --- Rules engine ---\n" + engine + "\n# --- Graphical interface ---\n")
    compile(combined, "Shardturn.py", "exec")
    output = folder / "Shardturn.py"
    output.write_text(combined, encoding="utf-8")
    output.chmod(0o755)
    print(output)


if __name__ == "__main__":
    build()
