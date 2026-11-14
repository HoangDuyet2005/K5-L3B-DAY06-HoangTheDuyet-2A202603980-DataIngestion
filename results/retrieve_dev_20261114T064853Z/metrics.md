# Automatic retrieval metrics (20261114T064853Z)

Model `google/embeddinggemma-2`, 768-d, top-3, exact cosine search. Hit = gold source + PDF page + full evidence quote inside the chunk. Human coherence / metadata / grounding labels are separate (see *_template.csv).

| Strategy | Split | Hit@1 | Evidence Hit@3 | Page Hit@3 (diagnostic) | Filter compliance top-3 |
|---|---|---|---|---|---|
| A | dev | 9/15 | 10/15 | 15/15 | 1/2 |
| B | dev | 11/15 | 13/15 | 14/15 | 0/2 |
| C | dev | 11/15 | 14/15 | 15/15 | 2/2 |
