# Thesis Plagiarism Reduction — Rewrite Notes

## Documents

| File | Description |
|------|-------------|
| `r & d4 (1).docx` | Original thesis chapter (Results & Discussion + Summary) |
| `r & d4 (1)_revised.docx` | Revised manuscript (124 paragraphs rewritten) |
| `DB_report_r & d4.pdf` | DrillBit baseline report (36% similarity) |

## Baseline (DrillBit)

- **Overall similarity:** 36% (Grade B — Upgrade)
- **Primary source type:** Internet (31.17%)
- **Matched sources:** 74 (60+ from `krishikosh.egranth.ac.in`)
- **Root cause:** Templated plant-breeding language repeated across trait subsections, correlation/path analyses, and summary chapter

## Rewrite scope

**124 paragraphs** rewritten across:

| Section | Paragraph indices | Changes applied |
|---------|-------------------|-----------------|
| Transitions | 0, 1, 2, 7, 14–19, 60–61, 68, 74–75, 77, 79, 91–92, 125, 165, 171, 210–213 | Restructured openers; removed templated bridges |
| §4.1.2 (Variability) | 21–22, 24–25, 30–31, 33–34, 36–37, 39–40, 42–43, 46–47, 49–50, 52–53, 55–56, 58–59 | 12 distinct paragraph architectures; mechanistic + breeding sentences added |
| §4.1.3 (PCA) | 62, 63, 65, 66 | Trait-loading and interpretation paragraphs re-authored |
| §4.2 (Clusters) | 78, 81–84, 86–89 | Cluster means, distances, divergence contributions rewritten |
| §4.2.5 (Correlation) | 94–96, 98–99, 101–102, 104–105, 107–108, 110–111, 115, 117, 119, 121–122, 124 | Structural inversion; citation clusters broken into narrative form |
| §4.2.6 (Path analysis) | 126, 130–131, 133–134, 137–138, 140–141, 143–144, 146–147, 149–150, 152–153, 155–156, 158–159, 161–163 | Full sentence restructure; added interpretive content |
| §4.3 (Seed quality) | 172–175 | Germination/vigour narrative rewritten |
| §V (Summary) | 195–208 | Re-authored from scratch; no verbatim body reuse |
| Citations | 22, 25, 31, 34, 37, 40, 43, 64, 79, 96, 99, 102, 108, 111, 117, 119, 122, 124, 131, 134, 144, 147, 150, 153, 156, 159, 162, 175 | Cluster citations converted to narrative integration |

## Hard constraints honoured

- No content deleted; all paragraphs expanded or maintained
- All numeric values preserved exactly (GCV, PCV, heritability, GAM, correlations, path coefficients, cluster distances, germination, yield)
- All Table/Fig references and author-year citations retained
- No character-substitution or formatting tricks

## Local verification results

Checker: `scripts/plagcheck.py`  
Final run: `scripts/plagcheck_output/revised_v2/`

| Metric | Original | Revised | Target |
|--------|----------|---------|--------|
| vs. original document | 100% | **15.50%** | < 25% |
| vs. boilerplate + source corpus | ~36% (proxy) | **9.07%** | ≤ 10% |
| Paragraphs ≥ 15% vs. corpus | — | **0** | 0 |

Heatmap report: [`scripts/plagcheck_report.html`](scripts/plagcheck_report.html)

## How to regenerate

```powershell
python V:\temp\Shelock_Finder\scripts\build_rewrites.py
python V:\temp\Shelock_Finder\scripts\apply_thesis_rewrites.py
python V:\temp\Shelock_Finder\scripts\plagcheck.py `
  --target "V:\temp\Shelock_Finder\r & d4 (1)_revised.docx" `
  --original "V:\temp\Shelock_Finder\r & d4 (1).docx" `
  --output-dir "V:\temp\Shelock_Finder\scripts\plagcheck_output\revised_v2" `
  --skip-fetch
```

## Recommended DrillBit re-submission settings

When re-submitting `r & d4 (1)_revised.docx` through your institution's DrillBit portal, request these exclusions be enabled:

1. **References / Bibliography** — Excluded
2. **Quotes** — Excluded (ensure direct quotations are in quote marks)
3. **Common phrases / Excluded phrases** — Enabled
4. **Exclude matches < 20 words** — if permitted by your university policy
5. **Student papers** — keep enabled (only 0.21% in baseline)

These settings alone typically reduce reported similarity by 2–4 percentage points on top of the rewrite gains.

## Limitations

The local checker is a **proxy**, not a replacement for DrillBit. It uses n-gram Jaccard similarity against a boilerplate corpus plus downloaded domain homepages. The authoritative score will come from your institutional DrillBit re-run on `r & d4 (1)_revised.docx`.

## Expected DrillBit outcome

Based on the rewrite depth (124 paragraphs, all hot zones) and local score of **9.07%**, the revised document should fall within the **Grade A (0–10%)** band on DrillBit re-submission, especially with reference/quote exclusions enabled.
