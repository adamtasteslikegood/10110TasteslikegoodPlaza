extends Node

## Global signal bus.
##
## Emitters never hold a reference to listeners, and listeners never reach back
## into the world tree. That is what lets the HUD be swapped, or a second frontend
## be built, without touching NPC code.
##
## Signal names are taken verbatim from specs/roadmap.md so that M5-M8 wire into
## the same bus rather than inventing a parallel one. Do not rename them casually;
## the roadmap, CLAUDE.md and the milestone plans all cite these spellings.

## A player entered an agent's proximity area. Carries the full agent record so
## listeners never have to reach into AgentRegistry themselves.
signal npc_approached(agent_id: String, agent_data: Dictionary)

## The player left that agent's proximity area.
signal npc_left(agent_id: String)

## A tutorial or delegated task finished. Unused until M5+; declared now so the
## contract is visible.
signal task_completed(task_id: String)

## A floor or room became accessible, normally as a consequence of task_completed.
signal floor_unlocked(floor_id: String)

## Bridge signals — M7/M8. The ws_client emits these; dialogue_panel listens.
signal agent_query_sent(agent_id: String, task: String)
signal agent_response_received(agent_id: String, response: String)
signal agent_query_failed(agent_id: String, error_type: String, message: String)

## Display snapshots changed; legacy bridge signal arities remain unchanged.
## Reasons: input, reply, failure, draft, connection, view. Empty request ID
## denotes a view/draft/connection change or an input rejected before admission.
signal conversation_changed(agent_id: String, reason: String, request_id: String)


## Workspace/domain snapshots are settled before these additive notifications.
## Wire reasons: workspace_state, domain_state, domain_accepted, domain_result,
## domain_error, resume_complete, status_stale. Local: input, draft, read, connection.
signal workspace_changed(reason: String, request_id: String)
signal domain_changed(domain_id: String, reason: String, request_id: String)

signal character_changed(agent_id: String, reason: String, request_id: String)
signal domain_surface_changed
