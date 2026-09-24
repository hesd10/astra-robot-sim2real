"""Transcribe the frozen task prompts into LaTeX, changing typography only."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ("Simulation approach and pressing", "app:prompt-sim",
     "sim/studies/body-experience-001/common/PROMPT.md",
     "The fixed-start and displaced-start studies use this common task prompt. "
     "The condition-specific \\texttt{PRIOR.md} lists the authorized materials defined in Table~\\ref{tab:design}."),
    ("Local-skill evaluation", "app:prompt-local",
     "sim/studies/local-feedback-001/inputs/FREE/PROMPT.md",
     "FREE, STEP, and LOOP use identical task prompts. In STEP and LOOP, "
     "\\texttt{PRIOR.md} additionally points to \\path{skill/local-press/SKILL.md}; "
     "the agent can read the supplied routine or write its own code."),
    ("Real-robot evaluation", "app:prompt-real",
     "experiments/real/common/PROMPT.md",
     "Conditions A--D share this task prompt; their authorized materials differ as in Table~\\ref{tab:design}. "
     "The prompt below requests physical button depression. In the executed hardware trials, "
     "the button's stiffness led the operator to accept gripper-tip contact with the target button as success. "
     "The reported real-robot results use that contact criterion; the original prompt is reproduced unchanged."),
]
ESCAPE = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
          "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
          "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "±": r"$\pm$"}
def escape(text):
    return "".join(ESCAPE.get(ch, ch) for ch in text)

out = ["% Generated from archived PROMPT.md files. Do not edit this transcription."]
provenance = []
for title, label, path, explanation in SOURCES:
    src = ROOT / path
    text = src.read_text().strip()
    out += [r"\par\noindent\begin{minipage}{\linewidth}",
            rf"\subsection{{{title}}}\label{{{label}}}", explanation,
            r"\begin{list}{}{\leftmargin=1em\rightmargin=1em}\item[]\small", escape(text),
            r"\end{list}", r"\end{minipage}\par\addvspace{1em}", ""]
    provenance.append({"path": path, "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                       "latex_label": label, "words": len(text.split())})
assert len({(ROOT / f"sim/studies/local-feedback-001/inputs/{c}/PROMPT.md").read_bytes()
            for c in ["FREE", "STEP", "LOOP"]}) == 1
(ROOT / "paper/task-prompts.tex").write_text("\n".join(out) + "\n")
(ROOT / "results/prompt-provenance.json").write_text(json.dumps({
    "transcription": "Complete prompt text; LaTeX escaping and typesetting only.",
    "sources": provenance}, indent=2) + "\n")
print("Transcribed the three experimental task prompts.")
