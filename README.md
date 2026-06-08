The prompts.md file contains the generation and validation prompt used for the generation of NPC schedules.

The json inputs folder contains the action library, world state and characters used for the project.

The evaluation scripts folder contains scripts contained for evaluation of the results
run.py runs the evaluation based on npc_generation.py and validator.py
validator.py contains the binary validation logic
z-value_calculation.ipynb is used to contain statistical significance of model difference
generate_qualitative_sample.py splits the total result from run.py up into a 20% sample for qualitative assessment.

The api folder contains scripts for the npc_generation.py, containing logic for the game as well as hosting the FastAPI that run.py connects to.