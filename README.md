# ARVO

## Abstract

Achieving reproducibility, quantity, and diversity in vulnerability datasets has long been viewed as an inherent three-way trade-off, where improving one dimension often comes at the cost of the others, and reproducibility is the one most often neglected. This lack of reproducibility limits what can be extracted from historical bugs and reduces their value for security research. This work proposes a new form of security dataset that ensures reproducibility for diverse vulnerabilities at scale by identifying the key obstacles to large-scale bug reproduction and addressing them with general solutions.

To validate these solutions, we introduce full reproducibility to the largest open source software vulnerability dataset (OSS-Fuzz) and construct the ARVO dataset (an **A**tlas of **R**eproducible **V**ulnerabilities in **O**pen-source software). As a result, ARVO provides a large-scale dataset of over 6,100 real-world vulnerabilities across 311 projects. With reproducibility, ARVO differs from existing datasets by providing each vulnerability in a form that can be consistently rebuilt, triggered, and analyzed across versions. Reproducibility also enables automatic identification of the corresponding patch for each vulnerability and supports direct interaction with vulnerabilities after code changes, capabilities that existing large-scale datasets do not provide. In our evaluation, ARVO successfully reproduces 81% of vulnerabilities and achieves 89.4% accuracy on the located patches. We also discuss ARVO's influence on both upstream practices and downstream security research.

## Artifact

- Source code: https://github.com/n132/arvo
- Dataset: https://github.com/n132/ARVO-Meta
- Paper: `data/paper.pdf` (TODO: add once camera-ready is finalized)
- Paper data: `./data/` contains the raw evaluation logs, metadata, and analysis scripts backing the paper's results.

## Paper

> **TODO**: add citation link / BibTeX entry once Euro S&P 2026 proceedings are published.
