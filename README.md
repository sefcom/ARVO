# ARVO

## Abstract

Achieving reproducibility, quantity, and diversity in vulnerability datasets has long been viewed as an inherent three-way trade-off, where improving one dimension often comes at the cost of the others. In practice, reproducibility has been the dimension most often neglected. This has limited what can be automatically extracted from historical bug datasets, and has reduced their utility for downstream security research.

In this work, we propose a method to produce a new security dataset which ensures reproducibility for diverse vulnerabilities at scale by identifying the key obstacles to large-scale bug reproduction and addressing them with general solutions. Using this method, we introduce full reproducibility to the largest open source software vulnerability dataset (OSS-Fuzz) and construct the ARVO dataset (an Atlas of Reproducible Vulnerabilities in Open-source software). ARVO is a large-scale dataset consisting of over 6,100 real-world vulnerabilities across 311 projects. Focusing on reproducibility, ARVO differs from existing datasets by providing each vulnerability in a form that can be consistently rebuilt, triggered, and analyzed across versions. Reproducibility also enables automatic identification of the corresponding patch for each vulnerability and supports direct interaction with vulnerabilities after code changes, capabilities that existing large-scale datasets do not provide. In our evaluation, ARVO successfully reproduces 81% of vulnerabilities and achieves 89.4% accuracy on the located patches. We also discuss ARVO's influence on both upstream practices and downstream security research.

## Artifact

- Source code: https://github.com/n132/arvo
- Dataset: https://github.com/n132/ARVO-Meta
- Paper data: `./data/` contains the raw evaluation logs, metadata, and analysis scripts backing the paper's results.

## Paper

Accepted at IEEE European Symposium on Security and Privacy (EuroS&P) 2026 

[ARVO paper (PDF)](./2026155803.pdf)

> To appear. Wait for IEEE Xplore to be ready.

```bibtex
@inproceedings{mei2026arvo,
  title     = {{ARVO}: Atlas of Reproducible Vulnerabilities for Open-Source Software},
  author    = {Mei, Xiang and Del Castillo, Jordi and Singh Singaria, Pulkit and Xi, Haoran and Benchikh, Abdelouahab and Bao, Tiffany and Wang, Ruoyu and Shoshitaishvili, Yan and Doup\'{e}, Adam and Pearce, Hammond and Dolan-Gavitt, Brendan},
  booktitle = {IEEE European Symposium on Security and Privacy (EuroS\&P)},
  year      = {2026}
}
```
