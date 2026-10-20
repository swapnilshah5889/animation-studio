# Minimal .sif examples (verified with the Synfig 1.5.5 CLI)

| File | Shows |
|---|---|
| `bones_arm_minimal.sif` (+ `upper.png`, `forearm.png`) | A 2-bone arm (`<bones>` block, `bone_root`, parent links, animated bone angles) driving two PNG parts through `bone_link` on each part group's `transformation`. The skeleton layer is excluded from rendering. |
| `deform_limb.sif` (+ `limb.png`) | A Skeleton Deformation layer bending one image at an elbow (rest and pose bone pairs). |

Written during Step 1 research; explained in `docs/learning/synfig-format.md` ("Bones").
`tests/test_sif_examples.py` renders both and checks the forearm tip lands where forward kinematics
predicts.
