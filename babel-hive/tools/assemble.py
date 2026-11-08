"""Inline puzzles.json into template.html -> ../index.html"""
import pathlib
here = pathlib.Path(__file__).parent
html = (here / "template.html").read_text()
data = (here / "puzzles.json").read_text().strip()
(here.parent / "index.html").write_text(html.replace("/*DATA*/null", data))
