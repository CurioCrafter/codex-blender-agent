# Codex Blender Agent Quickstart

This is the first 10 minutes guide for the add-on. The default path is now Game Creator chat in the View3D `AI` N-panel; the three workspaces are power surfaces for status, workflow graphs, and assets.

## 0. Fast Game Creator Path

1. Open the View3D `AI` tab.
2. In `AI Command Center`, click `Start / Refresh Models` before typing a prompt.
3. Choose the model and reasoning effort above the prompt box; the selected model is persisted when available next session.
4. Type in `Ask AI` and click `Send`, or choose a practical workflow.
5. Use workflow buttons such as `Explain Scene`, `Fix Selected`, `Make Game Asset`, `Generate Reference Image`, `Review With Screenshots`, `Save As Reusable Asset`, and `Recover Last Change`.
6. Let local reversible game-creation work run in `Fast` mode; the add-on records receipts and keeps Blender Undo available.
7. Expect approval only for broad, destructive, external-write, package, generic operator-bridge, or critical actions.
8. Watch `AI Flight Recorder` and `What AI Is Doing` for current step, active tool, why it is running, what it can affect, elapsed time, and review-loop events.
9. Use `Generate Reference Image` or `Generate Image Brief` when you want Codex/ChatGPT image generation; the add-on pins a handoff prompt, then the generated file can be registered as an AI Asset.
10. Open `Workflow` when you want to inspect an AI-generated graph; new graphs are blank or unconnected unless you explicitly create an example.
11. Open `Assets` when you want to search, reuse, validate, publish, or package reusable assets.

The live feed is optimized for speed: active tool calls, model readiness, workflow actions, and health status update through a compact observability path, while heavier transcript, asset, screenshot, and raw JSON panels refresh only when needed.

## 1. Open The AI Studio

1. Install and enable `codex_blender_agent.zip` in Blender 4.5.9 LTS or newer 4.5.x.
2. Open the `AI` launcher in the 3D View sidebar.
3. Click `Start / Refresh Models` to start Codex and populate model choices without submitting a prompt.
4. Check `Readiness Checklist` for online access, service, login, model availability, web console, scope, and assets.
5. Click `Create AI Workspaces` to append `AI Studio`, `Workflow`, and `Assets` after Blender's built-in workspace tabs.
6. Start the Codex service only after Blender online access is enabled.

Expected workspace split:

- `AI Studio` is for the AI Command Center, readiness, model selection, action cards, pinned outputs, live AI/tool activity, image-generation handoffs, and dispatch.
- `Workflow` is for repeatable node orchestration, preview, run history, and publish handoff.
- `Assets` is for Blender-native libraries/catalogs, immutable asset versions, previews, package publish/import, toolbox recipes, pins, provenance, and diagnostics.

## 2. Learn The Main Loop

The add-on is chat-first for game creation. The core rule is: chat drives normal reversible Blender work, receipts record what changed, and approval cards are reserved for high-risk or external actions.

1. Choose visible AI scope.
2. Confirm context chips under `What The AI Sees`.
3. Write a prompt or draft.
4. Ask-only and inspect-only prompts can stay in chat.
5. Local reversible scene changes can run directly in Fast mode and record receipts.
6. Review status, risk, affected targets, preview, plan, tool activity, and recovery when a high-risk approval card appears.
7. Approve, cancel, stop, archive, pin, or recover from the card.
8. Pin useful results so they remain visible outside long transcripts.

## 3. Walkthrough: Ask About Scene

Use this when you want help without changing Blender data.

1. Open `AI Studio`.
2. Set scope to `Selection` or `Active Object`.
3. Select the object or collection you want Codex to inspect.
4. Ask: `Explain what is selected and suggest safe improvements. Do not change the scene.`
5. Watch `Live Activity` for progress.
6. Use `Stop Turn` if the answer is going in the wrong direction.

Expected result: Codex answers through chat/transcript surfaces and no risky approval is needed.

## 4. Use The Runnable Prompt Draft

AI Studio can open a Blender text block named `Codex Prompt Draft`. It is a real Python wrapper, so Blender's built-in Text Editor `Run Script` button is safe to use.

1. Open `AI Studio`.
2. Open `Codex Prompt Draft` in a Text Editor area.
3. Type your request inside the `PROMPT = r""" ... """` body.
4. Click either `Send Draft` in the add-on UI or Blender's Text Editor `Run Script`.
5. The add-on extracts only the prompt body and sends it through the Codex/action-card path.

Do not delete the wrapper lines unless you are intentionally resetting the draft. If the template gets damaged, click `Reset Runnable Draft`.

## 5. Walkthrough: Make A Safe Scene Change

Use this for edits that should be inspectable first.

1. Open `AI Studio`.
2. Set scope to `Selection`.
3. Type: `Add a bevel modifier to the selected object, but show me the plan first.`
4. Click `Create Action`.
5. Review the card status, risk, affected targets, plan, and recovery.
6. Click `Mark For Review`, then `Approve` only if the card describes the correct target.
7. Pin the result if it is useful.

Expected result: normal local scene changes run through chat in Fast mode and leave a visible receipt. High-risk work still waits for an approval card.

## 6. Walkthrough: Save And Reuse An Asset

Use this when you want reusable models, systems, or outputs.

1. Select objects in the scene.
2. Open `Assets`.
3. Click `Initialize`, `Migrate`, then `Verify` if this is the first run.
4. Enter a clear asset name, author, and license.
5. Click `Create Publish Card` or `Save Card`.
6. Review the card in `AI Studio` when the action is broad, destructive, external, or package-related.
7. Refresh the asset list, validate the version, and pin it if useful.
8. Publish a package only after metadata, dependencies, preview, provenance, and QA are acceptable.
9. Append or link versions through the import controls; high-risk imports remain review-gated.

Expected result: selected objects move through the production lifecycle: output snapshot -> review card -> asset version -> validation -> package publish/import. SQLite is the local authority; JSON is only compatibility export/backup.

## 7. Walkthrough: Run A Workflow Graph

Use this when a process should be repeatable.

1. Open `Workflow`.
2. Choose an example graph: `Scene Inspector`, `Safe Castle Blockout`, `Material Assignment`, `Save Selection Asset`, or `Asset Reuse`.
3. Click `Create Example`.
4. Inspect the configured nodes and selected-node details.
5. Click `Preview Graph`.
6. Open `AI Studio` to review generated action cards before risky work runs.
7. Click `Run Graph` only after the preview makes sense.

Expected result: graph runs produce the same Studio actions and activity trail as chat-driven work.

## 7. Workflow V0.10 Mental Model

The next workflow pass is about typed orchestration, not more node clutter.

1. `Workflow Input` and `Workflow Output` define the run contract.
2. `Scene Snapshot`, `Selection`, `Context Merge`, and `Thread Memory` collect stable inputs.
3. `Assistant Prompt` resolves the prompt template.
4. `Assistant Call` performs the actual model request.
5. `Asset Search`, `Tool Call`, and `Publish Asset` stay reviewable and card-bound.
6. `Approval Gate`, `Route`, `For Each`, `Join`, and `Preview Tap` keep the graph inspectable.
7. `Recipe Call` is the reusable, versioned replacement for copy-pasted node islands.
8. AI graph edits should be proposed as patches and reviewed before commit.

## 8. In-App Tutorial

Click `Tutorial` in `AI Studio`. The tutorial is executable: each step has a target workspace, a run button, a check, a fix button, an expected result, and a recovery path.

Start with `First AI Studio Run`, then use:

- `Build A Castle Safely` for action-card review.
- `Workflow Graph Basics` for node examples and graph preview.
- `Save And Reuse Asset` for reusable asset bundles.
- `Stop And Recover` for interruption and recovery controls.

## 9. Attachments

Use attachments as context, not as a file manager.

- Attach images for screenshots, concepts, references, or UI problems.
- Attach small text files for specs, notes, or task details.
- Keep attachments relevant to the current action card or thread.

## 10. Stop, Steer, And Recover

- `Stop Turn` interrupts the active Codex response.
- `Guide Running Turn` sends steering text while a turn is active.
- `Cancel` stops a pending action card before execution.
- `Recover` records recovery guidance on a card.
- `Archive` removes a completed or cancelled card from the working surface.
- Blender Undo remains the first recovery path for scene edits.

## 11. Safe Boundaries

The add-on should not silently perform destructive work. Ask for a visible plan first when the task involves:

- deleting, replacing, or overwriting data
- rig cleanup or bone removal
- broad operator calls
- export settings that change deliverables
- arbitrary Python execution
These are treated as critical-risk and are blocked unless expert tools are explicitly enabled.

If a workflow cannot explain its target, risk, and recovery path, keep it in review instead of approving it.

## 12. Troubleshooting

- If the workspace tabs do not appear, use `Diagnose Workspace` in the compact `Codex` launcher.
- If Codex will not start, enable Blender online access and confirm your Codex CLI login works outside Blender.
- If `Run Script` shows a Python syntax error, click `Reset Runnable Draft`; prompt text must live inside the wrapper body.
- If the tutorial button does not show steps, click `Tutorial`, then `Fix Step`, then `Check Step`.
- If the UI feels crowded, use `AI Studio` as the main surface and keep the View3D panel as a launcher only.
- If transcript drawing slows Blender down, pause redraw or hide local visible messages.
- If an asset save fails, verify there is a selected object and register the asset library.
