# LLM-Driven NPC Scheduling in Structured Game Worlds

**Peter Husen | Student Number: 233900**  
Breda University of Applied Sciences — Data Science & AI  
Supervisor: Edirlei Soares de Lima

This repository contains the implementation and evaluation pipeline for the graduation project *LLM-Driven NPC Scheduling in Structured Game Worlds*. The system uses large language models to generate autonomous NPC action schedules at runtime in a zombie apocalypse survival game, replacing hand-authored behaviour trees and finite state machines with a pipeline driven by natural language character descriptions, a structured world state, an action library, and a set of world rules.

---

## Repository Structure

```
├── prompts.md                                   # System and user prompt templates
├── json_inputs/
│   ├── action_library.json                      # Available NPC actions with parameter definitions
│   ├── world_rules.json                         # Full world rules (16 entries)
│   ├── world_rules_minimal.json                 # Minimal world rules (10 physically-enforced constraints)
│   └── characters.json                          # Unified NPC character descriptions (8 NPCs)
├── api/
│   ├── npc_generation.py                        # FastAPI backend — /generate and /validate endpoints
│   ├── quest_generation.py                      # Shared pipeline structure (not part of this project's evaluation)
│   └── .env_example.env                         # Environment variable template
└── evaluation scripts/
    ├── run.py                                   # Evaluation runner — multi-model, multi-scenario, incremental xlsx saving
    ├── validator.py                             # Deterministic rule-based validator (ROOT/CASCADING classification)
    ├── generate_qualitative_sample.py           # Stratified weighted sampler for qualitative review
    └── z_value_calculation.py                   # Two-proportion z-test for full vs minimal ruleset comparison
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

---

## API

The generation service is implemented as a game-agnostic REST API using FastAPI, decoupling the LLM backend from the game client.

**Endpoints**

- `POST /generate` — accepts a character description, world state, action library, and world rules; returns a generated schedule for a single NPC
- `POST /validate` — accepts an existing schedule and an updated world state; returns the schedule unchanged if still executable, or a revised schedule if not
- `GET /health` — returns service status and active model

**Prompts**

`prompts.md` contains the prompt templates used by the generation and validation endpoints — `GENERATE_PROMPT_TEMPLATE` and `VALIDATE_PROMPT_TEMPLATE` — alongside the shared `STRICT_RULES` block. These are the same templates defined in `npc_generation.py` and are provided here as a readable reference for inspecting or modifying prompt logic without opening the API code.

**Setup**

Create a `.env` file in the `api/` directory using the provided template:

```bash
cp api/.env_example.env api/.env
```

Then edit `api/.env` with your server details:

```
LLM_API_BASE=https://your-llm-server/v1
BUAS_LLM_KEY=your_api_key_here
```

Start the backend:

```bash
uvicorn api.npc_generation:app --reload --port 8001
```

---

## Running the Evaluation Pipeline

To reproduce the evaluation results from the paper:

```bash
cd "evaluation scripts"
python run.py
```

This runs all configured models across all five scenarios under both ruleset conditions (full and minimal), generating 400 schedules per model per ruleset (800 per model, 3,200 total). Results are saved incrementally after each NPC to prevent data loss on server interruption.

To generate the qualitative sample from evaluation outputs:

```bash
cd "evaluation scripts"
python generate_qualitative_sample.py
```

This produces a stratified, diversity-weighted 20% sample (640 schedules) across all four models for human review.

To reproduce the statistical analysis:

```bash
cd "evaluation scripts"
python z_value_calculation.py
```

This calculates the two-proportion z-test comparing full versus minimal ruleset validity rates for all four models.

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

The full academic paper is available in the accompanying thesis submission.
