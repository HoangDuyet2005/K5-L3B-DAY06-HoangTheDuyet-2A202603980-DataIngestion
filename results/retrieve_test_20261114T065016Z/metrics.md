# Automatic retrieval metrics (20261114T065016Z)

Model `google/embeddinggemma-2`, 768-d, top-3, exact cosine search. Hit = gold source + PDF page + full evidence quote inside the chunk. Human coherence / metadata / grounding labels are separate (see *_template.csv).

| Strategy | Split | Hit@1 | Evidence Hit@3 | Page Hit@3 (diagnostic) | Filter compliance top-3 |
|---|---|---|---|---|---|
| A | test | 3/5 | 4/5 | 5/5 | 1/2 |
| B | test | 4/5 | 4/5 | 5/5 | 0/2 |
| C | test | 4/5 | 5/5 | 5/5 | 2/2 |
