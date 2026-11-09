# Judge validation report (v2, family units)

Judge run validation_v2_20261028, model claude-opus-5-5, prompt_hash 0b5ea77dda85.

**PRE-REJUDGE: The live runs were judged under prompt hash 735e2438f08f, not under this prompt (0b5ea77dda85). They have not been judged under this prompt, and this validation is not yet usable as a result for them.**

## Primary: item agreement on units

27 of 40 items match (the judge's set of units, rows mapped through families.json, equals Alex's set; strength ignored): **68%**. Bar: 90%. **NOT MET**

Non-matching items: W06, W08, W09, W13, W19, W23, W24, W25, W29, W31, W33, W35, W38

- W06: Alex {none}; judge {P1}
- W08: Alex {F15}; judge {F15, P1}
- W09: Alex {C1-C-1, C2-C-1, P2}; judge {C1-C-1, C2-C-1}
- W13: Alex {A1, F02, F04, P2}; judge {A1, A2, F02, F04, P2}
- W19: Alex {none}; judge {P1}
- W23: Alex {A1}; judge {P2}
- W24: Alex {none}; judge {P1}
- W25: Alex {B2-B-1, F05, F09, F10}; judge {B2-B-1, F05, F09, F10, F12}
- W29: Alex {A2, C1-C-1, P2}; judge {A2, C1-C-1}
- W31: Alex {C2-C-1, P2}; judge {P2}
- W33: Alex {B1-B-1, B2-B-1, C1-C-1, F09, F12}; judge {B1-B-1, B2-B-1, C1-C-1, F04, F09, F10, F12, P1}
- W35: Alex {B1-B-1}; judge {none}
- W38: Alex {A2, C1-C-1}; judge {C1-C-1}

## Per unit (recall = TP/(TP+FN), precision = TP/(TP+FP))

| unit | reach | Alex-present | TP | FP | FN | recall | precision |
|---|---|---|---|---|---|---|---|
| F01 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F02 | client | 1 | 1 | 0 | 0 | 100% | 100% |
| F03 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F04 | client | 1 | 1 | 1 | 0 | 100% | 50% |
| F05 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F06 | matter | 0 | 0 | 0 | 0 | n/a | n/a |
| F07 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F08 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F09 | matter | 4 | 4 | 0 | 0 | 100% | 100% |
| F10 | client | 1 | 1 | 1 | 0 | 100% | 50% |
| F11 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F12 | client | 3 | 3 | 1 | 0 | 100% | 75% |
| F13 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F14 | client | 1 | 1 | 0 | 0 | 100% | 100% |
| F15 | matter | 1 | 1 | 0 | 0 | 100% | 100% |
| F16 | client | 1 | 1 | 0 | 0 | 100% | 100% |
| A1 | client | 5 | 4 | 0 | 1 | 80% | 100% |
| A2 | client | 3 | 2 | 1 | 1 | 67% | 67% |
| B1-B-1 | client | 4 | 3 | 0 | 1 | 75% | 100% |
| B2-B-1 | client | 3 | 3 | 0 | 0 | 100% | 100% |
| C1-C-1 | client | 5 | 5 | 0 | 0 | 100% | 100% |
| C2-C-1 | client | 4 | 3 | 0 | 1 | 75% | 100% |
| P1 | firm | 2 | 2 | 5 | 0 | 100% | 29% |
| P2 | firm | 9 | 7 | 1 | 2 | 78% | 88% |

**Recall by reach tier**

| group | Alex-present | TP | FP | FN | recall | precision |
|---|---|---|---|---|---|---|
| matter | 12 | 12 | 0 | 0 | 100% | 100% |
| client | 32 | 28 | 4 | 4 | 88% | 88% |
| firm | 11 | 9 | 6 | 2 | 82% | 60% |

Missed entirely (Alex-present > 0, judge TP = 0): none

**By fact type**

| group | Alex-present | TP | FP | FN | recall | precision |
|---|---|---|---|---|---|---|
| verbatim | 10 | 10 | 1 | 0 | 100% | 91% |
| paraphrase | 10 | 10 | 2 | 0 | 100% | 83% |
| client_pattern | 24 | 20 | 1 | 4 | 83% | 95% |
| area_pattern | 11 | 9 | 6 | 2 | 82% | 60% |

Missed entirely (Alex-present > 0, judge TP = 0): none

## Agreement split (construction labels, read after the checks)

| base source | items matching | agreement |
|---|---|---|
| N0 | 23 of 30 | 77% |
| memory-condition | 4 of 10 | 40% |

| kind | items matching | agreement |
|---|---|---|
| area_pattern | 2 of 6 | 33% |
| client_pattern | 6 of 8 | 75% |
| lookalike | 6 of 10 | 60% |
| multi | 1 of 2 | 50% |
| none | 4 of 4 | 100% |
| paraphrase | 5 of 6 | 83% |
| verbatim | 3 of 4 | 75% |

## Label quality: inserted units Alex did not label

6 of 28 inserted units not labelled by Alex: W06 P1, W08 P1, W13 A2, W19 P1, W23 P2, W33 F04

## Strength agreement (secondary; units both Alex and the judge detected)

| type | pairs | agree |
|---|---|---|
| verbatim | 9 | 100% |
| paraphrase | 10 | 10% |
| client_pattern | 18 | 89% |
| area_pattern | 8 | 88% |

All types: 33 of 45 agree (73%). Excluded: 1 marked unsure by Alex, 3 without a strength.

| Alex \ judge | verbatim | paraphrase | pattern |
|---|---|---|---|
| verbatim | 9 | 9 | 0 |
| paraphrase | 0 | 1 | 2 |
| pattern | 0 | 1 | 23 |

FAIL: item-level agreement 68% is below 90%
