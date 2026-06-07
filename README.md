# LLM-Driven NPC Scheduling in Structured Game Worlds

**Peter Husen | Student Number: 233900**  
Breda University of Applied Sciences — Data Science & AI  
Supervisor: Edirlei Soares de Lima

This repository contains the full implementation and evaluation pipeline for the graduation project *LLM-Driven NPC Scheduling in Structured Game Worlds*. The system uses large language models to generate autonomous NPC action schedules at runtime in a zombie apocalypse survival game, replacing hand-authored behaviour trees and finite state machines with a pipeline driven by natural language character descriptions, a structured world state, an action library, and a set of world rules.

---

## Repository Structure

```
LLM-driven-NPC-scheduling/
│
├── api/                                    # FastAPI backend and evaluation pipeline
│   ├── npc_generation.py                   # FastAPI backend — /generate and /validate endpoints
│   ├── validator.py                        # Deterministic rule-based validator (ROOT/CASCADING classification)
│   ├── run.py                              # Evaluation runner — multi-model, multi-scenario, incremental xlsx saving
│   ├── generate_qualitative_sample.py      # Stratified weighted sampler for qualitative review
│   ├── z-value_calculation.py              # Two-proportion z-test for full vs minimal ruleset comparison
│   ├── quest_generation.py                 # Shared pipeline structure (not part of this project's evaluation)
│   └── .env.example                        # Environment variable template
│
├── data/                                   # All game world definition files
│   ├── characters.json                     # Unified NPC character descriptions (8 NPCs)
│   ├── action_library.json                 # Available NPC actions with parameter definitions
│   ├── world_rules.json                    # Full world rules (16 entries)
│   ├── world_rules_minimal.json            # Minimal world rules (10 physically-enforced constraints)
│   ├── world_state.json                    # Baseline world state
│   ├── chapters.json                       # Game chapter definitions
│   ├── scenario_1_village_safe.json
│   ├── scenario_2_keys_available.json
│   ├── scenario_3_village_safe_keys_available.json
│   └── scenario_4_high_threat.json
│
├── levels/                                 # Game level files (LÖVE2D)
├── images/                                 # Game image assets
├── audio/                                  # Game audio assets
├── libs/                                   # Game library dependencies
│
├── outputs/                                # Evaluation results — 8 xlsx files (4 models × 2 rulesets)
├── scoring/                                # Qualitative sample workbooks
│   ├── qualitative_sample_640.xlsx         # Blank scoring sheet (640 samples)
│   └── qualitative_sample_640_scored.xlsx  # Completed qualitative assessment
│
├── docs/                                   # Paper figures and architecture diagrams
│   ├── pipeline_architecture.png           # Figure 1 — Schedule generation pipeline
│   ├── npc_lifecycle.png                   # Figure 2 — Full NPC schedule lifecycle
│   ├── marcus_navigating.png               # Figure 3a — Marcus navigating to wood resource
│   └── marcus_dialogue.png                 # Figure 3b — Marcus collecting wood with dialogue
│
├── README.md
├── requirements.txt
├── CHANGELOG.md
└── .gitignore
```


---

## How It Works

### Schedule Generation Pipeline

The scheduling pipeline replaces hand-authored NPC behaviour with runtime LLM generation:

1. At game start, the game engine enqueues all NPCs and begins dispatching generation requests to the FastAPI backend one at a time
2. For each NPC, the backend combines four inputs into a prompt: the NPC's character description, the current world state (serialised JSON), the action library, and the world rules
3. The LLM generates a candidate action schedule as a structured JSON list of actions
4. The schedule is passed to `validator.py`, which checks each action against deterministic preconditions — movement connectivity, inventory requirements, location conditions
5. A valid schedule is returned to the game for execution; an invalid one triggers a retry (up to three attempts)
6. Once the schedule completes, the NPC is re-queued after a short cooldown and the cycle repeats

### How NPCs Behave In-Game

Once a schedule is returned, the game's `NPCScheduler` takes ownership of it and executes each action in sequence. Completion is checked differently per action type — a MOVE action completes when the NPC arrives at the destination, while other actions resolve through their own condition checks. As each action completes, the world state updates automatically, so subsequent NPC schedules reflect the current state of the world rather than a snapshot from the start of the cycle.

If the world state changes while an NPC's schedule is in progress — for example, the player picks up an item the NPC was planning to collect — the game calls the `/validate` endpoint to check whether the remaining steps are still executable. If not, a revised schedule is returned in its place.

Players can observe NPCs executing their schedules autonomously, interact with them through dialogue, or intervene by collecting items or modifying locations. These changes are automatically reflected in the next generation cycle.

---

## Installation and Setup

### 1. Install LÖVE2D (Game Engine)

Download and install LÖVE2D from [https://love2d.org](https://love2d.org).

**Add LÖVE2D to your system PATH (Windows):**

1. Press the Windows key and type **Edit the system environment variables**, then press Enter
2. Click **Environment Variables**
3. Under **System variables**, select **Path** and click **Edit**
4. Click **New** and add the path to your LÖVE2D installation (default: `C:\Program Files\LOVE`)
5. Click **OK** on all dialogs to save

To verify the installation, open a terminal and run:
```bash
love --version
```

### 2. Install Python Dependencies

Python 3.10 or higher is recommended.

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the `api/` directory using the provided template:

```bash
cp api/.env.example api/.env
```

Then edit `api/.env` with your server details:

```
LLM_API_BASE=https://your-llm-server/v1
BUAS_LLM_KEY=your_api_key_here
```

Replace the values with your server URL and API key. For BUas students: contact your supervisor for the correct values. Never commit the `.env` file — it is listed in `.gitignore` by default.

### 4. Select Models

**For the game (npc_generation.py):**  
Open `api/npc_generation.py` and set the `OPENAI_MODEL` variable to whichever model you want NPCs to use during gameplay:

```python
OPENAI_MODEL = "Qwen3.6-27B"
```

Available model names depend on what is hosted on your inference server.

**For the evaluation pipeline (run.py):**  
Open `api/run.py` and edit the `MODELS` list to include whichever models you want to evaluate:

```python
MODELS = [
    "GPT-OSS-120B",
    "Qwen3.5-122B",
    "Qwen3.6-27B",
    "Llama3.3-70B",
]
```

Remove any models you do not want to run.

### 5. Start the FastAPI Backend

```bash
uvicorn api.npc_generation:app --reload --port 8001
```

The backend exposes two endpoints:
- `POST /generate` — generates a schedule for a single NPC
- `POST /validate` — validates and optionally revises an in-progress schedule
- `GET /health` — returns service status and active model

Keep this terminal open while the game is running.

### 6. Launch the Game

**Option A — VS Code (recommended):**  
Open the repository in VS Code and press `Ctrl+Shift+B` to run the default build task, which launches the game using LÖVE2D.

**Option B — Terminal:**
```bash
love .
```

Run this from the repository root. Ensure the FastAPI backend is running first so NPCs can request schedules at startup.

---

## Running the Evaluation Pipeline

To reproduce the evaluation results from the paper:

```bash
cd api
python run.py
```

This runs all configured models across all five scenarios under both ruleset conditions (full and minimal), generating 400 schedules per model per ruleset (800 per model and 3,200 total across all four models). Results are saved incrementally to `outputs/` after each NPC to prevent data loss on server interruption.

The `DATA_DIR` variable in `run.py` points to `../data` by default. Scenario filenames are configured in the `SCENARIOS` list at the top of the file.

To generate the qualitative sample from evaluation outputs:

```bash
cd api
python generate_qualitative_sample.py
```

This produces `scoring/qualitative_sample_640.xlsx` with a stratified, diversity-weighted 20% sample (640 schedules) across all four models. Edit the `EVAL_FILES` dictionary at the top of the script to point to your actual output files.

To reproduce the statistical analysis:

```bash
cd api
python z-value_calculation.py
```

Open `api/z-value_calculation.py` in Jupyter and run all cells. This calculates the two-proportion z-test comparing full versus minimal ruleset validity rates for all four models.

---

## Models Evaluated

| Model | Provider | Type | Total Parameters | Active Parameters |
|---|---|---|---|---|
| Qwen3.5-122B-A10B | Alibaba Cloud | MoE | 122B | 10B |
| Qwen3.6-27B | Alibaba Cloud | Dense | 27B | 27B |
| GPT-OSS-120B | OpenAI | MoE | 117B | ~5B |
| Llama-3.3-70B-Instruct | Meta | Dense | 70B | 70B |

All models were hosted on the BUas inference server (AMD EPYC 9555, 1.5 TB RAM, 4× NVIDIA RTX PRO 6000 Blackwell).

---

## Key Results

| Model | Rule Validity (Full) | Rule Validity (Minimal) | Avg Steps | Avg Latency |
|---|---|---|---|---|
| GPT-OSS-120B | 96.8% | 96.7% | 3.32 | 4.95s |
| Qwen3.6-27B | 94.2% | 94.8% | 2.20 | 4.61s |
| Qwen3.5-122B-A10B | 87.5% | 84.5% | 4.17 | 3.48s |
| Llama-3.3-70B-Instruct | 14.7% | 14.2% | 7.76 | 6.58s |

The dominant failure mode across models was world-state reasoning rather than rule complexity. Ruleset specification depth had no statistically significant effect on validity for any model (two-proportion z-test, all p > 0.05).

---

## Paper

The full academic paper is available at: `[link to paper]`

---

## Licence

The game prototype is built on LÖVE2D (MIT licence) and adapts prior work by Lima et al. (2014, 2019, 2022b).  
All four evaluated models are released under open licences (Apache 2.0 or Llama 3.3 Community Licence).  
This repository is released for academic and research purposes.

---

## Citation

```
Husen, P. (2026). LLM-Driven NPC Scheduling in Structured Game Worlds.
Breda University of Applied Sciences.
```
