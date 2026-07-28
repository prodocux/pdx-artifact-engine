# Datasets

Training data should be trace-based, not generic prompt data.

Each trace should show how a user request becomes:

- a plan
- expert selection
- skill calls
- skill outputs
- verification results
- repair decisions
- final artifact summary

Initial sources:

- ProDocuX PIF runs in the parent workspace
- synthetic tool-routing traces
- synthetic FreeCAD/Blender 3D traces
- negative examples requiring human input

Do not commit customer data or regulated confidential source documents.

