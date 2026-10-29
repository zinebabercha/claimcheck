# ClaimCheck evaluation — mistral-small-latest

Cases: 28 (errors: 0)

| Metric | Value |
|---|---|
| Verdict accuracy | 25/28 (89%) |
| Over-confident wrong verdicts | 0 |
| Key clauses retrieved | 100% |
| Key clause cited (verified) | 93% |
| Quotes rejected by verification | 8/126 |
| Median latency | 5.5 s |

| Case | Expected | Got | |
|---|---|---|---|
| velo-commun-ouvert | non_couvert/incertain | non_couvert | ✅ |
| bougie-jardin | non_couvert | non_couvert | ✅ |
| velo-commun-ferme-force | couvert | couvert | ✅ |
| garage-prive-force | couvert | couvert | ✅ |
| cave-privee-ouverte | non_couvert | non_couvert | ✅ |
| cambriolage-fenetre | couvert | couvert | ✅ |
| porte-non-verrouillee | incertain/couvert | non_couvert | ❌ |
| chaises-jardin-volees | non_couvert | non_couvert | ✅ |
| tempete-parasol | couvert | couvert | ✅ |
| fuite-evier | couvert | couvert | ✅ |
| condensation | non_couvert | non_couvert | ✅ |
| infiltration-plafond | couvert | couvert | ✅ |
| infiltration-toiture | non_couvert | incertain | ❌ |
| cigarette-canape | non_couvert | non_couvert | ✅ |
| feu-poele | couvert | couvert | ✅ |
| fumee-chauffage | couvert | couvert | ✅ |
| vitre-ballon | couvert | couvert | ✅ |
| vitre-rayure | non_couvert | non_couvert | ✅ |
| rc-voisin | couvert | couvert | ✅ |
| rc-objet-prete | non_couvert | non_couvert | ✅ |
| intentionnel | non_couvert | non_couvert | ✅ |
| usure-canalisation | non_couvert/incertain | non_couvert | ✅ |
| velo-option-ok | couvert | couvert | ✅ |
| velo-option-cable | non_couvert/incertain | non_couvert | ✅ |
| bijoux-cambriolage | couvert | incertain | ❌ |
| tempete-80kmh-en | non_couvert/incertain | non_couvert | ✅ |
| declaration-tardive | couvert/incertain | couvert | ✅ |
| inondation-riviere | incertain/non_couvert | incertain | ✅ |