# Manuscript

**Robot Manipulation with GPT-6-Astra: Body Knowledge, Experience Reuse, Emergent Skills, and Sim2Real Transfer**

| File | Contents |
|---|---|
| [main.pdf](main.pdf) | Reviewed English manuscript, 23 pages |
| [main.tex](main.tex) | Main LaTeX source |
| [references.bib](references.bib) | Bibliography |
| [task-prompts.tex](task-prompts.tex) | Complete task prompts reproduced in Appendix D |
| [arxiv-source.tar.gz](arxiv-source.tar.gz) | Self-contained source bundle with figures and compiled bibliography |

The paper presents the simulation and real-robot results, observed use of geometry and experience, local-skill evaluation, and sim2real discussion. Appendices A–E contain the complete fixed-start results, skill diagnostics, exploratory studies, task prompts, and API/material provenance.

## Build

From the repository root, with Tectonic or a standard LaTeX/BibTeX installation:

```bash
bash paper/build.sh
```

The build uses the included PDF figures and requires no shell escape. The [reproduction guide](../docs/REPRODUCING.md) documents figure generation and the source-bundle check. The [final manuscript audit](../results/final-manuscript-audit.json) records numerical, citation, and compilation checks, including matching page text and bibliography from an independent build of the source archive.
