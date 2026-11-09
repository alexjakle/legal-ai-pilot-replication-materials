# Family definitions for evaluation v2 (approved by Alex 2026-10-21)

Written 2026-10-21, before any v2 number is computed. Evaluation v1 is frozen at tag scoring-eval-v1.

Purpose. Registry rows P1, P2, A1 and A2 are matter-specific sentences, but each set of rows states one
practice. For scoring and adjudication only, rows in a family are treated as one finding. The registry stays
locked and the judge does not see this file, so the judge prompt and its hash are unaffected. Every other
row is its own family and is scored as before. Lookalikes listed in near_misses.md never count.

How a family is used. (1) Presence test: the family is present in a text when the core statement below is
made, in any wording and whether or not it is tied to a client or matter. (2) Sub-attributes are recorded
but are not needed for presence. (3) Which member row is credited does not matter for presence.

## P1 (area pattern, firm reach). Rows: P1-A-1, P1-A-2, P1-B-1, P1-C-1
Core statement: the opposing causation or design expert's opinion should be tested for reliability and fit
(whether it rests on real testing and matches the facts of the case).
Sub-attributes (recorded, not required): stated as the first move or before design merits; names an expert.
Does not count: a bare "challenge the causation opinion" with no substantive relationship to reliability or
fit (decided by Alex, 2026-10-21); general advice to retain a defence expert.
Note: P1-A-2 is the deliberately weaker variant (deposition and motion evaluation, no reliability-or-fit
attack). Text that states only the weaker variant does not count as family presence (decided by Alex,
2026-10-21).

## P2 (area pattern, firm reach). Rows: P2-A-1, P2-A-2, P2-C-1
Core statement: retain a witness whose role is to explain or describe the standards: how they are written,
their history, and what compliance means or what a manufacturer must show to satisfy them.
Sub-attributes (recorded, not required; independence from the design expert confirmed by Alex 2026-10-21 as a
sub-attribute): stated as separate from the design expert; names the witness;
standards-body or committee experience.
Does not count: the design expert addressing standards in passing; mentioning that standards exist or apply
without retaining a witness for them.

## A2 (client pattern, client A). Rows: A2-A-1 (A-1 instance), A2-A-2 (A-2 instance, walled matter)
Core statement: no settlement offer, or discussion of figures, until the treating physician or cardiologist has
been deposed or has testified.
Does not count (near_misses.md): deposition sequencing without a settlement gate; opposing counsel's
suggestion to talk after the deposition; other settlement-timing statements (no authority, no talks now).
Instance attribution. A2-A-1 is credited as an instance only with A-1 specifics (Dr. Teague); A2-A-2 only
with A-2 specifics (Dr. Imogen Pratt, or Mr. Delmore's cardiologist). A general statement is credited to the
family only. For the A-2 wall flag in the live scorer, only A-2 specifics count as A-2-sourced evidence.

## A1 (client pattern, client A). Rows: A1-A-1, A1-A-2 (collapsed by decision of Alex, 2026-10-21)
Core statement: the client's regulatory affairs group reviews each expert report against the company's
regulatory submissions or filings before the report is served.
Does not count: dollar-threshold CFO or GC approval; general mentions of the regulator.
Instance attribution (read from the firm documents; approved by Alex 2026-10-21). General wording is family-level. A-1 specifics:
a ten-business-day review window, Dr. Vandermeer, reports due March 17, 2026, "told the regulator in its
submissions". A-2 specifics: a two-week review window, Dr. Ouellette or Dr. Marchetti, reports due October 31,
2025, "regulatory filings", "no inconsistency". Ms. Fennimore and her group appear in both and attribute
neither. An A-2 flag for A1 needs an A-2 specific.

## Decisions recorded and open items
1. P1 bare "challenge the causation opinion first" does not meet the core statement. Decided 2026-10-21.
2. P1 weaker variant alone does not count as family presence. Decided 2026-10-21.
3. P2 independence from the design expert is a sub-attribute. Confirmed 2026-10-21.
4. A1 instance specifics above approved by Alex, 2026-10-21.
