# EvidenceGraph demo video

- **Target length:** 90 seconds
- **Audience:** financial research and AI engineering reviewers
- **Story:** select a real SEC filing, inspect a risk disclosure, verify annual facts, and export the research.

## Verified reference run

On 2026-10-10, the application synced Target Corporation's 10-K for the period ended January 31, 2026 (SEC accession `0000027419-26-000016`) into an isolated temporary database. It indexed 229 passages. The question “What inventory shrink risks does Target disclose in its annual filing?” returned eight passages. A separate annual revenue query returned FY2023–FY2025 SEC facts:

| SEC fiscal year | Period ended | Revenue | Annual change |
|---|---|---:|---:|
| 2023 | 2024-02-03 | $107.412B | — |
| 2024 | 2025-02-01 | $106.566B | −0.79% |
| 2025 | 2026-01-31 | $104.780B | −1.68% |

The filed report is available from [SEC EDGAR](https://www.sec.gov/Archives/edgar/data/27419/000002741926000016/tgt-20260131.htm), with structured facts in [SEC Company Facts](https://data.sec.gov/api/xbrl/companyfacts/CIK0000027419.json). This confirms one real API workflow and one issuer's figures; it does not establish general research accuracy. The browser recording should show the values it actually returns.

The opt-in retrieval smoke set contains seven questions over this filing. After enabling FTS5's built-in Porter tokenizer, BM25 achieved Recall@5 **0.8571**, MRR **0.8571**, and nDCG@5 **0.8396**. A simpler distinct-token overlap baseline achieved **0.7143**, **0.3810**, and **0.4660**. BM25 still missed the phrased question about store support for digital fulfillment. These small, anchor-labeled retrieval scores are not answer-accuracy measurements.

## Before recording

- Start EvidenceGraph and open the introduction page, then select **Get started**.
- In Settings, enter a descriptive SEC contact email. Search for **Target** or **TGT** and add Target Corporation.
- In Companies, sync the 10-K whose period ended **January 31, 2026** and whose filing date is **March 11, 2026**. Filing sync uses the SEC accession selected from the list.
- Wait for the job to complete. In Documents, confirm the report period, filing date, source link, and passage count.
- Leave optional model generation disabled. It is not needed for this walkthrough, and model drafts do not have semantic citation verification.

## 90-second storyboard

| Time | On screen | Voiceover |
|---|---|---|
| 0:00–0:08 | Introduction page, then **Get started**. | “Financial research is only useful when you can check the source. EvidenceGraph brings SEC filing passages and reported annual facts into one reviewable workspace.” |
| 0:08–0:18 | Search for Target, open its filing list, point out report period and filing date. | “Choose the issuer and the exact filing. The period end and filing date are separate, so you can see which reporting period the document covers.” |
| 0:18–0:28 | Sync the selected 10-K; show the completed job and document row. | “The filing is retrieved from SEC EDGAR, parsed, and indexed as passages linked to its filing.” |
| 0:28–0:45 | Ask: “What inventory shrink risks does Target disclose in its annual filing?” Open one relevant result in the evidence viewer. | “Search the filing for a specific risk. Each result links back to the extracted passage and the original SEC document. Review the filing itself before drawing a conclusion.” |
| 0:45–1:05 | Ask: “What was Target annual revenue for the latest years?” Show the annual metric cards, fiscal years, period ends, and growth. | “Annual revenue facts come from SEC XBRL. EvidenceGraph shows the fiscal year and period end, then calculates year-over-year change only when the annual periods and units are comparable.” |
| 1:05–1:18 | Open an XBRL source link; return to the research result. | “The fact citation points to the SEC source. The retrieved text and the structured facts remain distinct evidence types.” |
| 1:18–1:30 | Export the Markdown report, show its citations and caveats, then end on Overview. | “Export the question, results, and citations as a research note. EvidenceGraph supports research and review; verify every source before relying on a claim.” |

## Recording checks

- The UI currently searches with SQLite FTS5 lexical BM25 and Porter stemming and returns up to eight passages. Do not call it semantic, vector, hybrid, or reranked search.
- To repeat the optional live evaluation in PowerShell, set `$env:EVIDENCEGRAPH_RUN_LIVE_SEC = "1"`, run `py -3.11 -m pytest -q -s tests/test_live_sec.py`, then clear the setting. It uses temporary storage and sends public requests to SEC EDGAR.
- The deterministic answer summarizes what was retrieved; it does not synthesize a full financial analysis. If optional generation is enabled later, label it as an AI-assisted draft and show its semantic-verification caveat.
- Confirm every figure, fiscal year, period end, and citation on screen before narrating it. SEC facts can change after amendments or new filings.
- If the query returns no relevant passage or fact, show the missing-evidence state or choose a supported query. Do not hide retrieval failures or add sample results.
