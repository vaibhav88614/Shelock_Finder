#!/usr/bin/env python3
"""Local n-gram plagiarism checker for thesis DOCX files."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from docx import Document

DEFAULT_SOURCE_DOMAINS = [
    "krishikosh.egranth.ac.in",
    "discoveryjournals.org",
    "academicjournals.org",
    "isdsnet.com",
    "indianjournals.com",
    "hict.edu.vn",
    "docview.dlib.vn",
    "file-rajshahi.portal.gov.bd",
    "ejbiophysics.org",
    "egeoscien.neigae.ac.cn",
    "recentscientific.com",
    "www.recentscientific.com",
]

BOILERPLATE_PHRASES = [
    "genetic variability is the foundation of any crop improvement programme",
    "narrow difference between pcv and gcv",
    "predominance of additive gene action",
    "high broad sense heritability",
    "genetic advance as per cent of mean",
    "similar findings were reported by",
    "similar findings were obtained by",
    "indicates good scope for improvement through selection",
    "path coefficient analysis provides a detailed assessment",
    "principal component analysis was carried out to assess the genetic diversity",
    "mahalanobis d2 analysis",
    "intra cluster distances were consistently lower than the inter cluster distances",
    "number of seeds per pod exhibited the highest positive direct effect",
    "the present investigation was carried out to assess the extent of genetic variability",
    "analysis of variance is a statistical technique used to determine whether significant differences exist",
    "phenotypic correlation coefficient values among seed yield and its attributing traits",
    "considerable variation was observed among the cowpea genotypes",
    "the residual effect of 0.66 indicated that the characters included in the path analysis",
]

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "was", "were", "be", "been", "being",
    "that", "this", "these", "those", "it", "its", "their", "there", "which",
    "are", "has", "have", "had", "not", "also", "can", "may", "per", "among",
}


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t and t not in STOPWORDS]


def shingles(words: list[str], n: int) -> set[str]:
    if len(words) < n:
        return set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def extract_paragraphs(docx_path: Path) -> list[dict]:
    doc = Document(str(docx_path))
    paragraphs = []
    for idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        words = tokens(text)
        paragraphs.append(
            {
                "index": idx,
                "style": para.style.name if para.style else "Normal",
                "text": text,
                "words": words,
                "shingles5": shingles(words, 5),
                "shingles8": shingles(words, 8),
            }
        )
    return paragraphs


def document_shingles(paragraphs: Iterable[dict], n: int) -> set[str]:
    combined: set[str] = set()
    for para in paragraphs:
        combined |= para.get(f"shingles{n}", set())
    return combined


def fetch_domain_text(domain: str, timeout: int = 12) -> str:
    """Best-effort fetch of visible text from a domain homepage/search page."""
    urls = [
        f"https://{domain}",
        f"http://{domain}",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; plagcheck/1.0)"}
    chunks: list[str] = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=timeout, headers=headers)
            if resp.status_code >= 400:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(" ", strip=True)
            if len(text) > 500:
                chunks.append(text[:250000])
                break
        except requests.RequestException:
            continue
    return " ".join(chunks)


def load_corpus_cache(cache_path: Path) -> dict[str, str]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return {}


def save_corpus_cache(cache_path: Path, corpus: dict[str, str]) -> None:
    cache_path.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")


def build_corpus(domains: list[str], cache_path: Path) -> dict[str, str]:
    corpus = load_corpus_cache(cache_path)
    for domain in domains:
        if domain in corpus and len(corpus[domain]) > 500:
            continue
        print(f"Fetching corpus text for {domain}...")
        corpus[domain] = fetch_domain_text(domain)
    save_corpus_cache(cache_path, corpus)
    return corpus


def compare_paragraphs(
    target_paragraphs: list[dict],
    reference_paragraphs: list[dict] | None = None,
    reference_shingles5: set[str] | None = None,
    reference_shingles8: set[str] | None = None,
) -> list[dict]:
    if reference_paragraphs is not None:
        reference_shingles5 = document_shingles(reference_paragraphs, 5)
        reference_shingles8 = document_shingles(reference_paragraphs, 8)

    results = []
    for para in target_paragraphs:
        s5 = jaccard(para["shingles5"], reference_shingles5 or set())
        s8 = jaccard(para["shingles8"], reference_shingles8 or set())
        score = max(s5, s8)
        results.append(
            {
                "index": para["index"],
                "style": para["style"],
                "score_pct": round(score * 100, 2),
                "score5_pct": round(s5 * 100, 2),
                "score8_pct": round(s8 * 100, 2),
                "preview": para["text"][:180],
            }
        )
    return results


def overall_score(target_paragraphs: list[dict], ref5: set[str], ref8: set[str]) -> float:
    s5 = jaccard(document_shingles(target_paragraphs, 5), ref5)
    s8 = jaccard(document_shingles(target_paragraphs, 8), ref8)
    return max(s5, s8) * 100


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_html_report(
    path: Path,
    title: str,
    overall: float,
    rows: list[dict],
    comparison_label: str,
) -> None:
    rows_sorted = sorted(rows, key=lambda r: r["score_pct"], reverse=True)
    body_rows = []
    for row in rows_sorted:
        color = "#d4edda"
        if row["score_pct"] >= 15:
            color = "#fff3cd"
        if row["score_pct"] >= 25:
            color = "#f8d7da"
        body_rows.append(
            f"<tr style='background:{color}'><td>{row['index']}</td>"
            f"<td>{html.escape(row['style'])}</td>"
            f"<td>{row['score_pct']:.2f}%</td>"
            f"<td>{row['score5_pct']:.2f}%</td>"
            f"<td>{row['score8_pct']:.2f}%</td>"
            f"<td>{html.escape(row['preview'])}</td></tr>"
        )

    content = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>{html.escape(title)}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; font-size: 13px; }}
th {{ background: #f0f0f0; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p><strong>{html.escape(comparison_label)} overall score:</strong> {overall:.2f}%</p>
<table>
<tr><th>Para #</th><th>Style</th><th>Score</th><th>5-gram</th><th>8-gram</th><th>Preview</th></tr>
{''.join(body_rows)}
</table></body></html>"""
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Local n-gram plagiarism checker")
    parser.add_argument("--target", required=True, help="Target DOCX to evaluate")
    parser.add_argument("--original", help="Original DOCX for comparison A")
    parser.add_argument("--output-dir", default="scripts/plagcheck_output", help="Output directory")
    parser.add_argument("--cache", default="scripts/plagcheck_output/corpus_cache.json")
    parser.add_argument("--skip-fetch", action="store_true", help="Use cached corpus only")
    args = parser.parse_args()

    target_path = Path(args.target)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    target_paragraphs = extract_paragraphs(target_path)
    print(f"Loaded {len(target_paragraphs)} non-empty paragraphs from {target_path.name}")

    summary = {"target": str(target_path)}

    if args.original:
        original_path = Path(args.original)
        original_paragraphs = extract_paragraphs(original_path)
        ref5 = document_shingles(original_paragraphs, 5)
        ref8 = document_shingles(original_paragraphs, 8)
        rows = compare_paragraphs(target_paragraphs, reference_shingles5=ref5, reference_shingles8=ref8)
        overall = overall_score(target_paragraphs, ref5, ref8)
        csv_path = output_dir / "comparison_original.csv"
        html_path = output_dir / "comparison_original.html"
        write_csv(csv_path, rows)
        write_html_report(html_path, "Comparison vs Original", overall, rows, "Revised vs Original")
        summary["vs_original_pct"] = round(overall, 2)
        print(f"Comparison vs original: {overall:.2f}%")

    cache_path = Path(args.cache)
    if args.skip_fetch and cache_path.exists():
        corpus = load_corpus_cache(cache_path)
    else:
        corpus = build_corpus(DEFAULT_SOURCE_DOMAINS, cache_path)

    boilerplate_text = " ".join(BOILERPLATE_PHRASES)
    if args.original:
        original_paragraphs_for_corpus = extract_paragraphs(Path(args.original))
        boilerplate_text += " " + " ".join(p["text"] for p in original_paragraphs_for_corpus)

    corpus_text = " ".join(corpus.values()) + " " + boilerplate_text
    corpus_words = tokens(corpus_text)
    corpus5 = shingles(corpus_words, 5)
    corpus8 = shingles(corpus_words, 8)
    rows_corpus = compare_paragraphs(target_paragraphs, reference_shingles5=corpus5, reference_shingles8=corpus8)
    overall_corpus = overall_score(target_paragraphs, corpus5, corpus8)
    write_csv(output_dir / "comparison_corpus.csv", rows_corpus)
    write_html_report(
        output_dir / "comparison_corpus.html",
        "Comparison vs Matched Source Corpus",
        overall_corpus,
        rows_corpus,
        "Document vs downloaded source corpus",
    )
    summary["vs_corpus_pct"] = round(overall_corpus, 2)
    print(f"Comparison vs source corpus: {overall_corpus:.2f}%")

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Reports written to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
