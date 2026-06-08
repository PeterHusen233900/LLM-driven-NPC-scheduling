"""
validator.py — Rule-Based Schedule Validator
---------------------------------------------
Validates a generated NPC schedule against the world state using strict,
deterministic rules derived from the action library.

Violations are classified as either ROOT (genuine precondition failure) or
CASCADING (caused by a prior failed step not applying its effects).

World state format expected:
{
  "world_state": {
    "player":      { "location": str, "conditions": [...], "inventory": [...] },
    "npcs":        [ { "name": str, "location": str, "conditions": [...], "inventory": [...] } ],
    "locations":   [ { "name": str, "type": str, "conditions": [...] } ],
    "connections": [ { "from": str, "to": str } ],
    "items":       [ { "name": str, "type": str, "location": str | null } ],
    "objects":     [ { "name": str, "state": str, "location": str } ]
  }
}
"""

from __future__ import annotations
from dataclasses import dataclass, field
from copy import deepcopy
import re as _re


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    step:       int
    action:     str
    parameters: list[str]
    violations: list[str]
    applied:    bool
    cascading:  bool = False   # True if violation is caused by a prior failed step

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    @property
    def violation_type(self) -> str:
        if self.passed:
            return "OK"
        return "CASCADING" if self.cascading else "ROOT"


@dataclass
class ValidationReport:
    npc:          str
    valid:        bool
    step_results: list[StepResult] = field(default_factory=list)

    @property
    def root_violations(self) -> list[StepResult]:
        return [r for r in self.step_results if not r.passed and not r.cascading]

    @property
    def cascading_violations(self) -> list[StepResult]:
        return [r for r in self.step_results if not r.passed and r.cascading]

    @property
    def violations(self) -> list[tuple[int, str, list[str]]]:
        return [
            (r.step, r.action, r.violations)
            for r in self.step_results if not r.passed
        ]

    def summary(self) -> str:
        root = len(self.root_violations)
        casc = len(self.cascading_violations)
        lines = [f"Validation report for {self.npc}: {'VALID' if self.valid else 'INVALID'}"]
        if not self.valid:
            lines.append(f"  {root} root violation(s), {casc} cascading violation(s)")
        for r in self.step_results:
            if not r.passed:
                tag = "[CASCADING]" if r.cascading else "[ROOT]"
                lines.append(f"  Step {r.step} [{r.action}] {tag}:")
                for v in r.violations:
                    lines.append(f"    - {v}")
        if self.valid:
            lines.append("  All steps passed.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# World state helpers
# ---------------------------------------------------------------------------

def _ws(ws: dict) -> dict:
    return ws.get("world_state", ws)


def _get_entity(ws: dict, name: str) -> dict | None:
    w = _ws(ws)
    if name == "player":
        return w.get("player")
    for npc in w.get("npcs", []):
        if npc["name"].lower() == name.lower():
            return npc
    return None


def _location(ws: dict, entity_name: str) -> str | None:
    e = _get_entity(ws, entity_name)
    return e["location"] if e else None


def _inventory(ws: dict, entity_name: str) -> list[str]:
    e = _get_entity(ws, entity_name)
    return e.get("inventory", []) if e else []


def _has(ws: dict, entity_name: str, item_name: str) -> bool:
    return item_name in _inventory(ws, entity_name)


def _conditions(ws: dict, entity_name: str) -> list[str]:
    e = _get_entity(ws, entity_name)
    return e.get("conditions", []) if e else []


def _has_condition(ws: dict, entity_name: str, condition: str) -> bool:
    return condition in _conditions(ws, entity_name)


def _get_location(ws: dict, loc_name: str) -> dict | None:
    for loc in _ws(ws).get("locations", []):
        if loc["name"].lower() == loc_name.lower():
            return loc
    return None


def _location_conditions(ws: dict, loc_name: str) -> list[str]:
    loc = _get_location(ws, loc_name)
    return loc.get("conditions", []) if loc else []


def _is_locked(ws: dict, loc_name: str) -> bool:
    return "locked" in _location_conditions(ws, loc_name)


def _is_interior(ws: dict, loc_name: str) -> bool:
    loc = _get_location(ws, loc_name)
    return loc.get("type", "interior") == "interior" if loc else True


def _path_exists(ws: dict, from_loc: str, to_loc: str) -> bool:
    for conn in _ws(ws).get("connections", []):
        a, b = conn["from"].lower(), conn["to"].lower()
        if (a == from_loc.lower() and b == to_loc.lower()) or \
           (a == to_loc.lower()   and b == from_loc.lower()):
            return True
    return False


def _get_item(ws: dict, item_name: str) -> dict | None:
    for item in _ws(ws).get("items", []):
        if item["name"].lower() == item_name.lower():
            return item
    return None


def _item_location(ws: dict, item_name: str) -> str | None:
    item = _get_item(ws, item_name)
    if item:
        return item.get("location")
    w = _ws(ws)
    if item_name in w.get("player", {}).get("inventory", []):
        return "__inventory__"
    for npc in w.get("npcs", []):
        if item_name in npc.get("inventory", []):
            return "__inventory__"
    return None


def _item_at_location(ws: dict, item_name: str, loc_name: str) -> bool:
    item = _get_item(ws, item_name)
    return bool(item and (item.get("location") or "").lower() == loc_name.lower())


def _get_object(ws: dict, obj_name: str) -> dict | None:
    for obj in _ws(ws).get("objects", []):
        if obj["name"].lower() == obj_name.lower():
            return obj
    return None


# ---------------------------------------------------------------------------
# Effect helpers (mutate working copy)
# ---------------------------------------------------------------------------

def _set_location(ws: dict, entity_name: str, loc: str):
    e = _get_entity(ws, entity_name)
    if e:
        e["location"] = loc


def _add_to_inventory(ws: dict, entity_name: str, item_name: str):
    e = _get_entity(ws, entity_name)
    if e and item_name not in e.get("inventory", []):
        e.setdefault("inventory", []).append(item_name)
    item = _get_item(ws, item_name)
    if item:
        item["location"] = None


def _remove_from_inventory(ws: dict, entity_name: str, item_name: str):
    e = _get_entity(ws, entity_name)
    if e and item_name in e.get("inventory", []):
        e["inventory"].remove(item_name)


def _consume_item(ws: dict, entity_name: str, item_name: str):
    _remove_from_inventory(ws, entity_name, item_name)
    item = _get_item(ws, item_name)
    if item:
        item["location"] = None


def _add_location_condition(ws: dict, loc_name: str, condition: str):
    loc = _get_location(ws, loc_name)
    if loc and condition not in loc.get("conditions", []):
        loc.setdefault("conditions", []).append(condition)


def _remove_location_condition(ws: dict, loc_name: str, condition: str):
    loc = _get_location(ws, loc_name)
    if loc and condition in loc.get("conditions", []):
        loc["conditions"].remove(condition)


def _add_entity_condition(ws: dict, entity_name: str, condition: str):
    e = _get_entity(ws, entity_name)
    if e and condition not in e.get("conditions", []):
        e.setdefault("conditions", []).append(condition)


def _remove_entity_condition(ws: dict, entity_name: str, condition: str):
    e = _get_entity(ws, entity_name)
    if e and condition in e.get("conditions", []):
        e["conditions"].remove(condition)


# ---------------------------------------------------------------------------
# Action checkers
# ---------------------------------------------------------------------------

def _check_move(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 3:
        return ["MOVE requires parameters: actor, from, to"], None
    from_loc, to_loc = params[1], params[2]
    if _location(ws, actor) != from_loc:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{from_loc}'")
    if _is_locked(ws, from_loc):
        viols.append(f"Cannot move FROM locked location '{from_loc}'")
    if _is_locked(ws, to_loc):
        viols.append(f"Cannot move TO locked location '{to_loc}'")
    if not _path_exists(ws, from_loc, to_loc):
        viols.append(f"No path from '{from_loc}' to '{to_loc}'")
    def apply(ws): _set_location(ws, actor, to_loc)
    return viols, (apply if not viols else None)


def _check_pickup(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 3:
        return ["PICKUP requires parameters: actor, item, place"], None
    item, place = params[1], params[2]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if not _item_at_location(ws, item, place):
        viols.append(f"'{item}' is not at '{place}' (location: '{_item_location(ws, item)}')")
    def apply(ws): _add_to_inventory(ws, actor, item)
    return viols, (apply if not viols else None)


def _check_drop(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 3:
        return ["DROP requires parameters: actor, item, place"], None
    item, place = params[1], params[2]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if not _has(ws, actor, item):
        viols.append(f"{actor} does not have '{item}' in inventory")
    def apply(ws):
        _remove_from_inventory(ws, actor, item)
        it = _get_item(ws, item)
        if it:
            it["location"] = place
    return viols, (apply if not viols else None)


def _check_give_item(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 4:
        return ["GIVE_ITEM requires parameters: actor, item, target, place"], None
    item, target, place = params[1], params[2], params[3]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if _location(ws, target) != place:
        viols.append(f"Target '{target}' is not at '{place}'")
    if not _has(ws, actor, item):
        viols.append(f"{actor} does not have '{item}' in inventory")
    def apply(ws):
        _remove_from_inventory(ws, actor, item)
        _add_to_inventory(ws, target, item)
    return viols, (apply if not viols else None)


def _check_talk(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 3:
        return ["TALK requires parameters: actor, target, place, dialogue_content"], None
    target, place = params[1], params[2]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if _location(ws, target) != place:
        viols.append(f"Target '{target}' is not at '{place}'")
    return viols, (lambda ws: None)


def _check_unlock(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 3:
        return ["UNLOCK requires parameters: actor, key_item, target_place"], None
    key_item, target_place = params[1], params[2]
    if not _has(ws, actor, key_item):
        viols.append(f"{actor} does not have '{key_item}' in inventory")
    if not _is_locked(ws, target_place):
        viols.append(f"'{target_place}' is not locked")
    def apply(ws):
        _consume_item(ws, actor, key_item)
        _remove_location_condition(ws, target_place, "locked")
        _set_location(ws, actor, target_place)
    return viols, (apply if not viols else None)


def _check_repair(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 5:
        return ["REPAIR requires parameters: actor, toolkit_item, wood_item, target, place"], None
    toolkit, wood, target, place = params[1], params[2], params[3], params[4]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if place != "dock":
        viols.append(f"REPAIR must be performed at 'dock', not '{place}'")
    if not _has(ws, actor, toolkit):
        viols.append(f"{actor} does not have '{toolkit}' in inventory")
    if not _has(ws, actor, wood):
        viols.append(f"{actor} does not have '{wood}' in inventory")
    obj = _get_object(ws, target)
    if not obj:
        viols.append(f"Object '{target}' not found in world state")
    elif obj.get("state") != "broken":
        viols.append(f"Object '{target}' is not broken (state: '{obj.get('state')}')")
    def apply(ws):
        _consume_item(ws, actor, toolkit)
        _consume_item(ws, actor, wood)
        o = _get_object(ws, target)
        if o:
            o["state"] = "fixed"
    return viols, (apply if not viols else None)


def _check_turn_power_on(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 4:
        return ["TURN_POWER_ON requires parameters: actor, fuse_item, place, target_place"], None
    fuse, place, target_place = params[1], params[2], params[3]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if place != "powerstation":
        viols.append(f"TURN_POWER_ON must be performed at 'powerstation', not '{place}'")
    if not _has(ws, actor, fuse):
        viols.append(f"{actor} does not have '{fuse}' in inventory")
    def apply(ws):
        _consume_item(ws, actor, fuse)
        _remove_location_condition(ws, target_place, "no_power")
        _add_location_condition(ws, target_place, "power_on")
    return viols, (apply if not viols else None)


def _check_fortify(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 3:
        return ["FORTIFY requires parameters: actor, wood_item, place"], None
    wood, place = params[1], params[2]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if not _has(ws, actor, wood):
        viols.append(f"{actor} does not have '{wood}' in inventory")
    if not _re.match(r"^wood_\d+$", wood):                          # ← NEW
        viols.append(f"FORTIFY item must be a wood item (got '{wood}')")  # ← NEW
    if not _is_interior(ws, place):
        viols.append(f"'{place}' is an exterior location and cannot be fortified")
    def apply(ws):
        _consume_item(ws, actor, wood)
        _add_location_condition(ws, place, "fortified")
    return viols, (apply if not viols else None)


def _check_synthesize_cure(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 2:
        return ["SYNTHESIZE_CURE requires parameters: actor, place"], None
    place = params[1]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    if place != "laboratory":
        viols.append(f"SYNTHESIZE_CURE must be performed at 'laboratory', not '{place}'")
    inv = _inventory(ws, actor)
    cure_samples = [i for i in inv if "cure_sample" in i.lower()]
    if not cure_samples:
        viols.append(f"{actor} does not have a cure_sample in inventory")
    if "power_on" not in _location_conditions(ws, place):
        viols.append(f"'{place}' does not have 'power_on' condition")
    if any("antidote" in i.lower() for i in inv):
        viols.append(f"{actor} already has an antidote in inventory")
    def apply(ws):
        inv = _inventory(ws, actor)
        samples = [i for i in inv if "cure_sample" in i.lower()]
        if samples:
            _consume_item(ws, actor, samples[0])
        e = _get_entity(ws, actor)
        if e:
            e.setdefault("inventory", []).append("antidote")
    return viols, (apply if not viols else None)


def _check_use_cure(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 3:
        return ["USE_CURE requires parameters: actor, item, target"], None
    item, target = params[1], params[2]
    if not _has(ws, actor, item):
        viols.append(f"{actor} does not have '{item}' in inventory")
    if _location(ws, actor) != _location(ws, target):
        viols.append(f"{actor} is at '{_location(ws, actor)}' but '{target}' is at '{_location(ws, target)}'")
    if not (_has_condition(ws, target, "infected") or _has_condition(ws, target, "injured")):
        viols.append(f"'{target}' is neither infected nor injured")
    def apply(ws):
        _consume_item(ws, actor, item)
        _remove_entity_condition(ws, target, "infected")
        _remove_entity_condition(ws, target, "injured")
        _add_entity_condition(ws, target, "healthy")
    return viols, (apply if not viols else None)


def _check_walk_around(actor: str, params: list[str], ws: dict):
    viols = []
    if len(params) < 2:
        return ["WALK_AROUND requires parameters: actor, place"], None
    place = params[1]
    if _location(ws, actor) != place:
        viols.append(f"{actor} is at '{_location(ws, actor)}', not '{place}'")
    return viols, (lambda ws: None)


# ---------------------------------------------------------------------------
# Action dispatcher
# ---------------------------------------------------------------------------

ACTION_CHECKERS = {
    "MOVE":            _check_move,
    "PICKUP":          _check_pickup,
    "DROP":            _check_drop,
    "GIVE_ITEM":       _check_give_item,
    "TALK":            _check_talk,
    "UNLOCK":          _check_unlock,
    "REPAIR":          _check_repair,
    "TURN_POWER_ON":   _check_turn_power_on,
    "FORTIFY":         _check_fortify,
    "SYNTHESIZE_CURE": _check_synthesize_cure,
    "USE_CURE":        _check_use_cure,
    "WALK_AROUND":     _check_walk_around,
}


# ---------------------------------------------------------------------------
# Step parser
# FIX 1: TALK dialogue strings may contain commas and internal quotes.
# We split on the first 3 commas only, then treat the remainder as a single
# dialogue argument. This applies to all actions but only matters for TALK
# since it is the only action whose final argument is free-form text.
# ---------------------------------------------------------------------------

def parse_step(step_str: str) -> tuple[str, list[str]] | None:
    """
    Parse a step string of the form ACTION(p0, p1, ...) into (action, params).

    For TALK specifically, only the first three commas are used as delimiters
    so that dialogue text containing commas (or quotes) does not break parsing.
    The fourth argument (dialogue content) is kept as a single string.
    All other actions are parsed with a simple comma split.
    """
    step_str = step_str.strip()
    if "(" not in step_str or not step_str.endswith(")"):
        return None

    action = step_str[:step_str.index("(")].strip().upper()
    inner  = step_str[step_str.index("(") + 1:-1]

    if action == "TALK":
        # Split on first 3 commas only: actor, target, place, <rest is dialogue>
        parts = inner.split(",", 3)
        params = [p.strip().strip('"').strip("'") for p in parts]
    else:
        params = [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]

    return action, params


# ---------------------------------------------------------------------------
# Cascading violation detection
# ---------------------------------------------------------------------------

def _is_cascading(step_result: StepResult, prior_failures: list[StepResult],
                  ws_before: dict) -> bool:
    """
    A violation is cascading if every violated precondition can be traced to
    a side-effect that a prior failed step was supposed to apply but didn't.

    For MOVE, two distinct location violations can be cascading:
      - "actor is at X, not FROM_LOC"  -> a prior step should have moved actor to FROM_LOC
      - "Cannot move FROM/TO locked location" -> a prior UNLOCK should have cleared the lock
      - "No path from ..." -> treated as a genuine topology failure (ROOT)

    missed_locations tracks (entity, expected_location) pairs, i.e. where a
    prior step's effect *would* have placed the actor. For a failed MOVE
    (actor, from, to), the missed location is the TO location (params[2]),
    because that is the effect that would have propagated forward.
    """
    if not prior_failures:
        return False

    # Collect what prior failed steps would have changed
    missed_locations:  set[tuple[str, str]] = set()   # (entity, location)
    missed_inventory:  set[tuple[str, str]] = set()   # (entity, item)
    missed_conditions: set[tuple[str, str]] = set()   # (place/entity, condition)

    for prior in prior_failures:
        action = prior.action
        params = prior.parameters

        if action == "MOVE" and len(params) >= 3:
            # A failed MOVE would have placed actor at params[2] (the TO location)
            missed_locations.add((params[0], params[2]))

        elif action == "PICKUP" and len(params) >= 2:
            missed_inventory.add((params[0], params[1]))

        elif action == "UNLOCK" and len(params) >= 3:
            # A failed UNLOCK would have removed the lock and moved actor there
            missed_conditions.add((params[2], "locked"))
            missed_locations.add((params[0], params[2]))

        elif action == "FORTIFY" and len(params) >= 3:
            missed_conditions.add((params[2], "fortified"))

        elif action == "TURN_POWER_ON" and len(params) >= 4:
            missed_conditions.add((params[3], "power_on"))

        elif action == "SYNTHESIZE_CURE" and len(params) >= 1:
            missed_inventory.add((params[0], "antidote"))

    action = step_result.action
    params = step_result.parameters
    actor  = params[0] if params else ""

    for viol in step_result.violations:
        viol_l = viol.lower()

        # --- Location mismatch violations ---
        if "is at" in viol_l and "not" in viol_l:
            # Determine which location the current step *requires* the actor to be at.
            # For MOVE: the FROM location is params[1]; actor must be there to start.
            # For all other actions: the required location is the place argument.
            if action == "MOVE" and len(params) >= 2:
                required_loc = params[1]   # actor must be at FROM loc
            elif action in ("PICKUP", "DROP", "TALK", "GIVE_ITEM",
                            "FORTIFY", "WALK_AROUND") and len(params) >= 3:
                required_loc = params[2]
            elif action == "WALK_AROUND" and len(params) >= 2:
                required_loc = params[1]
            else:
                required_loc = None

            if required_loc and (actor, required_loc) in missed_locations:
                return True

        # --- Locked-location violations ---
        # "Cannot move FROM/TO locked location 'X'" — cascading if a prior
        # UNLOCK for that location failed.
        if "cannot move" in viol_l and "locked location" in viol_l:
            # Extract the location name from the violation message
            import re
            m = re.search(r"locked location '([^']+)'", viol)
            if m:
                locked_loc = m.group(1)
                if (locked_loc, "locked") in missed_conditions:
                    return True

        # --- Missing inventory item ---
        if "does not have" in viol_l:
            for _, item in missed_inventory:
                if item.lower() in viol_l:
                    return True

        # --- Missing condition ---
        if "power_on" in viol_l or "locked" in viol_l:
            for _, cond in missed_conditions:
                if cond.lower() in viol_l:
                    return True

    return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def validate_schedule(npc_name: str, steps: list[str], world_state: dict) -> ValidationReport:
    """
    Validates each step against the world state using strict precondition rules.
    Effects are applied after each passing step so subsequent steps see updated state.
    Violations are classified as ROOT or CASCADING.
    """
    ws            = deepcopy(world_state)
    step_results  = []
    any_violation = False
    failed_steps: list[StepResult] = []

    for idx, step_str in enumerate(steps, start=1):
        parsed = parse_step(step_str)

        if parsed is None:
            r = StepResult(
                step=idx, action=step_str, parameters=[],
                violations=[f"Could not parse step: '{step_str}'"],
                applied=False, cascading=False
            )
            step_results.append(r)
            failed_steps.append(r)
            any_violation = True
            continue

        action, params = parsed
        checker = ACTION_CHECKERS.get(action)

        if checker is None:
            r = StepResult(
                step=idx, action=action, parameters=params,
                violations=[f"Unknown action '{action}' — not in action library"],
                applied=False, cascading=False
            )
            step_results.append(r)
            failed_steps.append(r)
            any_violation = True
            continue

        actor = params[0] if params else npc_name
        ws_snapshot = deepcopy(ws)
        viols, apply_fn = checker(actor, params, ws)

        if not viols and apply_fn is not None:
            apply_fn(ws)

        cascading = False
        if viols:
            any_violation = True
            cascading = _is_cascading(
                StepResult(idx, action, params, viols, False),
                failed_steps,
                ws_snapshot
            )

        r = StepResult(
            step=idx, action=action, parameters=params,
            violations=viols, applied=(not bool(viols)),
            cascading=cascading
        )
        step_results.append(r)
        if viols:
            failed_steps.append(r)

    return ValidationReport(
        npc=npc_name,
        valid=not any_violation,
        step_results=step_results
    )