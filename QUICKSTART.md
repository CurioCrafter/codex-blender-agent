# Codex Blender Agent Quickstart

This is the first 10 minutes guide for the add-on. It is written for someone who has never used the tool before and wants to understand what each workspace does and how the workflow fits together.

## Game Creator Fast Start

The shortest path is now the View3D `AI` N-panel. Type in `Ask AI`, click `Send`, or choose a quick start such as `Game-ready prop`, `Stylized material`, `Improve with screenshots`, `Clean for export`, or `Teach first asset`.

Use `fast` execution friction for normal game creation. Local reversible/additive Blender work runs directly and leaves a receipt with recovery. Broad, destructive, package, external-write, generic operator-bridge, and critical actions still ask for approval.

Use `Improve with screenshots` when the result needs visual iteration. The add-on runs a creator pass, captures local viewport screenshots from planned viewpoints, sends those screenshots back to the critic phase in the same thread, then repeats with the critic's next prompt until the score target or pass limit is reached. The current task card shows phase, pass count, score, Stop, Continue, and View screenshots.

Open `Workflow` only when you want to inspect or edit an AI-generated graph. New graphs are blank or unconnected unless you explicitly create an example. Open `Assets` when you want to search, reuse, validate, publish, or package reusable assets.

## 1. Install And Open

1. Install `codex_blender_agent.zip` in Blender 4.5.8 from this repo's root folder, for example:
   `%CD%\codex_blender_agent.zip`
2. Enable the add-on.
3. Confirm the extension is installed under:
   `%APPDATA%\Blender Foundation\blender\4.5\extensions\user_default\codex_blender_agent`
4. Open the compact `AI` panel in the 3D View sidebar.
5. Click `Create AI Workspaces` when you want the opt-in Studio workspace suite. Blender's default `Layout` stays unchanged.
6. Start `Codex` only after Blender online access is enabled.

## 2. What The Three Workspaces Do

`AI Studio`

- Your home/dispatch screen.
- Shows scene readiness, current AI scope, action cards, pinned outputs, running jobs, recent outputs, and live activity.
- Use this when you want to understand what Codex is doing and what it plans to do next.

`Workflow`

- Your orchestration workspace.
- Use this to build a node graph that describes a repeatable process, such as scene snapshot -> tool call -> approval -> publish.
- Use `Preview` first, then `Run` after you trust the graph.

`Assets`

- Your reusable memory and asset workspace.
- Use this for Blender-native libraries/catalogs, asset versions, previews, package publish/import, toolbox recipes, pins, provenance, and diagnostics.
- It is offline-first. The local SQLite store is the authority; JSON is backup/export compatibility only.
- Use it when you want Codex to remember a repeatable workflow, publish something reusable, or import a trusted version later.

## 3. First Prompt

1. Open `AI Studio`.
2. Set the visible scope to something small, such as `Selection`.
3. Attach an image or file if it helps the task.
4. Write a short prompt that names the result you want.
5. Use either `Send Draft` or Blender's Text Editor `Run Script`; both read the prompt body from `Codex Prompt Draft`.
6. If the task changes the scene, writes files, imports assets, exports, or runs a workflow, create or review the action card first.
7. Approve the action only after checking affected targets, risk, preview, tool activity, and recovery.

Example:

```text
Inspect the selected rig, identify non-deforming control bones, and prepare a Roblox-friendly FBX export plan. Do not delete anything until you show me the list.
```

`Codex Prompt Draft` is intentionally a valid Python wrapper:

```python
import bpy

PROMPT = r"""
create a castle
"""

bpy.ops.codex_blender_agent.send_prompt_literal(prompt=PROMPT)
```

Keep your prompt inside the triple quotes. If the draft gets damaged, use `Reset Runnable Draft` from AI Studio's prompt draft action.

## 4. How The Workflow Works

The workflow is intentionally visible.

1. `Scope` tells Codex what it should treat as the main context.
2. `Prompt` captures what you want in plain language.
3. `Action Card` turns scene-changing, export, asset-write, or workflow requests into something inspectable.
4. `Preview` shows scope, risk, and intended tool work before anything risky runs.
5. `Approve` is the only path that allows mutating tools to run.
6. `Tool Activity` records what ran, what changed, warnings, and rollback guidance.
7. `Pinned Output` keeps useful results visible after the transcript scrolls away.
8. `Workflow Graph` is for repeatable procedures that you want to run again later.

The product rule is now low-friction: chat drives normal game-creation work, receipts record what changed, approval cards handle risky work, and recovery stays visible.

## 5. Common Tasks

Scene question:

1. Set scope to `Selection` or `Active Object`.
2. Ask a focused question.
3. Read the action card and result summary.

Safe scene change:

1. Ask for the change from AI Studio or create a review card from the prompt draft.
2. Review affected targets and risk.
3. Use `Preview`.
4. Use `Approve`.
5. Use `Pin Result` if the output is useful.

Reusable asset:

1. Open `Assets`.
2. Click `Initialize`, `Migrate`, then `Verify` if this is the first run.
3. Select objects and enter a clear draft publish name.
4. Click `Create Publish Card` or `Save Card`; this creates a review card instead of writing immediately.
5. Review scope, metadata, risk, preview, and recovery in `AI Studio`.
6. Approve the card when the bundle, catalog, and license look correct.
7. Return to `Assets`, validate the version, pin it if useful, and publish a package only after metadata/QA is complete.
8. Append or link versions through action cards so scene changes remain recoverable.

AI Assets stores production facts separately:

- Blender-native payloads live in registered asset libraries and catalogs.
- Asset identity, versions, metadata, dependencies, provenance, QA, pins, and packages live in the SQLite authority store.
- Published packages contain a payload, `blender_assets.cats.txt`, manifest JSON, provenance JSON, previews, hashes, changelog, and license material.

Repeatable workflow:

1. Open `Workflow`.
2. Choose an example graph: `Scene Inspector`, `Safe Castle Blockout`, `Material Assignment`, `Save Selection Asset`, or `Asset Reuse`.
3. Click `Create Example`.
4. Inspect the configured nodes and selected-node details.
5. Preview the graph.
6. Review any generated action cards in `AI Studio`.
7. Run it when the result looks right.

## 6. Workflow V0.10 Mental Model

The next workflow pass is about typed orchestration rather than more node clutter.

1. `Workflow Input` and `Workflow Output` define the run contract.
2. `Scene Snapshot`, `Selection`, `Context Merge`, and `Thread Memory` collect stable inputs.
3. `Assistant Prompt` resolves the prompt template.
4. `Assistant Call` performs the actual model request.
5. `Asset Search`, `Tool Call`, and `Publish Asset` stay reviewable and card-bound.
6. `Approval Gate`, `Route`, `For Each`, `Join`, and `Preview Tap` keep the graph inspectable.
7. `Recipe Call` is the reusable, versioned replacement for copy-pasted node islands.
8. AI graph edits should be proposed as patches and reviewed before commit.

## 7. Tutorial

Click `Tutorial` inside `AI Studio`. The tutorial is not just text: each step has a target workspace, a run button, a check button, a fix button, an expected result, and a recovery action.

Recommended order:

- `First AI Studio Run`
- `Build A Castle Safely`
- `Workflow Graph Basics`
- `Save And Reuse Asset`
- `Stop And Recover`

## 8. Stop And Steer

- `Stop Turn` interrupts the current Codex turn without stopping the service.
- `Guide Running Turn` sends a steering update while Codex is already working.
- `Hide Current Messages` keeps Blender responsive when the transcript gets long.
- `Visible messages` limits how much transcript is drawn in the UI.

## 9. Attachments

- Use image attachments when you want Codex to inspect a screenshot, concept image, or reference.
- Use text/file attachments for specs, notes, or small supporting files.
- Keep attachments small and relevant; they are context, not a file manager.

## 10. What Codex Should Not Do Automatically

These are the boundaries for safe use:

- Destructive deletes or overwrites without review.
- Asset writes, package import/export, library registration, or append/link/import without an approved card.
- Rig cleanup that removes bones before showing you the affected list.
- Broad operator runs that touch unrelated objects or editor contexts.
- Arbitrary Python execution unless expert tools are explicitly enabled.
- Silent scene changes when the prompt is ambiguous.

If the request is risky, the add-on should show a plan, affected items, and a recovery path first. Arbitrary Python, broad operator bridge calls, and external writes are treated as high or critical risk and require card-bound approval.

## 11. Troubleshooting

- If the workspaces do not appear, use the compact `AI` launcher and click `Create AI Workspaces` or `Health`.
- If Codex will not start, check that Blender online access is enabled.
- If `Run Script` shows a Python syntax error, click `Reset Runnable Draft`; prompt text must stay inside the wrapper body.
- If the tutorial looks stuck, click `Fix Step`, then `Run Step`, then `Check Step`.
- If the prompt area feels crowded, move the work into `AI Studio` and keep the View3D panel as a launcher.
- If the transcript gets too long, hide the transcript or lower visible messages.
- If something changed unexpectedly, use Blender Undo first, then recover from the latest checkpoint if available.

## 12. Best Practice

Keep the UI simple:

- AI Studio for intent, scope, status, and action review.
- Workflow for repeatable graphs.
- Assets for reusable systems.
- N-panel for launching and status only.

If you cannot explain a step to a new user in one sentence, it should be rewritten or moved behind a clearer control.
