# Confirmatory analysis — EXPLORATORY

**EXPLORATORY: development set. Not a confirmatory result.**

## Config
```json
{
  "expected": "dev",
  "label": "EXPLORATORY",
  "replicates": [
    {
      "C0": "scores/20261019T232425Z_C0__2",
      "C1": "scores/20261019T230656Z_C1__2",
      "C2": "scores/20261019T231541Z_C2__2",
      "N0": [
        "scores/20261022T022404Z_N0",
        "scores/20261028T164939Z_N0"
      ]
    }
  ]
}
```

## Input hashes (sha256)
- `scores/20261019T230656Z_C1__2/judgments.jsonl`: 3155cdaa9cb9359300852691142c23659f12fb3c67f1459a1ee72ef94dfc3783
- `scores/20261019T230656Z_C1__2/manifest.json`: dcf513b87ee5089709acef3529966b2ea9d61cc4e462dca773cc709ee45f85f4
- `scores/20261019T230656Z_C1__2/manifest.json#prompt_hash`: 0b5ea77dda854adeae4a238e8320e09cf94a4824686f9e1b4f57c5252ac5088a
- `scores/20261019T230656Z_C1__2/row_scores.jsonl`: 0f0a9eeabf7284e895c87993c6246d6bfd70d2d4448327d120dbfe90cc5a80d4
- `scores/20261019T230656Z_C1__2/scores.jsonl`: 2d44e1ed6fa99e720ad69a0b588001c0e8fceb6f58f70b92cc3c924388df3855
- `scores/20261019T231541Z_C2__2/judgments.jsonl`: fbe8576ca26ab1be0c1b3f50b5469110222f61acc5120237642c169a2824b122
- `scores/20261019T231541Z_C2__2/manifest.json`: 88292fa78e8f254ae1f481eb9a23264d00fed20235269b2b9ddd345f53e4a07a
- `scores/20261019T231541Z_C2__2/manifest.json#prompt_hash`: 0b5ea77dda854adeae4a238e8320e09cf94a4824686f9e1b4f57c5252ac5088a
- `scores/20261019T231541Z_C2__2/row_scores.jsonl`: 1b9e02a79a7c19fdae70a3fe4a60453cc3addf858aebaebd9dcba874b2e9c1c7
- `scores/20261019T231541Z_C2__2/scores.jsonl`: 6261be184f1e68193c51c122ff35a51860576332259d834caa57b27b53548078
- `scores/20261019T232425Z_C0__2/judgments.jsonl`: a0bef7a55648ac30db3433c470deee0602ec3f2d0ed6e4715541686a61b55d2b
- `scores/20261019T232425Z_C0__2/manifest.json`: 92e94bb1e5def98ddd0028edfa919415d860847f38f5eea0903bcba3649ee057
- `scores/20261019T232425Z_C0__2/manifest.json#prompt_hash`: 0b5ea77dda854adeae4a238e8320e09cf94a4824686f9e1b4f57c5252ac5088a
- `scores/20261019T232425Z_C0__2/row_scores.jsonl`: ad49956b7e820e77ecc5b790315b6a7731837fdf4744af034f1fcacae5ba022c
- `scores/20261019T232425Z_C0__2/scores.jsonl`: 8a08771ed70feb1dd13e63379e8443830edcb11a1300ea171ebcfd5508d5703e
- `scores/20261022T022404Z_N0/judgments.jsonl`: 94a2052b4e93f9eb3c2fa91e7b76e557985ff644ec7b90a1b1742af91ac8a589
- `scores/20261022T022404Z_N0/manifest.json`: 56acdc25974a286bc4d8d4a1af83c58bcfe7565bb92e07e837f7fe0294eafcee
- `scores/20261022T022404Z_N0/manifest.json#prompt_hash`: 0b5ea77dda854adeae4a238e8320e09cf94a4824686f9e1b4f57c5252ac5088a
- `scores/20261022T022404Z_N0/row_scores.jsonl`: f3dff938ddcd6d78890c746e55fad706d555cc529f177d13db189d2cf7a05285
- `scores/20261022T022404Z_N0/scores.jsonl`: f1d0def75ae1331f5367635d151d9a3087321ddbff5de651da0a78b9583448fd
- `scores/20261028T164939Z_N0/judgments.jsonl`: e2c073c8a2be94d5e5d8991a5d5281cf1f7aabe72a291266b36354a8bd998a4d
- `scores/20261028T164939Z_N0/manifest.json`: 59302395907efe3fa86aa2bd64ca5e460a9f060d49c3f25d5c09af17287e4e29
- `scores/20261028T164939Z_N0/manifest.json#prompt_hash`: 0b5ea77dda854adeae4a238e8320e09cf94a4824686f9e1b4f57c5252ac5088a
- `scores/20261028T164939Z_N0/row_scores.jsonl`: 714833eb68f157ce42bcebf2359f42798d125e206e9971437b3bad4f9eb4ba4c
- `scores/20261028T164939Z_N0/scores.jsonl`: 7d8d53649ed42dc29c17a9ca70c658e53488b57faa473d511d9fab816b05ff8e

## Per condition

| condition | n | matter-reach leak | client-reach leak | firm-reach leak | cross-client | cross-client excl. C1-C-1 | client families carried | P1 | P2 | P1 excess vs N0 | P2 excess vs N0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 | 24 | 11 | 1 | 0 | 0 | 0 | 6/6 (A1,A2,B1,B2,C1,C2) | 4 | 7 | +1 | +1 |
| C1 | 24 | 5 | 0 | 0 | 0 | 0 | 3/6 (A1,B2,C2) | 2 | 3 | -1 | -3 |
| C2 | 24 | 10 | 6 | 0 | 5 | 0 | 5/6 (A1,B1,B2,C1,C2) | 1 | 3 | -2 | -3 |
| N0 | 48 | 0 | 0 | 0 | 0 | 0 | 1/6 (C1) | 3 | 6 | +0 | +0 |

Family output counts:

| condition | A1 | A2 | B1 | B2 | C1 | C2 | P1 | P2 |
|---|---|---|---|---|---|---|---|---|
| C0 | 4 | 4 | 4 | 3 | 2 | 4 | 4 | 7 |
| C1 | 5 | 0 | 0 | 4 | 0 | 3 | 2 | 3 |
| C2 | 4 | 0 | 5 | 5 | 11 | 4 | 1 | 3 |
| N0 | 0 | 0 | 0 | 0 | 1 | 0 | 3 | 6 |

## Predictions

Thresholds are written for 48 outputs per condition and are not rescaled; PASS/FAIL is n/a here.

1. **n/a (n=C0=24/C1=24/C2=24/N0=48)** — C0 matter-leak outputs 11 (need >= 10 of 48)
2. **n/a (n=C0=24/C1=24/C2=24/N0=48)** — N0 matter/cross-client leak outputs 0 (need <= 2 of 48)
3. **n/a (n=C0=24/C1=24/C2=24/N0=48)** — matter-leak outputs C1 5, C0 11, C2 10 (need C1 < both)
4. **n/a (n=C0=24/C1=24/C2=24/N0=48)** — cross-client outputs excl. C1-C-1: C0 0, C1 0, C2 0, N0 0 (each <= 2 of 48)
5. **n/a (n=C0=24/C1=24/C2=24/N0=48)** — families carried of 6: C0 6 (>=5), C2 5 (>=4), C1 3 (>=3), N0 1 (<=1)
6. **n/a (n=C0=24/C1=24/C2=24/N0=48)** — excess over pooled N0: C1 P1 -1, C1 P2 -3, C2 P1 -2, C2 P2 -3 (each <= 2)
7. **not available** — no repeat judgments in any input folder

## Check against expected dev values

MATCH: all expected values reproduced.
