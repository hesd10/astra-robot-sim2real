# Attribution and licensing

[XLeRobot](https://github.com/Vector-Wangel/XLeRobot) is the upstream embodiment. Its Apache-2.0 license from the source checkout is preserved in [XLeRobot-Apache-2.0.txt](../licenses/XLeRobot-Apache-2.0.txt).

Simulation uses MuJoCo, NumPy, Pillow, and PyOpenGL. Hardware uses the Feetech servo SDK, serial communication, and camera libraries. Requirements files identify these dependencies. [The asset manifest](../sim/ASSET_MANIFEST.json) records source filenames and hashes for robot meshes and scene assets.

Included upstream licenses and notices apply to their respective components. Project-wide licensing has not yet been specified. The supplied D3 demonstration is included with the operator's authorization and with audio removed.

The [bibliography](../paper/references.bib) cites primary work on code-based robot control, grounded skill selection, executable memory, skill acquisition, and sim2real. [The citation audit](../results/citation-audit.json) records the source checks.

The manuscript includes the unmodified [unsrtnat.bst](../paper/unsrtnat.bst) bibliography style by Patrick W. Daly (1993–2007), from [CTAN](https://mirrors.ctan.org/macros/latex/contrib/natbib/unsrtnat.bst). Its copyright and [LaTeX Project Public License](https://www.latex-project.org/lppl/) notice are preserved in the file. The style orders references by first citation and supports offline compilation.
