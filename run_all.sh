#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MPLCONFIGDIR="${TMPDIR:-/tmp}/local-currency-defi-adaptive-governance-mpl"
mkdir -p "$MPLCONFIGDIR"

cd "$PROJECT_DIR"
python3 analysis/run_analysis.py

python3 - <<'PY'
from pathlib import Path
from PIL import Image

figures = sorted(Path("figures").glob("*.png"))
if len(figures) != 7:
    raise SystemExit(f"Expected 7 figures, found {len(figures)}")
for path in figures:
    with Image.open(path) as image:
        image.load()
        if image.width < 1_000 or image.height < 600:
            raise SystemExit(f"Figure is unexpectedly small: {path} {image.size}")
print("Validated 7 publication PNG figures")
PY
sync figures/*.png

python3 -Werror -m py_compile analysis/model.py analysis/run_analysis.py
python3 -m unittest discover -s tests -q

cd manuscript
LATEX_BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/adaptive-governance-latex-XXXXXX")"
pdflatex -interaction=nonstopmode -halt-on-error \
    -output-directory="$LATEX_BUILD_DIR" main.tex
pdflatex -interaction=nonstopmode -halt-on-error \
    -output-directory="$LATEX_BUILD_DIR" main.tex

gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dCompatibilityLevel=1.5 \
    -dPDFSETTINGS=/prepress \
    -sOutputFile="$LATEX_BUILD_DIR/main-final.pdf" \
    "$LATEX_BUILD_DIR/main.pdf"
cp "$LATEX_BUILD_DIR/main-final.pdf" main.pdf
sync main.pdf

if grep -Eq "undefined references|undefined citations|Fatal error" \
    "$LATEX_BUILD_DIR/main.log"; then
    echo "LaTeX validation failed: unresolved reference, citation, or fatal error" >&2
    exit 1
fi

echo "Reproduction complete: manuscript/main.pdf"
