#!/usr/bin/env bash
set -euo pipefail

report_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$report_dir/.." && pwd)"
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT

mkdir -p "$repo_dir/output/pdf"
cd "$repo_dir"

pdflatex -interaction=nonstopmode -halt-on-error \
  -output-directory="$build_dir" stability_report/main.tex >/dev/null
pdflatex -interaction=nonstopmode -halt-on-error \
  -output-directory="$build_dir" stability_report/main.tex >/dev/null

if grep -Eq 'undefined references|Overfull \\hbox|Fatal error' "$build_dir/main.log"; then
  echo "LaTeX validation failed; inspect $build_dir/main.log before the temporary directory is removed." >&2
  grep -E 'undefined references|Overfull \\hbox|Fatal error' "$build_dir/main.log" >&2
  exit 1
fi

gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.7 -dPDFSETTINGS=/ebook \
  -dNOPAUSE -dQUIET -dBATCH \
  -sOutputFile="$repo_dir/output/pdf/stability_topology_report.pdf" \
  "$build_dir/main.pdf"
echo "Wrote output/pdf/stability_topology_report.pdf"
