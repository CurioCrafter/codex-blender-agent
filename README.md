# Codex Blender Agent

`Codex Blender Agent` is a Blender add-on that uses the local `codex app-server` process as its model backend. It reuses your existing Codex CLI/Desktop ChatGPT login, provides an in-Blender chat panel, sends scene context plus optional attachments, exposes structured Blender tools, and includes a full Blender operator bridge so Codex can call `bpy.ops` tools across Blender editor surfaces.

The current AI Studio work targets Blender 4.5.x, including Blender 4.5.8.

V13 adds visual self-review for game creation. From the View3D `AI` N-panel, `Improve with screenshots` lets the assistant create or improve the scene, capture local viewport screenshots from multiple viewpoints, critique the result in the same thread, generate the next prompt, and repeat until the target score or pass cap is reached.

## Current Goal

Clearer version of the product request:

Build a Blender-side Codex client that can keep longer conversations, accept image and file context, inspect and edit real Blender data, import/export assets, and maintain a visible toolbox of reusable mesh recipes, rig workflows, and scene systems that Codex can save, review, and run again later.

V3 added the missing "all Blender tools" layer: Codex can discover, inspect, poll, and call Blender operators dynamically instead of depending only on the hard-coded structured tools.

V4 adds separate chat modes, asset-library storage, stop-current-turn, transcript hiding/compaction, a live activity strip, and a dedicated Text Editor chat view.

V5 moves the add-on toward a workspace-first AI Dashboard. The dashboard keeps project/thread memory separate, stores long transcripts outside Blender RNA, surfaces asset-library backed reusable systems, and gives the model a faster path to inspect Blender surfaces and target the right tools without dumping huge operator lists into the prompt.

V6 makes the dashboard workspace repairable and top-tab visible, adds native Text Editor chat blocks, and turns the AI Workflow node graph into a callable graph surface the model can create, inspect, configure, and run.

V6.1 splits the crowded one-panel UI into a coordinated AI workspace suite: the View3D sidebar is now a compact launcher, `AI Dashboard` owns chat/transcript, `AI Workflow` owns node orchestration, and `AI Assets` owns toolbox and asset-library work.

V6.2 fixes Blender 4.5 extension-mode preference lookup so the same package works when loaded as `bl_ext.user_default.codex_blender_agent`.

V6.3 hardens workspace creation in Blender background/extension tests so the three AI workspaces resolve to exact names instead of `.001` duplicates.

V6.4 fixes Blender's background `workspace.duplicate()` behavior by selecting the newly created workspace before naming it.

V6.5 makes the workspace suite human-centered and action-first: the View3D N-panel is only a compact launcher/state rail, `AI Dashboard` shows scope chips, action cards, pinned outputs, and live activity, `AI Workflow` stays focused on callable node orchestration, and `AI Assets` owns toolbox memory and reusable assets.

V6.6 adds the usability/tutorial pass: in-addon guided walkthroughs, a packaged quickstart, stronger semantic status/risk badges, explanatory empty states, and clearer primary paths for dashboard actions, workflow graphs, and asset reuse.

V8 turns `AI Assets` into an offline-first production asset workspace. Reusable assets now flow through a SQLite authority store, Blender-native asset-library/catalog registration, immutable asset versions, metadata/provenance/QA records, FTS search, package publish/import manifests, and card-first approval for asset writes/imports/publishes.

V9 turns the add-on into a real multi-workspace studio. The opt-in workspace suite is `AI Studio`, `Workflow`, and `Assets`; Blender's default `Layout` is no longer auto-mutated, and the View3D `AI` tab is only a launcher/context bridge outside AI Studio.

V10 is the workflow-graph hardening pass. The goal is to turn `Workflow` into a typed orchestration surface with explicit inputs, assistant calls, approvals, preview-only nodes, reusable recipes, and safe patch proposals. `Workflow` should orchestrate Blender work; it should not replace Geometry Nodes, Shader Nodes, or the Compositor.

V14 improves observability and Codex capability handoffs. Dynamic tool calls now write live dashboard/web-console events, the main Studio UI shows what the AI is doing by default, and image-generation requests can be turned into pinned handoff briefs that are later registered as generated image assets.

V15 makes live observability cheaper and clearer. Tool calls now flow through a compact observability spine with active-tool tracking, debounced dashboard sync, faster `/api/live` polling, lazy web-console heavy tabs, and addon health diagnostics.

## What It Does

- Reuses local Codex/ChatGPT credentials through `codex app-server`.
- Lists available GPT/Codex models from the authenticated account.
- Provides a compact `AI` tab in the 3D View sidebar.
- Persists the latest local chat snapshot under Blender's user config directory.
- Keeps separate thread/history lanes for Scene Agent, Chat Only, Toolbox, and Assets modes.
- Lets the user attach images and text/files to a prompt.
- Sends compact scene summaries so the model has current Blender context.
- Keeps full chat transcripts in external JSON so visible dashboard rows stay light.
- Exposes an opt-in AI workspace suite instead of forcing every control into the View3D sidebar.
- Includes in-addon tutorial cards plus a packaged quickstart for the first AI Studio workflow.
- Creates `AI Studio`, `Workflow`, and `Assets` only when the user clicks `Create AI Workspaces`; Blender's default `Layout` stays untouched.
- Turns the View3D N-panel into the primary Game Creator command surface: chat composer, Send, quick prompts, context, current task, last result, stop, and recover.
- Adds `Improve with screenshots`: creator pass, viewport captures, critic pass with local image attachments, next-prompt generation, and a manifest under user storage in `visual_reviews/<run_id>/`.
- Uses native task-specific editors: AI Studio is View3D/Outliner/Info centered, Workflow is Node Editor/preview/Spreadsheet/Info centered, and Assets is File Browser/Asset Browser plus metadata/provenance controls.
- Shows visible AI scope/context chips so the user and model agree on selection, active object, collection, scene, project, attachments, mode, material, and timeline.
- Records ordinary reversible game-creation changes as receipts and reserves approval cards for broad, destructive, external-write, package, operator-bridge, or critical actions.
- Pins useful outputs outside the raw transcript so long threads remain navigable.
- Provides native `Codex Prompt Draft`, `Codex Chat Transcript`, and `Codex Activity Log` text blocks for multiline chat work.
- Exposes structured dynamic tools for scene reads, edits, import/export, rigs, animation, materials, and toolbox recipes.
- Exposes `list_live_ai_activity` and `run_addon_health_check` so Codex can inspect active tools, recent tool events, sync timing, install health, service state, and web-console status.
- Exposes callable `Codex AI Workflow` node graphs for scene snapshots, selection, thread memory, tool calls, toolbox recipes, asset search, approval gates, prompts, and asset publishing.
- Keeps `Workflow` focused on AI-managed orchestration: new graphs are blank or unconnected by default, and starter/example graphs are explicit.
- Exposes the full Blender `bpy.ops` operator system through a context-aware bridge.
- Stores reusable external files and selected-object `.blend` bundles in a local asset library.
- Lets long transcripts disappear from the UI while keeping the current thread alive.
- Shows live activity from streaming text, planning, reasoning summaries, and tool calls.
- Shows a default-visible `What AI Is Doing` feed with recent prompt, tool, approval, image-brief, and visual-review events.
- Adds Codex capability bridges such as `list_codex_capabilities`, `create_image_generation_brief`, and `register_generated_image_asset`.
- Keeps Codex credentials owned by Codex instead of copying token files into the add-on.
- Ships with both legacy `bl_info` metadata and a Blender 4.5 extension `blender_manifest.toml`.

## Blender Tool Surface

Scene and data inspection:

- `get_scene_summary`
- `get_selection`
- `list_data_blocks`
- `get_object_details`
- `get_blender_property`
- `get_armature_summary`

Object, collection, and transform edits:

- `create_primitive`
- `create_mesh_object`
- `create_empty`
- `rename_object`
- `duplicate_object`
- `set_transform`
- `set_custom_property`
- `set_blender_property`
- `set_object_visibility`
- `set_parent`
- `delete_object`
- `create_collection`
- `move_object_to_collection`
- `create_vertex_group`
- `assign_vertex_group`

Materials, modifiers, cameras, lights, and animation:

- `create_material`
- `assign_material`
- `add_modifier`
- `remove_modifier`
- `apply_modifier`
- `create_light`
- `create_camera`
- `insert_keyframe`
- `set_frame_range`

Rig and armature tools:

- `add_armature_bone`
- `set_bone_deform`
- `delete_armature_bones`
- `set_pose_bone_transform`

Import/export:

- `import_file`
- `export_fbx`

Full Blender operator bridge:

- `list_blender_operators`
- `inspect_blender_operator`
- `check_blender_operator_poll`
- `call_blender_operator`

RNA property access:

- `get_blender_property`
- `set_blender_property`

These tools now accept broad targets instead of a tiny fixed set. Supported target types include `object`, `active_object`, `object_data`, `active_material`, `scene`, `world`, `view_layer`, `modifier`, `pose_bone`, and most `bpy.data` collection names such as `mesh`, `material`, `image`, `action`, `node_group`, `text`, `camera`, `light`, and `collection`.

Toolbox memory:

- `list_toolbox_items`
- `get_toolbox_item`
- `save_toolbox_item`
- `run_toolbox_system`

Asset library:

- `list_asset_items`
- `get_asset_item`
- `search_ai_assets`
- `list_ai_asset_libraries`
- `list_asset_versions`
- `get_asset_version_detail`
- `list_asset_dependencies`
- `list_asset_provenance`
- `create_asset_publish_action`
- `promote_output_snapshot`
- `validate_asset_version`
- `publish_asset_package`
- `import_asset_package`
- `pin_asset_version`
- `fork_asset_version`
- `append_asset_version`
- `link_asset_version`
- `diagnose_ai_assets`
- `save_asset_file`
- `save_selected_objects_asset`
- `import_asset_item`
- `register_blender_asset_library`
- `list_blender_asset_libraries`
- `save_selection_to_asset_library`
- `append_asset_from_library`

Dashboard, memory, and surface targeting:

- `list_studio_context`
- `list_dashboard_context`
- `list_codex_capabilities`
- `create_image_generation_brief`
- `register_generated_image_asset`
- `list_ai_scope`
- `list_context_chips`
- `list_action_cards`
- `get_action_detail`
- `create_action_card`
- `update_action_status`
- `pin_output_to_thread`
- `list_blender_surfaces`
- `list_cached_operator_namespaces`
- `get_thread_context`
- `write_project_note`
- `diagnose_ai_studio_workspace`
- `diagnose_dashboard_workspace`

Workflow graphs:

- `list_workflow_graphs`
- `create_workflow_graph`
- `add_workflow_node`
- `connect_workflow_nodes`
- `set_workflow_node_config`
- `inspect_workflow_graph`
- `run_workflow_graph`

Workflow v0.10 direction:

- `Workflow Input`
- `Workflow Output`
- `Value`
- `Context Merge`
- `Assistant Call`
- `Route`
- `For Each`
- `Join`
- `Preview Tap`
- `Recipe Call`

The intended mental model is:

- pure nodes preview safely
- action nodes require a Flow path and an approval/card boundary
- recipe reuse should be versioned
- AI graph edits should be proposed as patches, not applied directly to the live graph

AI Assets uses an offline-first storage model. The authority store is `ai_assets.db` in writable extension/user storage, with WAL enabled, FTS search, migration backups, previews, manifests, logs, packages, and quarantine folders. Legacy JSON is preserved and exported for compatibility, but SQLite is the source of truth for asset versions, library/catalog records, provenance, dependencies, QA, pins, toolbox memory, and package manifests.

Fast Game Creator Mode records ordinary local reversible changes as receipts. Package exports/imports, external writes, destructive operations, generic operator-bridge work, and critical actions still create reviewable cards with risk, scope, intended changes, and recovery before execution.

Python execution, disabled by default:

- `execute_blender_python`

`call_blender_operator` is the universal bridge to Blender's own operator/tool system. It supports optional `area_type`, `region_type`, `active_object`, `selected_objects`, `mode`, `execution_context`, `switch_area_if_missing`, `poll_first`, and JSON operator properties. This is how the add-on reaches tools across View3D, Mesh Edit Mode, Armature Edit Mode, Pose Mode, UV Editor, Node Editor, Graph Editor, render/import/export surfaces, and other `bpy.ops` namespaces without hard-coding every possible operator.

## Roblox / FBX Workflow Support

The add-on now includes the specific capabilities needed for the problem shown in the screenshot:

- Inspect armatures and bones with `get_armature_summary`.
- Mark non-export/control bones as non-deforming with `set_bone_deform`.
- Delete duplicate/export-only control bones with `delete_armature_bones`.
- Export selected mesh and armature as FBX with `export_fbx`.
- Default FBX export settings include selected objects, `ARMATURE` and `MESH`, no leaf bones, and deform-bone-only armature export.

The model should still ask before destructive rig cleanup unless your prompt explicitly tells it to make those changes.

## Attachments

Use the attachment path field in the panel to add context before sending a prompt.

- Image attachments are sent to Codex as local image input paths.
- Text-like files are read into prompt context, capped to avoid oversized turns.
- Other files are listed as paths and can be imported when supported by `import_file`.
- Supported import formats are FBX, OBJ, GLTF, and GLB.

## Toolbox Recipes

The toolbox is a local memory store for reusable systems. Codex can save named entries such as:

- repeatable mesh creation recipes
- material setups
- rig cleanup workflows
- Roblox export workflows
- scene-system notes

Runnable toolbox recipes use this JSON shape:

```json
{
  "steps": [
    {
      "tool": "create_primitive",
      "arguments": {
        "primitive": "cube",
        "name": "Blockout_Cube"
      }
    }
  ]
}
```

Structured tools and `call_blender_operator` are runnable from recipes. Arbitrary Python is not runnable through toolbox recipes.

## Install

1. Make sure Codex is installed locally and `codex login status` works in your normal shell.
2. In Blender, open `Edit > Preferences > Add-ons > Install`.
3. Choose `codex_blender_agent.zip`.
4. Enable `Codex Blender Agent`.
5. Confirm the `Codex command` path points to your local `codex` command or `codex.cmd`.
6. If Blender online access is disabled, enable it before starting the Codex service.
7. Open the compact `AI` launcher in the 3D View sidebar and click `Create AI Workspaces`. The `AI Studio`, `Workflow`, and `Assets` workspaces are appended after Blender's built-in workspaces; `Layout` should remain unchanged.

## Quickstart

If you want the shortest path from install to first useful result, read [QUICKSTART.md](./QUICKSTART.md). It explains the three workspaces, the action-card workflow, context chips, attachments, workflow graphs, assets, stop/steer, and safe boundaries in the order a new user should learn them.

The same guidance is available inside Blender through the `Tutorial` button in the compact Codex launcher and the main AI workspaces.

## Usage

1. Click `Start Service`.
2. If needed, click `Login with ChatGPT`.
3. Pick a model and reasoning level.
4. Pick a chat mode: Scene Agent, Chat Only, Toolbox, or Assets.
5. Add optional image/file attachments.
6. Prompt it with a concrete task, such as:

```text
Inspect the selected rig, identify non-deforming control bones, and prepare a Roblox-friendly FBX export plan. Do not delete anything until you show me the list.
```

The add-on sends scene context with each prompt and lets Codex call Blender tools for authoritative state or scene changes.

Use `Stop Turn` to interrupt the active model response without shutting down the Codex app-server. While a turn is running, the prompt box becomes `Guide Running Turn`, which sends a live steering update through `turn/steer`. Use `Hide Current Messages`, `Show transcript`, and `Visible messages` to keep Blender responsive when messages get long. Use `Prompt Draft` or `Open Multiline Draft` to edit a full multiline prompt in the `Codex Prompt Draft` text block, then use `Send Draft`.

For a more guided first-time walkthrough, use the tutorial in `QUICKSTART.md` rather than trying to learn the whole UI from the long feature list above.

The workspace-first UI is split by task instead of clustered in one panel. Use `AI Studio` for orientation, scene readiness, action cards, pinned outputs, live activity, and dispatch. Use `Workflow` for node graph orchestration, preview, run history, and publish handoff. Use `Assets` for searchable reusable assets, toolbox recipes, metadata, provenance, and package import/export. The normal View3D N-panel stays a compact launcher/context bridge.

The primary loop is now action-first: set the visible AI scope, write a prompt, create or send an action, review the action card, approve or cancel if needed, then pin useful results. Chat remains available for explanation and iteration, but scene-changing work should be represented as visible action cards.

## Release Readiness

This package is a functional local add-on build, not a moderated Blender Extensions Platform release. The archive now includes the required extension manifest shape for Blender 4.5-style packaging, but public distribution still needs a real in-Blender validation pass, screenshots, and platform-specific smoke tests.

## Full Operator Bridge And Python

The full operator bridge is enabled by default because it is the only practical way to let Codex use "all Blender tools" across surfaces. It can run destructive Blender operators, so use checkpoint saves and undo before broad changes. If a requested `area_type` is not open, the bridge can temporarily switch the current area to that editor type for the operator call.

`execute_blender_python` is still disabled by default. Enable `Python execution` or the legacy expert override in add-on preferences only for trusted sessions.

## Architecture

- Blender UI: panel, operators, and runtime polling on Blender's main thread.
- Codex transport: local stdio JSON-RPC client for `codex app-server`.
- Tool bridge: thread-scoped experimental `dynamicTools`.
- Auth: `account/read` and `account/login/start` through Codex.
- Local storage: chat snapshots, dashboard thread JSON, toolbox JSON, asset-library JSON, and copied asset files under Blender's user config directory.

## Verification

This package has local unit tests for tool specs, attachments, command launch behavior, prompting, toolbox storage, dashboard storage, asset storage, tutorial state, and visual token mapping. Check it with:

```powershell
python -m pytest -q
python -m compileall -q codex_blender_agent tests
```
