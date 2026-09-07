# Retrieval evaluation

Generated 2026-09-07 07:38 UTC. Expected ids are computed from `data/inventory.json` for each query, never typed by hand.

## Per mode

| mode | cases | passed | n/a | mean precision@k | mean recall | note |
|---|---|---|---|---|---|---|
| structured | 27 | 25 | 1 | 0.926 | 0.919 |  |
| fts | 27 | 13 | 1 | 0.785 | 0.948 |  |
| hybrid | 27 | 27 | 1 | 1.0 | 0.993 |  |
| embeddings | 27 | 25 | 1 | 1.0 | 0.993 |  |

## Per query

| query | structured | fts | hybrid | embeddings | expected | note |
|---|---|---|---|---|---|---|
| the only honda | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 1 |  |
| toyota must not surface the honda | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 14 | the CR-V's title says 'Toyota Service History' |
| white suv under $20k (the PDF's example) | pass p@k 1.0 r 0.81 rank 1 | FAIL p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 0.81 rank 1 | FAIL p@k 1.0 r 0.81 rank 1 | 16 | one white SUV (Bestune T99) is priced under AED 73k, two are over, the rest state no price |
| range rover under 150k | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.8 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 5 |  |
| cheapest mercedes | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 37 |  |
| electric cars | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.6 r 1.0 rank 2 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 6 |  |
| under 2000 a month | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.6 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 171 |  |
| seven seater | FAIL p@k 0.0 r 0.0 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 7 |  |
| brand new cars | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.6 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 16 | brand new tyres are not a brand new car |
| gcc 2023 or newer with warranty | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.2 r 1.0 rank 5 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 18 |  |
| corolla (arabic only listing) | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 1 |  |
| patrol incl. arabic only rows | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.8 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 4 |  |
| mazda 3 (int-typed model cell) | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 1 |  |
| dbx 707 (int-typed trim cell) | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 1 |  |
| phantom (shared dealer paragraph) | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 2 |  |
| merc c300 via aliases | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 10 |  |
| convertibles | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.8 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 14 |  |
| export only excluded from bookable stock | n/a | n/a | n/a | n/a |  | not applicable: no listing here matches the expectation |
| panoramic roof by keyword | FAIL p@k 0.0 r 0.0 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 31 |  |
| mileage under 50k | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 50 |  |
| diesel | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 1.0 r 0.6 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 5 |  |
| japanese spec | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 21 |  |
| dubizzle inspected | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.2 r 1.0 rank 4 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 10 |  |
| 2015 to 2017 | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.0 r 0.0 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 28 |  |
| listed between 50k and 100k | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.4 r 1.0 rank 4 | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 1.0 r 1.0 rank 1 | 158 |  |
| bentley continental incl. flying spur trim | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.8 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 4 |  |
| g wagon alias | pass p@k 1.0 r 1.0 rank 1 | FAIL p@k 0.4 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 2 |  |
| velar by model alias | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | pass p@k 1.0 r 1.0 rank 1 | 1 |  |

Precision at k is over the shown page. Recall compares the full match count with the expected set. A pass also honours each case's extra check, for example that the relaxation ladder ran or the priced car ranks first.
