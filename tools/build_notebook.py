"""Convert a '# %%' percent-format script to an executed .ipynb.

Usage (from the project root):  uv run python tools/build_notebook.py notebooks/02_eda.py notebooks/02_eda.ipynb
Cells are split on '# %%' ('# %% [markdown]' for text cells; markdown lines are '# ' comments). The notebook is executed
with notebooks/ as the working directory so outputs are stored in the .ipynb.
"""
import re
import sys

import nbformat
from nbclient import NotebookClient

src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf8").read()
parts = re.split(r"^# %%(.*)$", text, flags=re.M)
nb = nbformat.v4.new_notebook()
for hdr, body in zip(parts[1::2], parts[2::2]):
    body = body.strip("\n")
    if "[markdown]" in hdr:
        md = "\n".join(l[2:] if l.startswith("# ") else l.lstrip("#") for l in body.splitlines())
        nb.cells.append(nbformat.v4.new_markdown_cell(md))
    else:
        nb.cells.append(nbformat.v4.new_code_cell(body))
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
NotebookClient(nb, timeout=600, resources={"metadata": {"path": "notebooks"}}).execute()
nbformat.write(nb, dst)
print("ok", len(nb.cells), "cells")
