CREATE UNIQUE INDEX "action_items_uq1" ON "core"."action_items" ("stable_key");

CREATE INDEX "ix_aging_exposure_report_items_project" ON "financial"."aging_exposure_report_items" ("project_key", "threshold_band", "review_required");

CREATE UNIQUE INDEX "aging_exposure_report_items_uq2" ON "financial"."aging_exposure_report_items" ("project_key", "record_family", "record_ref");

CREATE INDEX "ix_ai_job_queue_env_status" ON "core"."ai_job_queue" ("environment", "status");

CREATE UNIQUE INDEX "ai_job_queue_uq2" ON "core"."ai_job_queue" ("environment", "job_type", "idempotency_key");

CREATE INDEX "idx_assistant_action_stage_citations_stage" ON "core"."assistant_action_stage_citations" ("stage_id", "stage_item_id", "citation_order");

CREATE INDEX "idx_assistant_action_stage_events_stage" ON "core"."assistant_action_stage_events" ("stage_id", "created_at");

CREATE INDEX "idx_assistant_action_stage_items_target" ON "core"."assistant_action_stage_items" ("target_kind", "target_id");

CREATE INDEX "idx_assistant_action_stage_items_kind" ON "core"."assistant_action_stage_items" ("action_kind", "staged_state");

CREATE INDEX "idx_assistant_action_stage_items_stage" ON "core"."assistant_action_stage_items" ("stage_id", "item_order");

CREATE INDEX "idx_assistant_action_stage_receipts_stage" ON "core"."assistant_action_stage_receipts" ("stage_id", "created_at");

CREATE INDEX "idx_assistant_action_stages_lineage" ON "core"."assistant_action_stages" ("stage_type", "workflow_type", "request_digest", "status");

CREATE INDEX "idx_assistant_action_stages_workflow" ON "core"."assistant_action_stages" ("workflow_type", "workflow_id");

CREATE INDEX "idx_assistant_action_stages_type" ON "core"."assistant_action_stages" ("stage_type", "status");

CREATE INDEX "idx_assistant_answer_draft_citations_packet_citation" ON "core"."assistant_answer_draft_citations" ("packet_citation_id");

CREATE INDEX "idx_assistant_answer_draft_citations_section" ON "core"."assistant_answer_draft_citations" ("draft_section_id", "citation_order");

CREATE INDEX "idx_assistant_answer_draft_citations_draft" ON "core"."assistant_answer_draft_citations" ("draft_id", "citation_order");

CREATE INDEX "idx_assistant_answer_draft_events_draft" ON "core"."assistant_answer_draft_events" ("draft_id", "created_at");

CREATE INDEX "idx_assistant_answer_draft_receipts_draft" ON "core"."assistant_answer_draft_receipts" ("draft_id", "created_at");

CREATE INDEX "idx_assistant_answer_draft_sections_item" ON "core"."assistant_answer_draft_sections" ("packet_item_id");

CREATE INDEX "idx_assistant_answer_draft_sections_type" ON "core"."assistant_answer_draft_sections" ("draft_id", "section_type");

CREATE INDEX "idx_assistant_answer_draft_sections_draft" ON "core"."assistant_answer_draft_sections" ("draft_id", "section_order");

CREATE INDEX "idx_assistant_answer_drafts_input" ON "core"."assistant_answer_drafts" ("input_digest");

CREATE INDEX "idx_assistant_answer_drafts_packet" ON "core"."assistant_answer_drafts" ("packet_id");

CREATE INDEX "idx_assistant_answer_drafts_type" ON "core"."assistant_answer_drafts" ("draft_type", "status");

CREATE INDEX "idx_assistant_claim_events_claim" ON "core"."assistant_claim_events" ("claim_id", "created_at");

CREATE INDEX "idx_assistant_context_pack_events_pack" ON "core"."assistant_context_pack_events" ("pack_id", "created_at");

CREATE INDEX "idx_assistant_context_pack_items_source" ON "core"."assistant_context_pack_items" ("source_id");

CREATE INDEX "idx_assistant_context_pack_items_pack" ON "core"."assistant_context_pack_items" ("pack_id", "item_order");

CREATE INDEX "idx_assistant_context_pack_receipts_pack" ON "core"."assistant_context_pack_receipts" ("pack_id", "created_at");

CREATE INDEX "idx_assistant_context_packs_status" ON "core"."assistant_context_packs" ("status", "created_at");

CREATE INDEX "idx_assistant_context_packs_type" ON "core"."assistant_context_packs" ("pack_type");

CREATE INDEX "idx_assistant_decision_memory_events_record" ON "core"."assistant_decision_memory_events" ("record_kind", "record_id", "created_at");

CREATE INDEX "idx_assistant_enrichment_jobs_lease" ON "core"."assistant_enrichment_jobs" ("lease_owner", "lease_expires_at");

CREATE INDEX "idx_assistant_enrichment_jobs_source" ON "core"."assistant_enrichment_jobs" ("source_id");

CREATE INDEX "idx_assistant_enrichment_jobs_type" ON "core"."assistant_enrichment_jobs" ("job_type");

CREATE INDEX "idx_assistant_enrichment_jobs_status" ON "core"."assistant_enrichment_jobs" ("status", "priority", "created_at");

CREATE INDEX "idx_assistant_enrichment_receipts_job" ON "core"."assistant_enrichment_receipts" ("job_id", "created_at");

CREATE INDEX "idx_assistant_feedback_events_feedback" ON "core"."assistant_feedback_events" ("feedback_id", "created_at");

CREATE INDEX "idx_assistant_feedback_receipts_feedback" ON "core"."assistant_feedback_receipts" ("feedback_id", "created_at");

CREATE INDEX "idx_assistant_intelligence_projection_events_projection" ON "core"."assistant_intelligence_projection_events" ("projection_id", "created_at");

CREATE INDEX "idx_assistant_intelligence_projection_items_target" ON "core"."assistant_intelligence_projection_items" ("target_kind", "target_id");

CREATE INDEX "idx_assistant_intelligence_projection_items_inclusion" ON "core"."assistant_intelligence_projection_items" ("projection_id", "inclusion_state");

CREATE INDEX "idx_assistant_intelligence_projection_items_projection" ON "core"."assistant_intelligence_projection_items" ("projection_id", "item_order");

CREATE INDEX "idx_assistant_intelligence_projection_receipts_projection" ON "core"."assistant_intelligence_projection_receipts" ("projection_id", "created_at");

CREATE INDEX "idx_assistant_intelligence_projections_input" ON "core"."assistant_intelligence_projections" ("input_digest");

CREATE INDEX "idx_assistant_intelligence_projections_type" ON "core"."assistant_intelligence_projections" ("projection_type", "status");

CREATE INDEX "idx_assistant_memory_compilations_status" ON "core"."assistant_memory_compilations" ("status");

CREATE INDEX "idx_assistant_memory_compilations_node" ON "core"."assistant_memory_compilations" ("node_id", "compile_type", "created_at");

CREATE INDEX "idx_assistant_memory_events_node" ON "core"."assistant_memory_events" ("node_id", "created_at");

CREATE INDEX "idx_assistant_output_file_receipts_output" ON "core"."assistant_output_file_receipts" ("output_id", "receipt_type");

CREATE INDEX "idx_assistant_quality_events_run" ON "core"."assistant_quality_events" ("quality_run_id", "created_at");

CREATE INDEX "idx_assistant_quality_receipts_run" ON "core"."assistant_quality_receipts" ("quality_run_id", "created_at");

CREATE INDEX "idx_assistant_quality_runs_request" ON "core"."assistant_quality_runs" ("request_digest");

CREATE INDEX "idx_assistant_quality_runs_lineage" ON "core"."assistant_quality_runs" ("target_kind", "target_id", "policy_json", "status");

CREATE INDEX "idx_assistant_quality_runs_target" ON "core"."assistant_quality_runs" ("target_kind", "target_id", "status");

CREATE INDEX "idx_assistant_research_packet_citations_item" ON "core"."assistant_research_packet_citations" ("packet_item_id", "citation_order");

CREATE INDEX "idx_assistant_research_packet_citations_packet" ON "core"."assistant_research_packet_citations" ("packet_id", "citation_order");

CREATE INDEX "idx_assistant_research_packet_events_packet" ON "core"."assistant_research_packet_events" ("packet_id", "created_at");

CREATE INDEX "idx_assistant_research_packet_items_target" ON "core"."assistant_research_packet_items" ("target_kind", "target_id");

CREATE INDEX "idx_assistant_research_packet_items_role" ON "core"."assistant_research_packet_items" ("packet_id", "answer_role");

CREATE INDEX "idx_assistant_research_packet_items_packet" ON "core"."assistant_research_packet_items" ("packet_id", "item_order");

CREATE INDEX "idx_assistant_research_packet_receipts_packet" ON "core"."assistant_research_packet_receipts" ("packet_id", "created_at");

CREATE INDEX "idx_assistant_research_packets_input" ON "core"."assistant_research_packets" ("input_digest");

CREATE INDEX "idx_assistant_research_packets_projection" ON "core"."assistant_research_packets" ("projection_id");

CREATE INDEX "idx_assistant_research_packets_type" ON "core"."assistant_research_packets" ("packet_type", "status");

CREATE INDEX "idx_assistant_review_events_item" ON "core"."assistant_review_events" ("review_item_id", "created_at");

CREATE INDEX "ix_brief_effectiveness_rollups_created" ON "core"."brief_effectiveness_rollups" ("created_utc");

CREATE INDEX "ix_brief_effectiveness_rollups_window" ON "core"."brief_effectiveness_rollups" ("window_start", "window_end");

CREATE INDEX "ix_brief_effectiveness_rollups_scope" ON "core"."brief_effectiveness_rollups" ("scope", "scope_key");

CREATE UNIQUE INDEX "calendar_event_attendees_uq1" ON "calendar"."calendar_event_attendees" ("event_index_id", "attendee_hash");

CREATE INDEX "ix_calendar_event_index_review" ON "calendar"."calendar_event_index" ("review_required");

CREATE INDEX "ix_calendar_event_index_project_start" ON "calendar"."calendar_event_index" ("project_key", "start_datetime_utc");

CREATE INDEX "ix_calendar_event_index_source_start" ON "calendar"."calendar_event_index" ("source_id", "start_datetime_utc");

CREATE UNIQUE INDEX "calendar_event_index_uq2" ON "calendar"."calendar_event_index" ("source_id", "graph_event_id_hash");

CREATE INDEX "idx_calendar_event_raw_content_start" ON "calendar"."calendar_event_raw_content" ("start_datetime_utc");

CREATE INDEX "ix_calendar_project_candidates_project" ON "calendar"."calendar_project_match_candidates" ("project_key", "confidence_class");

CREATE INDEX "idx_calendar_raw_event_attendees_structured_raw_row_id" ON "calendar"."calendar_raw_event_attendees_structured" ("raw_row_id");

CREATE INDEX "idx_calendar_raw_event_attendees_structured_parent_proj_01dfdd5" ON "calendar"."calendar_raw_event_attendees_structured" ("parent_projection_id");

CREATE INDEX "idx_calendar_raw_event_locations_structured_raw_row_id" ON "calendar"."calendar_raw_event_locations_structured" ("raw_row_id");

CREATE INDEX "idx_calendar_raw_event_locations_structured_parent_proj_04e048e" ON "calendar"."calendar_raw_event_locations_structured" ("parent_projection_id");

CREATE INDEX "idx_calendar_raw_event_recurrence_structured_raw_row_id" ON "calendar"."calendar_raw_event_recurrence_structured" ("raw_row_id");

CREATE INDEX "idx_calendar_raw_event_recurrence_structured_parent_pro_9a848f4" ON "calendar"."calendar_raw_event_recurrence_structured" ("parent_projection_id");

CREATE INDEX "idx_calendar_raw_event_structured_source_quality" ON "calendar"."calendar_raw_event_structured" ("source_quality");

CREATE INDEX "idx_calendar_raw_event_structured_project_key" ON "calendar"."calendar_raw_event_structured" ("project_key");

CREATE INDEX "idx_calendar_raw_event_structured_raw_row_id" ON "calendar"."calendar_raw_event_structured" ("raw_row_id");

CREATE INDEX "ix_candidate_lifecycle_events_effective" ON "core"."candidate_lifecycle_events" ("effective_until_utc");

CREATE INDEX "ix_candidate_lifecycle_events_group" ON "core"."candidate_lifecycle_events" ("duplicate_group_key");

CREATE INDEX "ix_candidate_lifecycle_events_new_state" ON "core"."candidate_lifecycle_events" ("new_state");

CREATE INDEX "ix_candidate_lifecycle_events_candidate" ON "core"."candidate_lifecycle_events" ("candidate_id");

CREATE INDEX "ix_candidate_lifecycle_events_subject" ON "core"."candidate_lifecycle_events" ("subject_type", "subject_id", "created_utc");

CREATE UNIQUE INDEX "candidate_lifecycle_events_uq2" ON "core"."candidate_lifecycle_events" ("idempotency_key");

CREATE INDEX "ix_candidate_merge_links_group" ON "core"."candidate_merge_links" ("duplicate_group_key");

CREATE INDEX "ix_candidate_merge_links_target" ON "core"."candidate_merge_links" ("target_subject_type", "target_subject_id");

CREATE INDEX "ix_candidate_merge_links_source" ON "core"."candidate_merge_links" ("source_subject_type", "source_subject_id");

CREATE UNIQUE INDEX "candidate_merge_links_uq2" ON "core"."candidate_merge_links" ("idempotency_key");

CREATE INDEX "ix_candidate_similarity_edges_cluster" ON "core"."candidate_similarity_edges" ("cluster_id");

CREATE INDEX "ix_candidate_similarity_edges_b" ON "core"."candidate_similarity_edges" ("candidate_b_id");

CREATE INDEX "ix_candidate_similarity_edges_a" ON "core"."candidate_similarity_edges" ("candidate_a_id");

CREATE INDEX "ix_candidate_similarity_edges_date" ON "core"."candidate_similarity_edges" ("brief_date");

CREATE INDEX "ix_candidate_source_refs_candidate" ON "core"."candidate_source_refs" ("candidate_type", "candidate_id");

CREATE INDEX "ix_candidate_suppression_rules_active" ON "core"."candidate_suppression_rules" ("active");

CREATE INDEX "ix_candidate_suppression_rules_subject" ON "core"."candidate_suppression_rules" ("subject_type", "subject_id");

CREATE INDEX "ix_candidate_suppression_rules_group" ON "core"."candidate_suppression_rules" ("duplicate_group_key");

CREATE INDEX "ix_candidate_suppression_rules_scope" ON "core"."candidate_suppression_rules" ("scope");

CREATE UNIQUE INDEX "candidate_suppression_rules_uq2" ON "core"."candidate_suppression_rules" ("idempotency_key");

CREATE INDEX "ix_claude_context_packets_type_date" ON "core"."claude_context_packets" ("packet_type", "packet_date");

CREATE INDEX "ix_commitment_candidates_snoozed_until" ON "core"."commitment_candidates" ("snoozed_until_utc");

CREATE INDEX "ix_commitment_candidates_review_status" ON "core"."commitment_candidates" ("review_status");

CREATE UNIQUE INDEX "commitment_candidates_uq2" ON "core"."commitment_candidates" ("stable_key");

CREATE INDEX "ix_document_cards_review" ON "construction"."construction_document_cards" ("review_required", "review_status");

CREATE INDEX "ix_document_cards_source" ON "construction"."construction_document_cards" ("source_id", "drive_item_id_hash");

CREATE INDEX "ix_document_cards_project_type" ON "construction"."construction_document_cards" ("project_key", "document_type", "confidence_class");

CREATE UNIQUE INDEX "ux_document_cards_document_card_id" ON "construction"."construction_document_cards" ("document_card_id");

CREATE INDEX "ix_document_relationship_candidates_target" ON "construction"."construction_document_relationship_candidates" ("target_system", "target_record_type", "target_record_key_hash");

CREATE INDEX "ix_construction_drive_items_review_required" ON "construction"."construction_drive_items" ("review_required");

CREATE INDEX "ix_construction_drive_items_match_status" ON "construction"."construction_drive_items" ("match_status");

CREATE INDEX "ix_construction_drive_items_project_key" ON "construction"."construction_drive_items" ("project_key");

CREATE INDEX "ix_construction_drive_items_deleted" ON "construction"."construction_drive_items" ("deleted");

CREATE INDEX "ix_construction_drive_items_source_modified" ON "construction"."construction_drive_items" ("source_id", "last_modified_datetime");

CREATE INDEX "ix_construction_drive_items_project" ON "construction"."construction_drive_items" ("project_number_detected");

CREATE INDEX "ix_construction_file_extraction_runs_item" ON "construction"."construction_file_extraction_runs" ("source_id", "drive_item_id");

CREATE INDEX "ix_construction_file_ingestion_decisions_review" ON "construction"."construction_file_ingestion_decisions" ("review_required");

CREATE INDEX "ix_construction_file_ingestion_decisions_source" ON "construction"."construction_file_ingestion_decisions" ("source_id");

CREATE UNIQUE INDEX "construction_file_ingestion_decisions_uq2" ON "construction"."construction_file_ingestion_decisions" ("source_id", "drive_item_id");

CREATE INDEX "ix_construction_graph_download_receipts_item" ON "construction"."construction_graph_download_receipts" ("source_id", "drive_item_id");

CREATE INDEX "ix_construction_graph_link_resolution_source" ON "construction"."construction_graph_link_resolution" ("source_id");

CREATE INDEX "ix_construction_model_decisions_item" ON "construction"."construction_model_decisions" ("source_key", "item_id");

CREATE INDEX "ix_construction_model_decisions_status" ON "construction"."construction_model_decisions" ("status");

CREATE INDEX "ix_project_keyword_registry_project_strength" ON "construction"."construction_project_keyword_registry" ("project_key", "strength")
    WHERE "registry_status" = 'enabled';

CREATE INDEX "ix_project_keyword_registry_project_status" ON "construction"."construction_project_keyword_registry" ("project_key", "registry_status");

CREATE UNIQUE INDEX "construction_project_keyword_registry_uq2" ON "construction"."construction_project_keyword_registry" ("project_key", "keyword_hash");

CREATE INDEX "ix_construction_project_source_matches_review" ON "construction"."construction_project_source_matches" ("review_required");

CREATE UNIQUE INDEX "construction_project_source_matches_uq1" ON "construction"."construction_project_source_matches" ("project_key", "source_id");

CREATE INDEX "ix_construction_review_queue_source" ON "construction"."construction_review_queue" ("source_key");

CREATE INDEX "ix_construction_review_queue_status" ON "construction"."construction_review_queue" ("status");

CREATE UNIQUE INDEX "construction_review_queue_uq1" ON "construction"."construction_review_queue" ("source_key", "item_id", "rule_id");

CREATE INDEX "ix_construction_source_locations_project" ON "construction"."construction_source_locations" ("project_key");

CREATE UNIQUE INDEX "content_embeddings_uq1" ON "core"."content_embeddings" ("source_record_id", "content_ref", "model");

CREATE INDEX "ix_readiness_project" ON "core"."cross_domain_context_readiness_mart" ("project_key");

CREATE INDEX "ix_cross_source_relationship_candidates_target" ON "core"."cross_source_relationship_candidates" ("target_family", "target_record_type");

CREATE INDEX "ix_cross_source_relationship_candidates_source" ON "core"."cross_source_relationship_candidates" ("source_family", "source_record_type");

CREATE INDEX "ix_cross_source_relationship_candidates_project" ON "core"."cross_source_relationship_candidates" ("project_key", "confidence_class", "review_required");

CREATE UNIQUE INDEX "cross_source_relationship_candidates_uq2" ON "core"."cross_source_relationship_candidates" ("source_family", "source_record_ref", "target_family", "target_record_ref", "relationship_type");

CREATE INDEX "ix_cross_source_relationships_project" ON "core"."cross_source_relationships" ("project_key", "confidence_class", "review_required");

CREATE UNIQUE INDEX "cross_source_relationships_uq2" ON "core"."cross_source_relationships" ("source_family", "source_record_ref", "target_family", "target_record_ref", "relationship_type");

CREATE INDEX "ix_daily_brief_action_candidates_date_section" ON "core"."daily_brief_action_candidates" ("brief_date", "section");

CREATE INDEX "ix_daily_brief_assembly_runs_model_status" ON "core"."daily_brief_assembly_runs" ("model_layer_status");

CREATE INDEX "ix_daily_brief_assembly_runs_ranking" ON "core"."daily_brief_assembly_runs" ("ranking_run_id");

CREATE INDEX "ix_daily_brief_assembly_runs_date" ON "core"."daily_brief_assembly_runs" ("brief_date");

CREATE INDEX "ix_daily_brief_assembly_sections_run" ON "core"."daily_brief_assembly_sections" ("assembly_run_id");

CREATE INDEX "ix_daily_brief_change_event_refs_event" ON "core"."daily_brief_change_event_refs" ("change_event_id");

CREATE INDEX "ix_daily_brief_change_events_created" ON "core"."daily_brief_change_events" ("created_utc");

CREATE INDEX "ix_daily_brief_change_events_attention" ON "core"."daily_brief_change_events" ("attention_class");

CREATE INDEX "ix_daily_brief_change_events_family" ON "core"."daily_brief_change_events" ("source_family");

CREATE INDEX "ix_daily_brief_change_events_date" ON "core"."daily_brief_change_events" ("brief_date");

CREATE INDEX "ix_delivery_receipts_date" ON "core"."daily_brief_delivery_receipts" ("brief_date", "created_utc");

CREATE INDEX "ix_daily_brief_exposure_events_created" ON "core"."daily_brief_exposure_events" ("created_utc");

CREATE INDEX "ix_daily_brief_exposure_events_candidate" ON "core"."daily_brief_exposure_events" ("daily_brief_action_candidate_id");

CREATE INDEX "ix_daily_brief_exposure_events_assembly" ON "core"."daily_brief_exposure_events" ("assembly_run_id");

CREATE INDEX "ix_daily_brief_exposure_events_ranking" ON "core"."daily_brief_exposure_events" ("ranking_run_id");

CREATE INDEX "ix_daily_brief_exposure_events_date" ON "core"."daily_brief_exposure_events" ("brief_date");

CREATE INDEX "ix_daily_brief_handoff_lines_run" ON "core"."daily_brief_handoff_lines" ("brief_run_id", "section", "line_index");

CREATE INDEX "ix_html_render_receipts_date" ON "core"."daily_brief_html_render_receipts" ("brief_date", "created_utc");

CREATE INDEX "ix_daily_brief_item_outcome_events_created" ON "core"."daily_brief_item_outcome_events" ("created_utc");

CREATE INDEX "ix_daily_brief_item_outcome_events_type" ON "core"."daily_brief_item_outcome_events" ("outcome_type");

CREATE INDEX "ix_daily_brief_item_outcome_events_candidate" ON "core"."daily_brief_item_outcome_events" ("daily_brief_action_candidate_id");

CREATE INDEX "ix_daily_brief_item_outcome_events_date" ON "core"."daily_brief_item_outcome_events" ("brief_date");

CREATE INDEX "ix_notification_receipts_date" ON "core"."daily_brief_notification_receipts" ("brief_date", "created_utc");

CREATE INDEX "ix_open_receipts_date" ON "core"."daily_brief_open_receipts" ("brief_date", "created_utc");

CREATE INDEX "ix_daily_brief_ranked_candidates_cluster" ON "core"."daily_brief_ranked_candidates" ("duplicate_cluster_id");

CREATE INDEX "ix_daily_brief_ranked_candidates_candidate" ON "core"."daily_brief_ranked_candidates" ("daily_brief_action_candidate_id");

CREATE INDEX "ix_daily_brief_ranked_candidates_run" ON "core"."daily_brief_ranked_candidates" ("ranking_run_id");

CREATE INDEX "ix_daily_brief_ranking_runs_model_status" ON "core"."daily_brief_ranking_runs" ("model_status");

CREATE INDEX "ix_daily_brief_ranking_runs_date" ON "core"."daily_brief_ranking_runs" ("brief_date");

CREATE INDEX "ix_daily_brief_runs_date" ON "core"."daily_brief_runs" ("brief_date", "status");

CREATE INDEX "ix_data_quality_gate_results_run_status" ON "core"."data_quality_gate_results" ("run_id", "gate_status", "blocking");

CREATE INDEX "ix_email_followup_enrichments_created_utc" ON "email"."email_followup_enrichments" ("created_utc");

CREATE INDEX "ix_email_followup_enrichments_waiting_state" ON "email"."email_followup_enrichments" ("waiting_state");

CREATE INDEX "ix_email_followup_enrichments_review_status" ON "email"."email_followup_enrichments" ("review_status");

CREATE INDEX "ix_email_followup_enrichments_watch_item" ON "email"."email_followup_enrichments" ("watch_item_id");

CREATE INDEX "ix_email_followup_enrichments_candidate" ON "email"."email_followup_enrichments" ("source_candidate_id");

CREATE UNIQUE INDEX "email_followup_enrichments_uq2" ON "email"."email_followup_enrichments" ("idempotency_key");

CREATE INDEX "ix_email_body_vault_refs_review" ON "email"."email_message_body_vault_refs" ("review_required");

CREATE INDEX "idx_email_message_raw_content_received" ON "email"."email_message_raw_content" ("received_at_utc");

CREATE INDEX "idx_email_message_raw_content_conversation" ON "email"."email_message_raw_content" ("conversation_id_hash");

CREATE UNIQUE INDEX "email_message_recipients_uq1" ON "email"."email_message_recipients" ("message_id", "recipient_role", "address_hash");

CREATE INDEX "ix_email_messages_review" ON "email"."email_messages" ("review_required");

CREATE INDEX "ix_email_messages_received" ON "email"."email_messages" ("received_datetime");

CREATE INDEX "ix_email_messages_project" ON "email"."email_messages" ("project_number_detected");

CREATE INDEX "ix_email_messages_thread" ON "email"."email_messages" ("thread_key");

CREATE INDEX "ix_email_model_classifications_review" ON "email"."email_model_classifications" ("review_required");

CREATE INDEX "ix_email_model_classifications_project" ON "email"."email_model_classifications" ("project_key");

CREATE UNIQUE INDEX "email_model_classifications_uq2" ON "email"."email_model_classifications" ("message_id", "model_name", "schema_version");

CREATE INDEX "ix_email_processing_receipts_run" ON "email"."email_processing_receipts" ("run_id");

CREATE UNIQUE INDEX "email_project_matches_uq2" ON "email"."email_project_matches" ("message_id", "project_key", "match_signal");

CREATE INDEX "idx_email_raw_message_attachments_structured_raw_row_id" ON "email"."email_raw_message_attachments_structured" ("raw_row_id");

CREATE INDEX "idx_email_raw_message_attachments_structured_parent_pro_11a752e" ON "email"."email_raw_message_attachments_structured" ("parent_projection_id");

CREATE INDEX "idx_email_raw_message_recipients_structured_raw_row_id" ON "email"."email_raw_message_recipients_structured" ("raw_row_id");

CREATE INDEX "idx_email_raw_message_recipients_structured_parent_proj_ad33491" ON "email"."email_raw_message_recipients_structured" ("parent_projection_id");

CREATE INDEX "idx_email_raw_message_structured_source_quality" ON "email"."email_raw_message_structured" ("source_quality");

CREATE INDEX "idx_email_raw_message_structured_project_key" ON "email"."email_raw_message_structured" ("project_key");

CREATE INDEX "idx_email_raw_message_structured_raw_row_id" ON "email"."email_raw_message_structured" ("raw_row_id");

CREATE INDEX "idx_email_raw_thread_messages_structured_raw_row_id" ON "email"."email_raw_thread_messages_structured" ("raw_row_id");

CREATE INDEX "idx_email_raw_thread_messages_structured_parent_projection_id" ON "email"."email_raw_thread_messages_structured" ("parent_projection_id");

CREATE INDEX "idx_email_raw_thread_structured_source_quality" ON "email"."email_raw_thread_structured" ("source_quality");

CREATE INDEX "idx_email_raw_thread_structured_project_key" ON "email"."email_raw_thread_structured" ("project_key");

CREATE INDEX "idx_email_raw_thread_structured_raw_row_id" ON "email"."email_raw_thread_structured" ("raw_row_id");

CREATE UNIQUE INDEX "email_relationship_candidates_uq2" ON "email"."email_relationship_candidates" ("message_id", "candidate_type", "target_table", "target_key", "match_signal");

CREATE INDEX "ix_email_review_queue_project" ON "email"."email_review_queue" ("project_key");

CREATE INDEX "ix_email_review_queue_status" ON "email"."email_review_queue" ("status");

CREATE UNIQUE INDEX "email_review_queue_uq2" ON "email"."email_review_queue" ("message_id", "category", "reason");

CREATE INDEX "ix_email_source_locations_role" ON "email"."email_source_locations" ("folder_role");

CREATE INDEX "ix_email_source_locations_owner" ON "email"."email_source_locations" ("mailbox_owner_hash");

CREATE UNIQUE INDEX "email_thread_raw_context_uq2" ON "email"."email_thread_raw_context" ("thread_ref");

CREATE INDEX "ix_follow_up_watch_items_status_check" ON "core"."follow_up_watch_items" ("watch_status", "next_check_utc");

CREATE INDEX "idx_forecast_accuracy_results_baseline" ON "financial"."forecast_accuracy_results" ("baseline");

CREATE INDEX "idx_forecast_accuracy_results_project" ON "financial"."forecast_accuracy_results" ("project_key");

CREATE INDEX "idx_forecast_accuracy_results_forecast" ON "financial"."forecast_accuracy_results" ("external_forecast_id");

CREATE INDEX "idx_forecast_anomaly_findings_severity" ON "financial"."forecast_anomaly_findings" ("severity");

CREATE INDEX "idx_forecast_anomaly_findings_project" ON "financial"."forecast_anomaly_findings" ("project_key");

CREATE INDEX "idx_forecast_anomaly_findings_forecast" ON "financial"."forecast_anomaly_findings" ("external_forecast_id");

CREATE INDEX "idx_forecast_budget_details_package" ON "financial"."forecast_budget_details" ("source_package");

CREATE INDEX "idx_forecast_budget_details_code" ON "financial"."forecast_budget_details" ("budget_code_key");

CREATE INDEX "idx_forecast_budget_details_project" ON "financial"."forecast_budget_details" ("project_key");

CREATE INDEX "idx_forecast_calibration_weights_project" ON "financial"."forecast_calibration_weights" ("project_key");

CREATE INDEX "idx_forecast_calibration_weights_run" ON "financial"."forecast_calibration_weights" ("run_id");

CREATE UNIQUE INDEX "forecast_calibration_weights_uq2" ON "financial"."forecast_calibration_weights" ("run_id", "method");

CREATE INDEX "idx_forecast_comparison_results_baseline" ON "financial"."forecast_comparison_results" ("baseline");

CREATE INDEX "idx_forecast_comparison_results_code" ON "financial"."forecast_comparison_results" ("budget_code_key");

CREATE INDEX "idx_forecast_comparison_results_project" ON "financial"."forecast_comparison_results" ("project_key");

CREATE INDEX "idx_forecast_comparison_results_forecast" ON "financial"."forecast_comparison_results" ("external_forecast_id");

CREATE INDEX "idx_forecast_confidence_factors_run" ON "financial"."forecast_confidence_factors" ("run_id");

CREATE INDEX "idx_forecast_confidence_factors_scorecard" ON "financial"."forecast_confidence_factors" ("scorecard_id");

CREATE UNIQUE INDEX "forecast_confidence_factors_uq2" ON "financial"."forecast_confidence_factors" ("scorecard_id", "factor_key");

CREATE INDEX "idx_forecast_confidence_scorecards_project" ON "financial"."forecast_confidence_scorecards" ("project_key");

CREATE INDEX "idx_forecast_confidence_scorecards_run" ON "financial"."forecast_confidence_scorecards" ("run_id");

CREATE UNIQUE INDEX "forecast_confidence_scorecards_uq2" ON "financial"."forecast_confidence_scorecards" ("run_id", "scope", "scope_key");

CREATE INDEX "idx_forecast_config_items_status" ON "financial"."forecast_config_items" ("status");

CREATE INDEX "idx_forecast_config_items_name" ON "financial"."forecast_config_items" ("config_name");

CREATE INDEX "idx_forecast_config_items_domain" ON "financial"."forecast_config_items" ("config_domain");

CREATE INDEX "idx_forecast_config_items_project" ON "financial"."forecast_config_items" ("project_key");

CREATE INDEX "idx_forecast_config_items_source" ON "financial"."forecast_config_items" ("config_source_id");

CREATE UNIQUE INDEX "forecast_config_items_uq2" ON "financial"."forecast_config_items" ("project_key", "config_domain", "config_name", "item_key", "canonical_json_sha256");

CREATE INDEX "idx_forecast_config_snapshot_items_domain" ON "financial"."forecast_config_snapshot_items" ("config_domain");

CREATE INDEX "idx_forecast_config_snapshot_items_project" ON "financial"."forecast_config_snapshot_items" ("project_key");

CREATE INDEX "idx_forecast_config_snapshot_items_snapshot" ON "financial"."forecast_config_snapshot_items" ("config_snapshot_id");

CREATE INDEX "idx_forecast_config_snapshots_name" ON "financial"."forecast_config_snapshots" ("snapshot_name");

CREATE INDEX "idx_forecast_config_snapshots_project" ON "financial"."forecast_config_snapshots" ("project_key");

CREATE UNIQUE INDEX "forecast_config_snapshots_uq2" ON "financial"."forecast_config_snapshots" ("project_key", "snapshot_name", "snapshot_sha256");

CREATE INDEX "idx_forecast_config_sources_name" ON "financial"."forecast_config_sources" ("config_name");

CREATE INDEX "idx_forecast_config_sources_domain" ON "financial"."forecast_config_sources" ("config_domain");

CREATE INDEX "idx_forecast_config_sources_project" ON "financial"."forecast_config_sources" ("project_key");

CREATE UNIQUE INDEX "forecast_config_sources_uq2" ON "financial"."forecast_config_sources" ("project_key", "config_domain", "config_name", "content_sha256");

CREATE INDEX "idx_forecast_cost_entries_package" ON "financial"."forecast_cost_entries" ("source_package");

CREATE INDEX "idx_forecast_cost_entries_code" ON "financial"."forecast_cost_entries" ("budget_code_key");

CREATE INDEX "idx_forecast_cost_entries_project" ON "financial"."forecast_cost_entries" ("project_key");

CREATE UNIQUE INDEX "forecast_cost_entries_uq2" ON "financial"."forecast_cost_entries" ("project_key", "source_package", "source_row_number");

CREATE INDEX "idx_forecast_cost_entry_staffing_actuals_person" ON "financial"."forecast_cost_entry_staffing_actuals" ("project_key", "employee_name_normalized");

CREATE INDEX "idx_forecast_cost_entry_staffing_actuals_project" ON "financial"."forecast_cost_entry_staffing_actuals" ("project_key", "cost_code", "category");

CREATE INDEX "idx_forecast_data_availability_profiles_project" ON "financial"."forecast_data_availability_profiles" ("project_key");

CREATE INDEX "idx_forecast_data_availability_profiles_run" ON "financial"."forecast_data_availability_profiles" ("run_id");

CREATE UNIQUE INDEX "forecast_data_availability_profiles_uq2" ON "financial"."forecast_data_availability_profiles" ("run_id", "domain");

CREATE INDEX "idx_forecast_evidence_packages_project" ON "financial"."forecast_evidence_packages" ("project_key");

CREATE INDEX "idx_forecast_evidence_packages_forecast" ON "financial"."forecast_evidence_packages" ("external_forecast_id");

CREATE UNIQUE INDEX "forecast_evidence_packages_uq2" ON "financial"."forecast_evidence_packages" ("project_key", "manifest_sha256");

CREATE INDEX "idx_forecast_external_mappings_status" ON "financial"."forecast_external_forecast_mappings" ("mapping_status");

CREATE INDEX "idx_forecast_external_mappings_project" ON "financial"."forecast_external_forecast_mappings" ("project_key");

CREATE INDEX "idx_forecast_external_mappings_forecast" ON "financial"."forecast_external_forecast_mappings" ("external_forecast_id");

CREATE INDEX "idx_forecast_external_rows_code" ON "financial"."forecast_external_forecast_rows" ("budget_code_key");

CREATE INDEX "idx_forecast_external_rows_project" ON "financial"."forecast_external_forecast_rows" ("project_key");

CREATE INDEX "idx_forecast_external_rows_forecast" ON "financial"."forecast_external_forecast_rows" ("external_forecast_id");

CREATE INDEX "idx_forecast_external_forecasts_source" ON "financial"."forecast_external_forecasts" ("source_system");

CREATE INDEX "idx_forecast_external_forecasts_period" ON "financial"."forecast_external_forecasts" ("period");

CREATE INDEX "idx_forecast_external_forecasts_project" ON "financial"."forecast_external_forecasts" ("project_key");

CREATE UNIQUE INDEX "forecast_external_forecasts_uq2" ON "financial"."forecast_external_forecasts" ("project_key", "period", "content_sha256");

CREATE INDEX "idx_forecast_generation_requests_project_created" ON "financial"."forecast_generation_requests" ("project_key", "created_utc");

CREATE INDEX "idx_forecast_method_eligibility_project" ON "financial"."forecast_method_eligibility" ("project_key");

CREATE INDEX "idx_forecast_method_eligibility_run" ON "financial"."forecast_method_eligibility" ("run_id");

CREATE UNIQUE INDEX "forecast_method_eligibility_uq2" ON "financial"."forecast_method_eligibility" ("run_id", "method");

CREATE INDEX "idx_forecast_model_selection_decisions_project" ON "financial"."forecast_model_selection_decisions" ("project_key");

CREATE INDEX "idx_forecast_model_selection_decisions_run" ON "financial"."forecast_model_selection_decisions" ("run_id");

CREATE UNIQUE INDEX "forecast_model_selection_decisions_uq2" ON "financial"."forecast_model_selection_decisions" ("run_id", "method");

CREATE INDEX "idx_forecast_model_versions_sha" ON "financial"."forecast_model_versions" ("methodology_sha256");

CREATE INDEX "idx_forecast_model_versions_label" ON "financial"."forecast_model_versions" ("version_label");

CREATE UNIQUE INDEX "forecast_model_versions_uq2" ON "financial"."forecast_model_versions" ("methodology_sha256");

CREATE INDEX "idx_forecast_monthly_actuals_month" ON "financial"."forecast_monthly_actuals_by_budget_code" ("month");

CREATE INDEX "idx_forecast_monthly_actuals_package" ON "financial"."forecast_monthly_actuals_by_budget_code" ("source_package");

CREATE INDEX "idx_forecast_monthly_actuals_code" ON "financial"."forecast_monthly_actuals_by_budget_code" ("budget_code_key");

CREATE INDEX "idx_forecast_monthly_actuals_project" ON "financial"."forecast_monthly_actuals_by_budget_code" ("project_key");

CREATE INDEX "idx_forecast_operator_assumptions_project" ON "financial"."forecast_operator_assumptions" ("project_key");

CREATE INDEX "idx_forecast_operator_assumptions_run" ON "financial"."forecast_operator_assumptions" ("run_id");

CREATE INDEX "idx_forecast_output_budget_codes_project" ON "financial"."forecast_output_budget_codes" ("project_key");

CREATE INDEX "idx_forecast_output_budget_codes_output" ON "financial"."forecast_output_budget_codes" ("output_id");

CREATE UNIQUE INDEX "forecast_output_budget_codes_uq2" ON "financial"."forecast_output_budget_codes" ("output_id", "budget_code_key");

CREATE INDEX "idx_forecast_output_changes_project" ON "financial"."forecast_output_changes" ("project_key");

CREATE INDEX "idx_forecast_output_changes_output" ON "financial"."forecast_output_changes" ("output_id");

CREATE UNIQUE INDEX "forecast_output_changes_uq2" ON "financial"."forecast_output_changes" ("output_id", "budget_code_key", "change_type");

CREATE INDEX "idx_forecast_output_commitment_exposure_project" ON "financial"."forecast_output_commitment_exposure" ("project_key");

CREATE INDEX "idx_forecast_output_commitment_exposure_output" ON "financial"."forecast_output_commitment_exposure" ("output_id");

CREATE UNIQUE INDEX "forecast_output_commitment_exposure_uq2" ON "financial"."forecast_output_commitment_exposure" ("output_id", "budget_code_key");

CREATE INDEX "idx_forecast_output_monthly_output_value_type" ON "financial"."forecast_output_monthly" ("output_id", "value_type");

CREATE INDEX "idx_forecast_output_monthly_output_month" ON "financial"."forecast_output_monthly" ("output_id", "month");

CREATE INDEX "idx_forecast_output_monthly_output_code" ON "financial"."forecast_output_monthly" ("output_id", "budget_code_key");

CREATE INDEX "idx_forecast_output_monthly_project" ON "financial"."forecast_output_monthly" ("project_key");

CREATE INDEX "idx_forecast_output_monthly_output" ON "financial"."forecast_output_monthly" ("output_id");

CREATE UNIQUE INDEX "forecast_output_monthly_uq2" ON "financial"."forecast_output_monthly" ("output_id", "budget_code_key", "month");

CREATE INDEX "idx_forecast_output_monthly_table_rows_output_cost_code" ON "financial"."forecast_output_monthly_table_rows" ("output_id", "cost_code");

CREATE INDEX "idx_forecast_output_monthly_table_rows_output_cost_type" ON "financial"."forecast_output_monthly_table_rows" ("output_id", "cost_type");

CREATE INDEX "idx_forecast_output_monthly_table_rows_output" ON "financial"."forecast_output_monthly_table_rows" ("output_id");

CREATE UNIQUE INDEX "forecast_output_monthly_table_rows_uq2" ON "financial"."forecast_output_monthly_table_rows" ("output_id", "budget_code_key");

CREATE INDEX "idx_forecast_output_monthly_table_totals_output" ON "financial"."forecast_output_monthly_table_totals" ("output_id");

CREATE UNIQUE INDEX "forecast_output_monthly_table_totals_uq2" ON "financial"."forecast_output_monthly_table_totals" ("output_id");

CREATE INDEX "idx_forecast_output_narratives_project" ON "financial"."forecast_output_narratives" ("project_key");

CREATE INDEX "idx_forecast_output_narratives_output" ON "financial"."forecast_output_narratives" ("output_id");

CREATE UNIQUE INDEX "forecast_output_narratives_uq2" ON "financial"."forecast_output_narratives" ("output_id", "scope", "narrative_key");

CREATE INDEX "idx_forecast_output_probability_project" ON "financial"."forecast_output_probability" ("project_key");

CREATE INDEX "idx_forecast_output_probability_output" ON "financial"."forecast_output_probability" ("output_id");

CREATE UNIQUE INDEX "forecast_output_probability_uq2" ON "financial"."forecast_output_probability" ("output_id", "scope", "budget_code_key");

CREATE INDEX "idx_forecast_output_risks_project" ON "financial"."forecast_output_risks" ("project_key");

CREATE INDEX "idx_forecast_output_risks_output" ON "financial"."forecast_output_risks" ("output_id");

CREATE UNIQUE INDEX "forecast_output_risks_uq2" ON "financial"."forecast_output_risks" ("output_id", "risk_id");

CREATE INDEX "idx_forecast_output_schedule_phasing_project" ON "financial"."forecast_output_schedule_phasing" ("project_key");

CREATE INDEX "idx_forecast_output_schedule_phasing_output" ON "financial"."forecast_output_schedule_phasing" ("output_id");

CREATE UNIQUE INDEX "forecast_output_schedule_phasing_uq2" ON "financial"."forecast_output_schedule_phasing" ("output_id", "budget_code_key", "phase");

CREATE INDEX "idx_forecast_output_staffing_project" ON "financial"."forecast_output_staffing" ("project_key");

CREATE INDEX "idx_forecast_output_staffing_output" ON "financial"."forecast_output_staffing" ("output_id");

CREATE UNIQUE INDEX "forecast_output_staffing_uq2" ON "financial"."forecast_output_staffing" ("output_id", "budget_code_key", "role", "month");

CREATE INDEX "idx_forecast_outputs_run" ON "financial"."forecast_outputs" ("run_id");

CREATE INDEX "idx_forecast_outputs_project" ON "financial"."forecast_outputs" ("project_key");

CREATE INDEX "idx_forecast_package_manifests_run" ON "financial"."forecast_package_manifests" ("run_id");

CREATE INDEX "idx_forecast_package_manifests_project_type" ON "financial"."forecast_package_manifests" ("project_key", "package_type");

CREATE UNIQUE INDEX "forecast_package_manifests_uq2" ON "financial"."forecast_package_manifests" ("package_name");

CREATE INDEX "idx_forecast_project_maturity_snapshots_project" ON "financial"."forecast_project_maturity_snapshots" ("project_key");

CREATE INDEX "idx_forecast_project_maturity_snapshots_run" ON "financial"."forecast_project_maturity_snapshots" ("run_id");

CREATE UNIQUE INDEX "forecast_project_maturity_snapshots_uq2" ON "financial"."forecast_project_maturity_snapshots" ("run_id", "project_key", "source_package");

CREATE INDEX "idx_forecast_project_staffing_absence_project" ON "financial"."forecast_project_staffing_absence_overrides" ("project_key", "active_status");

CREATE INDEX "idx_forecast_project_staffing_review_items_project" ON "financial"."forecast_project_staffing_attribution_review_items" ("project_key", "review_status");

CREATE INDEX "idx_forecast_project_staffing_attribution_rules_lookup" ON "financial"."forecast_project_staffing_attribution_rules" ("project_key", "cost_code", "category");

CREATE INDEX "idx_forecast_project_staffing_config_template" ON "financial"."forecast_project_staffing_config" ("template_id");

CREATE INDEX "idx_forecast_project_staffing_config_person" ON "financial"."forecast_project_staffing_config" ("project_key", "person_name_normalized");

CREATE INDEX "idx_forecast_project_staffing_config_cost_code" ON "financial"."forecast_project_staffing_config" ("project_key", "cost_code");

CREATE INDEX "idx_forecast_project_staffing_config_project" ON "financial"."forecast_project_staffing_config" ("project_key", "active_status");

CREATE INDEX "idx_forecast_project_staffing_snapshot_rows_snapshot" ON "financial"."forecast_project_staffing_snapshot_rows" ("staffing_snapshot_id");

CREATE INDEX "idx_forecast_project_staffing_snapshots_output" ON "financial"."forecast_project_staffing_snapshots" ("output_id");

CREATE INDEX "idx_forecast_project_staffing_snapshots_project" ON "financial"."forecast_project_staffing_snapshots" ("project_key");

CREATE INDEX "idx_forecast_required_assumptions_project" ON "financial"."forecast_required_assumptions" ("project_key");

CREATE INDEX "idx_forecast_required_assumptions_run" ON "financial"."forecast_required_assumptions" ("run_id");

CREATE UNIQUE INDEX "forecast_required_assumptions_uq2" ON "financial"."forecast_required_assumptions" ("run_id", "assumption_type");

CREATE INDEX "idx_forecast_review_items_status" ON "financial"."forecast_review_items" ("status");

CREATE INDEX "idx_forecast_review_items_project" ON "financial"."forecast_review_items" ("project_key");

CREATE INDEX "idx_forecast_review_items_forecast" ON "financial"."forecast_review_items" ("external_forecast_id");

CREATE INDEX "idx_forecast_run_model_versions_project" ON "financial"."forecast_run_model_versions" ("project_key");

CREATE INDEX "idx_forecast_run_model_versions_model" ON "financial"."forecast_run_model_versions" ("model_version_id");

CREATE INDEX "idx_forecast_runs_project_created" ON "financial"."forecast_runs" ("project_key", "created_utc");

CREATE INDEX "idx_forecast_source_ingestions_run" ON "financial"."forecast_source_ingestions" ("run_id");

CREATE INDEX "idx_forecast_source_ingestions_project_kind" ON "financial"."forecast_source_ingestions" ("project_key", "source_kind");

CREATE UNIQUE INDEX "forecast_source_ingestions_uq2" ON "financial"."forecast_source_ingestions" ("project_key", "source_package", "source_sha256");

CREATE INDEX "idx_forecast_staffing_cost_codes_project" ON "financial"."forecast_staffing_cost_codes" ("project_key", "cost_code");

CREATE INDEX "idx_forecast_staffing_template_versions_template" ON "financial"."forecast_staffing_template_versions" ("template_id");

CREATE UNIQUE INDEX "forecast_staffing_template_versions_uq2" ON "financial"."forecast_staffing_template_versions" ("template_id", "version_number");

CREATE UNIQUE INDEX "forecast_staffing_templates_uq2" ON "financial"."forecast_staffing_templates" ("template_key");

CREATE INDEX "idx_forecast_validation_events_project" ON "financial"."forecast_validation_events" ("project_key", "gate_name");

CREATE INDEX "ix_long_term_memory_items_project" ON "core"."long_term_memory_items" ("project_key", "review_status");

CREATE INDEX "ix_long_term_memory_quality_signals_memory" ON "core"."long_term_memory_quality_signals" ("memory_id", "signal_type");

CREATE INDEX "ix_long_term_memory_source_refs_memory" ON "core"."long_term_memory_source_refs" ("memory_id");

CREATE INDEX "ix_meeting_email_candidates_review" ON "core"."meeting_email_relationship_candidates" ("review_required");

CREATE INDEX "ix_meeting_email_candidates_project_event" ON "core"."meeting_email_relationship_candidates" ("project_key", "event_index_id");

CREATE INDEX "ix_meeting_prep_brief_runs_project" ON "core"."meeting_prep_brief_runs" ("project_key", "status");

CREATE INDEX "ix_meeting_prep_brief_sections_run" ON "core"."meeting_prep_brief_sections" ("brief_run_id", "section_kind");

CREATE INDEX "ix_memory_update_candidates_review" ON "core"."memory_update_candidates" ("status", "review_required");

CREATE INDEX "ix_memory_update_reviews_candidate" ON "core"."memory_update_reviews" ("candidate_id", "decision");

CREATE INDEX "ix_model_profile_eval_results_created" ON "core"."model_profile_eval_results" ("created_utc");

CREATE INDEX "ix_model_profile_eval_results_profile" ON "core"."model_profile_eval_results" ("model_profile_id");

CREATE INDEX "ix_model_profile_eval_results_window" ON "core"."model_profile_eval_results" ("window_start", "window_end");

CREATE INDEX "ix_obsidian_index_entries_hash" ON "core"."obsidian_index_entries" ("note_path_hash", "content_hash");

CREATE INDEX "ix_obsidian_index_entries_project" ON "core"."obsidian_index_entries" ("project_key", "source_type", "review_status");

CREATE UNIQUE INDEX "obsidian_index_entries_uq2" ON "core"."obsidian_index_entries" ("manifest_id", "note_path_hash", "section_marker", "content_hash");

CREATE UNIQUE INDEX "obsidian_managed_section_registry_uq2" ON "core"."obsidian_managed_section_registry" ("note_id", "section_key");

CREATE UNIQUE INDEX "obsidian_note_index_uq2" ON "core"."obsidian_note_index" ("vault_profile", "note_path_hash");

CREATE INDEX "idx_pa_validation_receipts_bundle" ON "core"."pa_artifact_validation_receipts" ("promotion_bundle_id", "validation_hash");

CREATE INDEX "idx_pa_promotion_receipts_bundle" ON "core"."pa_promotion_receipts" ("promotion_bundle_id");

CREATE UNIQUE INDEX "parser_outputs_uq1" ON "core"."parser_outputs" ("file_source_record_id", "parser_name", "parser_version", "content_hash");

CREATE INDEX "ix_procore_action_signals_type" ON "procore"."procore_action_signals" ("signal_type");

CREATE INDEX "ix_procore_action_signals_project_status" ON "procore"."procore_action_signals" ("project_key", "signal_status", "importance");

CREATE INDEX "ix_procore_attachment_refs_source" ON "procore"."procore_attachment_refs" ("source_record_key");

CREATE UNIQUE INDEX "procore_custom_field_values_uq2" ON "procore"."procore_custom_field_values" ("record_key", "custom_field_key");

CREATE INDEX "ix_procore_endpoint_capture_pages_run" ON "procore"."procore_endpoint_capture_pages" ("capture_run_id", "endpoint_key");

CREATE INDEX "ix_procore_endpoint_capture_runs_status" ON "procore"."procore_endpoint_capture_runs" ("status", "endpoint_family");

CREATE INDEX "ix_procore_endpoint_raw_payloads_current" ON "procore"."procore_endpoint_raw_payloads" ("endpoint_key", "is_current");

CREATE INDEX "ix_procore_endpoint_raw_payloads_source_ref" ON "procore"."procore_endpoint_raw_payloads" ("source_ref_hash");

CREATE INDEX "ix_procore_endpoint_raw_payloads_endpoint_project" ON "procore"."procore_endpoint_raw_payloads" ("endpoint_key", "project_key");

CREATE UNIQUE INDEX "procore_endpoint_raw_payloads_uq2" ON "procore"."procore_endpoint_raw_payloads" ("endpoint_key", "project_key", "parent_record_id", "record_id", "payload_hash");

CREATE INDEX "idx_procore_ep_billing_periods_record_id" ON "procore"."procore_ep_billing_periods" ("record_id");

CREATE INDEX "idx_procore_ep_billing_periods_raw_payload_id" ON "procore"."procore_ep_billing_periods" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_billing_periods_endpoint_key" ON "procore"."procore_ep_billing_periods" ("endpoint_key");

CREATE INDEX "idx_procore_ep_billing_periods_project_key" ON "procore"."procore_ep_billing_periods" ("project_key");

CREATE INDEX "idx_procore_ep_budget_change_history_record_id" ON "procore"."procore_ep_budget_change_history" ("record_id");

CREATE INDEX "idx_procore_ep_budget_change_history_raw_payload_id" ON "procore"."procore_ep_budget_change_history" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_budget_change_history_endpoint_key" ON "procore"."procore_ep_budget_change_history" ("endpoint_key");

CREATE INDEX "idx_procore_ep_budget_change_history_project_key" ON "procore"."procore_ep_budget_change_history" ("project_key");

CREATE INDEX "idx_procore_ep_budget_detail_columns_current_quality" ON "procore"."procore_ep_budget_detail_columns" ("is_current", "source_quality");

CREATE INDEX "idx_procore_ep_budget_detail_columns_field_path" ON "procore"."procore_ep_budget_detail_columns" ("field_path");

CREATE INDEX "idx_procore_ep_budget_detail_columns_name" ON "procore"."procore_ep_budget_detail_columns" ("name");

CREATE INDEX "idx_procore_ep_budget_detail_columns_budget_view_id" ON "procore"."procore_ep_budget_detail_columns" ("budget_view_id");

CREATE INDEX "idx_procore_ep_budget_detail_columns_parent_record_id" ON "procore"."procore_ep_budget_detail_columns" ("parent_record_id");

CREATE INDEX "idx_procore_ep_budget_detail_columns_record_id" ON "procore"."procore_ep_budget_detail_columns" ("record_id");

CREATE INDEX "idx_procore_ep_budget_detail_columns_raw_payload_id" ON "procore"."procore_ep_budget_detail_columns" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_budget_detail_columns_endpoint_key" ON "procore"."procore_ep_budget_detail_columns" ("endpoint_key");

CREATE INDEX "idx_procore_ep_budget_detail_columns_project_key" ON "procore"."procore_ep_budget_detail_columns" ("project_key");

CREATE INDEX "idx_procore_ep_budget_detail_row_cells_current_quality" ON "procore"."procore_ep_budget_detail_row_cells" ("is_current", "source_quality");

CREATE INDEX "idx_procore_ep_budget_detail_row_cells_field_path" ON "procore"."procore_ep_budget_detail_row_cells" ("field_path");

CREATE INDEX "idx_procore_ep_budget_detail_row_cells_column_name" ON "procore"."procore_ep_budget_detail_row_cells" ("column_name");

CREATE INDEX "idx_procore_ep_budget_detail_row_cells_budget_view_id" ON "procore"."procore_ep_budget_detail_row_cells" ("budget_view_id");

CREATE INDEX "idx_procore_ep_budget_detail_row_cells_project_key" ON "procore"."procore_ep_budget_detail_row_cells" ("project_key");

CREATE INDEX "idx_procore_ep_budget_detail_row_cells_record_key" ON "procore"."procore_ep_budget_detail_row_cells" ("record_key");

CREATE INDEX "idx_procore_ep_budget_detail_rows_current_quality" ON "procore"."procore_ep_budget_detail_rows" ("is_current", "source_quality");

CREATE INDEX "idx_procore_ep_budget_detail_rows_cost_code_id" ON "procore"."procore_ep_budget_detail_rows" ("cost_code_id");

CREATE INDEX "idx_procore_ep_budget_detail_rows_canonical_key" ON "procore"."procore_ep_budget_detail_rows" ("canonical_budget_code_key");

CREATE INDEX "idx_procore_ep_budget_detail_rows_wbs_flat_code" ON "procore"."procore_ep_budget_detail_rows" ("wbs_flat_code");

CREATE INDEX "idx_procore_ep_budget_detail_rows_budget_view_id" ON "procore"."procore_ep_budget_detail_rows" ("budget_view_id");

CREATE INDEX "idx_procore_ep_budget_detail_rows_parent_record_id" ON "procore"."procore_ep_budget_detail_rows" ("parent_record_id");

CREATE INDEX "idx_procore_ep_budget_detail_rows_record_id" ON "procore"."procore_ep_budget_detail_rows" ("record_id");

CREATE INDEX "idx_procore_ep_budget_detail_rows_raw_payload_id" ON "procore"."procore_ep_budget_detail_rows" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_budget_detail_rows_endpoint_key" ON "procore"."procore_ep_budget_detail_rows" ("endpoint_key");

CREATE INDEX "idx_procore_ep_budget_detail_rows_project_key" ON "procore"."procore_ep_budget_detail_rows" ("project_key");

CREATE INDEX "idx_procore_ep_budget_modifications_record_id" ON "procore"."procore_ep_budget_modifications" ("record_id");

CREATE INDEX "idx_procore_ep_budget_modifications_raw_payload_id" ON "procore"."procore_ep_budget_modifications" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_budget_modifications_endpoint_key" ON "procore"."procore_ep_budget_modifications" ("endpoint_key");

CREATE INDEX "idx_procore_ep_budget_modifications_project_key" ON "procore"."procore_ep_budget_modifications" ("project_key");

CREATE INDEX "idx_procore_ep_budget_views_record_id" ON "procore"."procore_ep_budget_views" ("record_id");

CREATE INDEX "idx_procore_ep_budget_views_raw_payload_id" ON "procore"."procore_ep_budget_views" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_budget_views_endpoint_key" ON "procore"."procore_ep_budget_views" ("endpoint_key");

CREATE INDEX "idx_procore_ep_budget_views_project_key" ON "procore"."procore_ep_budget_views" ("project_key");

CREATE INDEX "idx_procore_ep_change_events_record_id" ON "procore"."procore_ep_change_events" ("record_id");

CREATE INDEX "idx_procore_ep_change_events_raw_payload_id" ON "procore"."procore_ep_change_events" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_change_events_endpoint_key" ON "procore"."procore_ep_change_events" ("endpoint_key");

CREATE INDEX "idx_procore_ep_change_events_project_key" ON "procore"."procore_ep_change_events" ("project_key");

CREATE INDEX "idx_procore_ep_change_events_attachments_parent_item_id" ON "procore"."procore_ep_change_events_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_change_events_attachments_raw_payload_id" ON "procore"."procore_ep_change_events_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_change_events_attachments_primary_record_key" ON "procore"."procore_ep_change_events_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_change_events_change_items_parent_item_id" ON "procore"."procore_ep_change_events_change_items" ("parent_item_id");

CREATE INDEX "idx_procore_ep_change_events_change_items_raw_payload_id" ON "procore"."procore_ep_change_events_change_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_change_events_change_items_primary_record_key" ON "procore"."procore_ep_change_events_change_items" ("primary_record_key");

CREATE INDEX "idx_procore_ep_change_events_change_items_budget_code_s_d374f10" ON "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22" ("parent_item_id");

CREATE INDEX "idx_procore_ep_change_events_change_items_budget_code_s_fecc078" ON "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_change_events_change_items_budget_code_s_6703e5b" ON "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22" ("primary_record_key");

CREATE INDEX "idx_procore_ep_change_events_markup_items_parent_item_id" ON "procore"."procore_ep_change_events_markup_items" ("parent_item_id");

CREATE INDEX "idx_procore_ep_change_events_markup_items_raw_payload_id" ON "procore"."procore_ep_change_events_markup_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_change_events_markup_items_primary_record_key" ON "procore"."procore_ep_change_events_markup_items" ("primary_record_key");

CREATE INDEX "idx_procore_ep_change_events_markup_items_wbs_code_segm_43b59f6" ON "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items" ("parent_item_id");

CREATE INDEX "idx_procore_ep_change_events_markup_items_wbs_code_segm_87f6c74" ON "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_change_events_markup_items_wbs_code_segm_586425d" ON "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items" ("primary_record_key");

CREATE INDEX "idx_procore_ep_commitment_attachments_record_id" ON "procore"."procore_ep_commitment_attachments" ("record_id");

CREATE INDEX "idx_procore_ep_commitment_attachments_raw_payload_id" ON "procore"."procore_ep_commitment_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_commitment_attachments_endpoint_key" ON "procore"."procore_ep_commitment_attachments" ("endpoint_key");

CREATE INDEX "idx_procore_ep_commitment_attachments_project_key" ON "procore"."procore_ep_commitment_attachments" ("project_key");

CREATE INDEX "idx_procore_ep_commitment_change_orders_record_id" ON "procore"."procore_ep_commitment_change_orders" ("record_id");

CREATE INDEX "idx_procore_ep_commitment_change_orders_raw_payload_id" ON "procore"."procore_ep_commitment_change_orders" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_commitment_change_orders_endpoint_key" ON "procore"."procore_ep_commitment_change_orders" ("endpoint_key");

CREATE INDEX "idx_procore_ep_commitment_change_orders_project_key" ON "procore"."procore_ep_commitment_change_orders" ("project_key");

CREATE INDEX "idx_procore_ep_commitment_compliance_record_id" ON "procore"."procore_ep_commitment_compliance" ("record_id");

CREATE INDEX "idx_procore_ep_commitment_compliance_raw_payload_id" ON "procore"."procore_ep_commitment_compliance" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_commitment_compliance_endpoint_key" ON "procore"."procore_ep_commitment_compliance" ("endpoint_key");

CREATE INDEX "idx_procore_ep_commitment_compliance_project_key" ON "procore"."procore_ep_commitment_compliance" ("project_key");

CREATE INDEX "idx_procore_ep_commitment_compliance_insurance_document_0b03f8c" ON "procore"."procore_ep_commitment_compliance_insurance_documents" ("parent_item_id");

CREATE INDEX "idx_procore_ep_commitment_compliance_insurance_document_018ad0e" ON "procore"."procore_ep_commitment_compliance_insurance_documents" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_commitment_compliance_insurance_document_fe21747" ON "procore"."procore_ep_commitment_compliance_insurance_documents" ("primary_record_key");

CREATE INDEX "idx_procore_ep_commitment_compliance_insurance_document_4499d53" ON "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf" ("parent_item_id");

CREATE INDEX "idx_procore_ep_commitment_compliance_insurance_document_f38c2e3" ON "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_commitment_compliance_insurance_document_b18d0c9" ON "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf" ("primary_record_key");

CREATE INDEX "idx_procore_ep_commitment_contracts_record_id" ON "procore"."procore_ep_commitment_contracts" ("record_id");

CREATE INDEX "idx_procore_ep_commitment_contracts_raw_payload_id" ON "procore"."procore_ep_commitment_contracts" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_commitment_contracts_endpoint_key" ON "procore"."procore_ep_commitment_contracts" ("endpoint_key");

CREATE INDEX "idx_procore_ep_commitment_contracts_project_key" ON "procore"."procore_ep_commitment_contracts" ("project_key");

CREATE INDEX "idx_procore_ep_commitment_line_items_record_id" ON "procore"."procore_ep_commitment_line_items" ("record_id");

CREATE INDEX "idx_procore_ep_commitment_line_items_raw_payload_id" ON "procore"."procore_ep_commitment_line_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_commitment_line_items_endpoint_key" ON "procore"."procore_ep_commitment_line_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_commitment_line_items_project_key" ON "procore"."procore_ep_commitment_line_items" ("project_key");

CREATE INDEX "idx_procore_ep_daily_log_dcrs_record_id" ON "procore"."procore_ep_daily_log_dcrs" ("record_id");

CREATE INDEX "idx_procore_ep_daily_log_dcrs_raw_payload_id" ON "procore"."procore_ep_daily_log_dcrs" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_dcrs_endpoint_key" ON "procore"."procore_ep_daily_log_dcrs" ("endpoint_key");

CREATE INDEX "idx_procore_ep_daily_log_dcrs_project_key" ON "procore"."procore_ep_daily_log_dcrs" ("project_key");

CREATE INDEX "idx_procore_ep_daily_log_dcrs_attachments_parent_item_id" ON "procore"."procore_ep_daily_log_dcrs_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_daily_log_dcrs_attachments_raw_payload_id" ON "procore"."procore_ep_daily_log_dcrs_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_dcrs_attachments_primary_record_key" ON "procore"."procore_ep_daily_log_dcrs_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_daily_log_deliveries_record_id" ON "procore"."procore_ep_daily_log_deliveries" ("record_id");

CREATE INDEX "idx_procore_ep_daily_log_deliveries_raw_payload_id" ON "procore"."procore_ep_daily_log_deliveries" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_deliveries_endpoint_key" ON "procore"."procore_ep_daily_log_deliveries" ("endpoint_key");

CREATE INDEX "idx_procore_ep_daily_log_deliveries_project_key" ON "procore"."procore_ep_daily_log_deliveries" ("project_key");

CREATE INDEX "idx_procore_ep_daily_log_deliveries_attachments_parent_item_id" ON "procore"."procore_ep_daily_log_deliveries_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_daily_log_deliveries_attachments_raw_payload_id" ON "procore"."procore_ep_daily_log_deliveries_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_deliveries_attachments_primary_32901d6" ON "procore"."procore_ep_daily_log_deliveries_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_daily_log_inspections_record_id" ON "procore"."procore_ep_daily_log_inspections" ("record_id");

CREATE INDEX "idx_procore_ep_daily_log_inspections_raw_payload_id" ON "procore"."procore_ep_daily_log_inspections" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_inspections_endpoint_key" ON "procore"."procore_ep_daily_log_inspections" ("endpoint_key");

CREATE INDEX "idx_procore_ep_daily_log_inspections_project_key" ON "procore"."procore_ep_daily_log_inspections" ("project_key");

CREATE INDEX "idx_procore_ep_daily_log_inspections_attachments_parent_item_id" ON "procore"."procore_ep_daily_log_inspections_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_daily_log_inspections_attachments_raw_payload_id" ON "procore"."procore_ep_daily_log_inspections_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_inspections_attachments_primar_d95b5d8" ON "procore"."procore_ep_daily_log_inspections_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_daily_log_manpower_record_id" ON "procore"."procore_ep_daily_log_manpower" ("record_id");

CREATE INDEX "idx_procore_ep_daily_log_manpower_raw_payload_id" ON "procore"."procore_ep_daily_log_manpower" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_manpower_endpoint_key" ON "procore"."procore_ep_daily_log_manpower" ("endpoint_key");

CREATE INDEX "idx_procore_ep_daily_log_manpower_project_key" ON "procore"."procore_ep_daily_log_manpower" ("project_key");

CREATE INDEX "idx_procore_ep_daily_log_manpower_attachments_parent_item_id" ON "procore"."procore_ep_daily_log_manpower_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_daily_log_manpower_attachments_raw_payload_id" ON "procore"."procore_ep_daily_log_manpower_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_manpower_attachments_primary_r_9c82a38" ON "procore"."procore_ep_daily_log_manpower_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_daily_log_notes_record_id" ON "procore"."procore_ep_daily_log_notes" ("record_id");

CREATE INDEX "idx_procore_ep_daily_log_notes_raw_payload_id" ON "procore"."procore_ep_daily_log_notes" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_notes_endpoint_key" ON "procore"."procore_ep_daily_log_notes" ("endpoint_key");

CREATE INDEX "idx_procore_ep_daily_log_notes_project_key" ON "procore"."procore_ep_daily_log_notes" ("project_key");

CREATE INDEX "idx_procore_ep_daily_log_notes_attachments_parent_item_id" ON "procore"."procore_ep_daily_log_notes_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_daily_log_notes_attachments_raw_payload_id" ON "procore"."procore_ep_daily_log_notes_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_notes_attachments_primary_record_key" ON "procore"."procore_ep_daily_log_notes_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_daily_log_visitor_record_id" ON "procore"."procore_ep_daily_log_visitor" ("record_id");

CREATE INDEX "idx_procore_ep_daily_log_visitor_raw_payload_id" ON "procore"."procore_ep_daily_log_visitor" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_visitor_endpoint_key" ON "procore"."procore_ep_daily_log_visitor" ("endpoint_key");

CREATE INDEX "idx_procore_ep_daily_log_visitor_project_key" ON "procore"."procore_ep_daily_log_visitor" ("project_key");

CREATE INDEX "idx_procore_ep_daily_log_weather_record_id" ON "procore"."procore_ep_daily_log_weather" ("record_id");

CREATE INDEX "idx_procore_ep_daily_log_weather_raw_payload_id" ON "procore"."procore_ep_daily_log_weather" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_daily_log_weather_endpoint_key" ON "procore"."procore_ep_daily_log_weather" ("endpoint_key");

CREATE INDEX "idx_procore_ep_daily_log_weather_project_key" ON "procore"."procore_ep_daily_log_weather" ("project_key");

CREATE INDEX "idx_procore_ep_inspection_items_record_id" ON "procore"."procore_ep_inspection_items" ("record_id");

CREATE INDEX "idx_procore_ep_inspection_items_raw_payload_id" ON "procore"."procore_ep_inspection_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspection_items_endpoint_key" ON "procore"."procore_ep_inspection_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_inspection_items_project_key" ON "procore"."procore_ep_inspection_items" ("project_key");

CREATE INDEX "idx_procore_ep_inspection_items_response_set_responses__2798bc2" ON "procore"."procore_ep_inspection_items_response_set_responses" ("parent_item_id");

CREATE INDEX "idx_procore_ep_inspection_items_response_set_responses__c9ffb14" ON "procore"."procore_ep_inspection_items_response_set_responses" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspection_items_response_set_responses__a4e2045" ON "procore"."procore_ep_inspection_items_response_set_responses" ("primary_record_key");

CREATE INDEX "idx_procore_ep_inspection_sections_record_id" ON "procore"."procore_ep_inspection_sections" ("record_id");

CREATE INDEX "idx_procore_ep_inspection_sections_raw_payload_id" ON "procore"."procore_ep_inspection_sections" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspection_sections_endpoint_key" ON "procore"."procore_ep_inspection_sections" ("endpoint_key");

CREATE INDEX "idx_procore_ep_inspection_sections_project_key" ON "procore"."procore_ep_inspection_sections" ("project_key");

CREATE INDEX "idx_procore_ep_inspections_record_id" ON "procore"."procore_ep_inspections" ("record_id");

CREATE INDEX "idx_procore_ep_inspections_raw_payload_id" ON "procore"."procore_ep_inspections" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspections_endpoint_key" ON "procore"."procore_ep_inspections" ("endpoint_key");

CREATE INDEX "idx_procore_ep_inspections_project_key" ON "procore"."procore_ep_inspections" ("project_key");

CREATE INDEX "idx_procore_ep_inspections_attachments_parent_item_id" ON "procore"."procore_ep_inspections_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_inspections_attachments_raw_payload_id" ON "procore"."procore_ep_inspections_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspections_attachments_primary_record_key" ON "procore"."procore_ep_inspections_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_inspections_distribution_members_parent_item_id" ON "procore"."procore_ep_inspections_distribution_members" ("parent_item_id");

CREATE INDEX "idx_procore_ep_inspections_distribution_members_raw_payload_id" ON "procore"."procore_ep_inspections_distribution_members" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspections_distribution_members_primary_8d31201" ON "procore"."procore_ep_inspections_distribution_members" ("primary_record_key");

CREATE INDEX "idx_procore_ep_inspections_inspectors_parent_item_id" ON "procore"."procore_ep_inspections_inspectors" ("parent_item_id");

CREATE INDEX "idx_procore_ep_inspections_inspectors_raw_payload_id" ON "procore"."procore_ep_inspections_inspectors" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspections_inspectors_primary_record_key" ON "procore"."procore_ep_inspections_inspectors" ("primary_record_key");

CREATE INDEX "idx_procore_ep_inspections_signature_requests_parent_item_id" ON "procore"."procore_ep_inspections_signature_requests" ("parent_item_id");

CREATE INDEX "idx_procore_ep_inspections_signature_requests_raw_payload_id" ON "procore"."procore_ep_inspections_signature_requests" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_inspections_signature_requests_primary_r_ba62056" ON "procore"."procore_ep_inspections_signature_requests" ("primary_record_key");

CREATE INDEX "idx_procore_ep_meetings_record_id" ON "procore"."procore_ep_meetings" ("record_id");

CREATE INDEX "idx_procore_ep_meetings_raw_payload_id" ON "procore"."procore_ep_meetings" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_meetings_endpoint_key" ON "procore"."procore_ep_meetings" ("endpoint_key");

CREATE INDEX "idx_procore_ep_meetings_project_key" ON "procore"."procore_ep_meetings" ("project_key");

CREATE INDEX "idx_procore_ep_observations_record_id" ON "procore"."procore_ep_observations" ("record_id");

CREATE INDEX "idx_procore_ep_observations_raw_payload_id" ON "procore"."procore_ep_observations" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_observations_endpoint_key" ON "procore"."procore_ep_observations" ("endpoint_key");

CREATE INDEX "idx_procore_ep_observations_project_key" ON "procore"."procore_ep_observations" ("project_key");

CREATE INDEX "idx_procore_ep_observations_assignees_parent_item_id" ON "procore"."procore_ep_observations_assignees" ("parent_item_id");

CREATE INDEX "idx_procore_ep_observations_assignees_raw_payload_id" ON "procore"."procore_ep_observations_assignees" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_observations_assignees_primary_record_key" ON "procore"."procore_ep_observations_assignees" ("primary_record_key");

CREATE INDEX "idx_procore_ep_prime_change_order_line_items_record_id" ON "procore"."procore_ep_prime_change_order_line_items" ("record_id");

CREATE INDEX "idx_procore_ep_prime_change_order_line_items_raw_payload_id" ON "procore"."procore_ep_prime_change_order_line_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_prime_change_order_line_items_endpoint_key" ON "procore"."procore_ep_prime_change_order_line_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_prime_change_order_line_items_project_key" ON "procore"."procore_ep_prime_change_order_line_items" ("project_key");

CREATE INDEX "idx_procore_ep_prime_change_orders_record_id" ON "procore"."procore_ep_prime_change_orders" ("record_id");

CREATE INDEX "idx_procore_ep_prime_change_orders_raw_payload_id" ON "procore"."procore_ep_prime_change_orders" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_prime_change_orders_endpoint_key" ON "procore"."procore_ep_prime_change_orders" ("endpoint_key");

CREATE INDEX "idx_procore_ep_prime_change_orders_project_key" ON "procore"."procore_ep_prime_change_orders" ("project_key");

CREATE INDEX "idx_procore_ep_prime_contract_line_items_record_id" ON "procore"."procore_ep_prime_contract_line_items" ("record_id");

CREATE INDEX "idx_procore_ep_prime_contract_line_items_raw_payload_id" ON "procore"."procore_ep_prime_contract_line_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_prime_contract_line_items_endpoint_key" ON "procore"."procore_ep_prime_contract_line_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_prime_contract_line_items_project_key" ON "procore"."procore_ep_prime_contract_line_items" ("project_key");

CREATE INDEX "idx_procore_ep_prime_contracts_record_id" ON "procore"."procore_ep_prime_contracts" ("record_id");

CREATE INDEX "idx_procore_ep_prime_contracts_raw_payload_id" ON "procore"."procore_ep_prime_contracts" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_prime_contracts_endpoint_key" ON "procore"."procore_ep_prime_contracts" ("endpoint_key");

CREATE INDEX "idx_procore_ep_prime_contracts_project_key" ON "procore"."procore_ep_prime_contracts" ("project_key");

CREATE UNIQUE INDEX "idx_procore_ep_projects_project_key_unique" ON "procore"."procore_ep_projects" ("project_key");

CREATE INDEX "idx_procore_ep_projects_record_id" ON "procore"."procore_ep_projects" ("record_id");

CREATE INDEX "idx_procore_ep_projects_raw_payload_id" ON "procore"."procore_ep_projects" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_projects_endpoint_key" ON "procore"."procore_ep_projects" ("endpoint_key");

CREATE INDEX "idx_procore_ep_projects_project_key" ON "procore"."procore_ep_projects" ("project_key");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_6bec471" ON "procore"."procore_ep_projects_custom_fields_custom_field_163287_value" ("parent_item_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_aad5c8e" ON "procore"."procore_ep_projects_custom_fields_custom_field_163287_value" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_ad44f46" ON "procore"."procore_ep_projects_custom_fields_custom_field_163287_value" ("primary_record_key");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_358a865" ON "procore"."procore_ep_projects_custom_fields_custom_field_163290_value" ("parent_item_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_ce6f996" ON "procore"."procore_ep_projects_custom_fields_custom_field_163290_value" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_3bed7dd" ON "procore"."procore_ep_projects_custom_fields_custom_field_163290_value" ("primary_record_key");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_46ed438" ON "procore"."procore_ep_projects_custom_fields_custom_field_163293_value" ("parent_item_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_9e2509e" ON "procore"."procore_ep_projects_custom_fields_custom_field_163293_value" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_fcf3f7e" ON "procore"."procore_ep_projects_custom_fields_custom_field_163293_value" ("primary_record_key");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_1f6fbe2" ON "procore"."procore_ep_projects_custom_fields_custom_field_163296_value" ("parent_item_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_5c2d01d" ON "procore"."procore_ep_projects_custom_fields_custom_field_163296_value" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_0cb3c8d" ON "procore"."procore_ep_projects_custom_fields_custom_field_163296_value" ("primary_record_key");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_9af2209" ON "procore"."procore_ep_projects_custom_fields_custom_field_163299_value" ("parent_item_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_7fb176c" ON "procore"."procore_ep_projects_custom_fields_custom_field_163299_value" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1632_91712c0" ON "procore"."procore_ep_projects_custom_fields_custom_field_163299_value" ("primary_record_key");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1633_584171d" ON "procore"."procore_ep_projects_custom_fields_custom_field_163302_value" ("parent_item_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1633_90b3b65" ON "procore"."procore_ep_projects_custom_fields_custom_field_163302_value" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_projects_custom_fields_custom_field_1633_deabdf9" ON "procore"."procore_ep_projects_custom_fields_custom_field_163302_value" ("primary_record_key");

CREATE INDEX "idx_procore_ep_punch_items_record_id" ON "procore"."procore_ep_punch_items" ("record_id");

CREATE INDEX "idx_procore_ep_punch_items_raw_payload_id" ON "procore"."procore_ep_punch_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_punch_items_endpoint_key" ON "procore"."procore_ep_punch_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_punch_items_project_key" ON "procore"."procore_ep_punch_items" ("project_key");

CREATE INDEX "idx_procore_ep_punch_items_assignees_parent_item_id" ON "procore"."procore_ep_punch_items_assignees" ("parent_item_id");

CREATE INDEX "idx_procore_ep_punch_items_assignees_raw_payload_id" ON "procore"."procore_ep_punch_items_assignees" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_punch_items_assignees_primary_record_key" ON "procore"."procore_ep_punch_items_assignees" ("primary_record_key");

CREATE INDEX "idx_procore_ep_punch_items_assignments_parent_item_id" ON "procore"."procore_ep_punch_items_assignments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_punch_items_assignments_raw_payload_id" ON "procore"."procore_ep_punch_items_assignments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_punch_items_assignments_primary_record_key" ON "procore"."procore_ep_punch_items_assignments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_punch_items_ball_in_court_parent_item_id" ON "procore"."procore_ep_punch_items_ball_in_court" ("parent_item_id");

CREATE INDEX "idx_procore_ep_punch_items_ball_in_court_raw_payload_id" ON "procore"."procore_ep_punch_items_ball_in_court" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_punch_items_ball_in_court_primary_record_key" ON "procore"."procore_ep_punch_items_ball_in_court" ("primary_record_key");

CREATE INDEX "idx_procore_ep_purchase_order_contracts_record_id" ON "procore"."procore_ep_purchase_order_contracts" ("record_id");

CREATE INDEX "idx_procore_ep_purchase_order_contracts_raw_payload_id" ON "procore"."procore_ep_purchase_order_contracts" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_purchase_order_contracts_endpoint_key" ON "procore"."procore_ep_purchase_order_contracts" ("endpoint_key");

CREATE INDEX "idx_procore_ep_purchase_order_contracts_project_key" ON "procore"."procore_ep_purchase_order_contracts" ("project_key");

CREATE INDEX "idx_procore_ep_purchase_order_contracts_custom_fields_c_508be90" ON "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65" ("parent_item_id");

CREATE INDEX "idx_procore_ep_purchase_order_contracts_custom_fields_c_897f908" ON "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_purchase_order_contracts_custom_fields_c_3644ca7" ON "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65" ("primary_record_key");

CREATE INDEX "idx_procore_ep_purchase_order_line_items_record_id" ON "procore"."procore_ep_purchase_order_line_items" ("record_id");

CREATE INDEX "idx_procore_ep_purchase_order_line_items_raw_payload_id" ON "procore"."procore_ep_purchase_order_line_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_purchase_order_line_items_endpoint_key" ON "procore"."procore_ep_purchase_order_line_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_purchase_order_line_items_project_key" ON "procore"."procore_ep_purchase_order_line_items" ("project_key");

CREATE INDEX "idx_procore_ep_purchase_order_line_items_cost_code_line_c9eeee0" ON "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd" ("parent_item_id");

CREATE INDEX "idx_procore_ep_purchase_order_line_items_cost_code_line_56bfd7a" ON "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_purchase_order_line_items_cost_code_line_6ef28e2" ON "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd" ("primary_record_key");

CREATE INDEX "idx_procore_ep_rfis_record_id" ON "procore"."procore_ep_rfis" ("record_id");

CREATE INDEX "idx_procore_ep_rfis_raw_payload_id" ON "procore"."procore_ep_rfis" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfis_endpoint_key" ON "procore"."procore_ep_rfis" ("endpoint_key");

CREATE INDEX "idx_procore_ep_rfis_project_key" ON "procore"."procore_ep_rfis" ("project_key");

CREATE INDEX "idx_procore_ep_rfis_assignees_parent_item_id" ON "procore"."procore_ep_rfis_assignees" ("parent_item_id");

CREATE INDEX "idx_procore_ep_rfis_assignees_raw_payload_id" ON "procore"."procore_ep_rfis_assignees" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfis_assignees_primary_record_key" ON "procore"."procore_ep_rfis_assignees" ("primary_record_key");

CREATE INDEX "idx_procore_ep_rfis_ball_in_courts_parent_item_id" ON "procore"."procore_ep_rfis_ball_in_courts" ("parent_item_id");

CREATE INDEX "idx_procore_ep_rfis_ball_in_courts_raw_payload_id" ON "procore"."procore_ep_rfis_ball_in_courts" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfis_ball_in_courts_primary_record_key" ON "procore"."procore_ep_rfis_ball_in_courts" ("primary_record_key");

CREATE INDEX "idx_procore_ep_rfis_questions_parent_item_id" ON "procore"."procore_ep_rfis_questions" ("parent_item_id");

CREATE INDEX "idx_procore_ep_rfis_questions_raw_payload_id" ON "procore"."procore_ep_rfis_questions" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfis_questions_primary_record_key" ON "procore"."procore_ep_rfis_questions" ("primary_record_key");

CREATE INDEX "idx_procore_ep_rfqs_record_id" ON "procore"."procore_ep_rfqs" ("record_id");

CREATE INDEX "idx_procore_ep_rfqs_raw_payload_id" ON "procore"."procore_ep_rfqs" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfqs_endpoint_key" ON "procore"."procore_ep_rfqs" ("endpoint_key");

CREATE INDEX "idx_procore_ep_rfqs_project_key" ON "procore"."procore_ep_rfqs" ("project_key");

CREATE INDEX "idx_procore_ep_rfqs_attachments_parent_item_id" ON "procore"."procore_ep_rfqs_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_rfqs_attachments_raw_payload_id" ON "procore"."procore_ep_rfqs_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfqs_attachments_primary_record_key" ON "procore"."procore_ep_rfqs_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_rfqs_change_event_attachments_parent_item_id" ON "procore"."procore_ep_rfqs_change_event_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_rfqs_change_event_attachments_raw_payload_id" ON "procore"."procore_ep_rfqs_change_event_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfqs_change_event_attachments_primary_record_key" ON "procore"."procore_ep_rfqs_change_event_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_rfqs_change_event_change_event_line_item_f53ca3b" ON "procore"."procore_ep_rfqs_change_event_change_event_line_items" ("parent_item_id");

CREATE INDEX "idx_procore_ep_rfqs_change_event_change_event_line_item_e623ad0" ON "procore"."procore_ep_rfqs_change_event_change_event_line_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfqs_change_event_change_event_line_item_21ece0e" ON "procore"."procore_ep_rfqs_change_event_change_event_line_items" ("primary_record_key");

CREATE INDEX "idx_procore_ep_rfqs_change_event_change_event_line_item_6e3f805" ON "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d" ("parent_item_id");

CREATE INDEX "idx_procore_ep_rfqs_change_event_change_event_line_item_68d96c8" ON "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_rfqs_change_event_change_event_line_item_055fdc3" ON "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d" ("primary_record_key");

CREATE INDEX "idx_schedule_activities_cost_code" ON "procore"."procore_ep_schedule_activities" ("cost_code");

CREATE INDEX "idx_schedule_activities_schedule" ON "procore"."procore_ep_schedule_activities" ("schedule_id");

CREATE INDEX "idx_schedule_activities_import" ON "procore"."procore_ep_schedule_activities" ("import_id");

CREATE INDEX "idx_schedule_activities_version" ON "procore"."procore_ep_schedule_activities" ("schedule_version_key");

CREATE INDEX "idx_schedule_activities_project" ON "procore"."procore_ep_schedule_activities" ("project_key");

CREATE UNIQUE INDEX "procore_ep_schedule_activities_uq1" ON "procore"."procore_ep_schedule_activities" ("schedule_version_key", "activity_id", "import_id");

CREATE INDEX "idx_schedule_codes_activity" ON "procore"."procore_ep_schedule_activity_code_assignments" ("activity_id");

CREATE INDEX "idx_schedule_codes_version" ON "procore"."procore_ep_schedule_activity_code_assignments" ("schedule_version_key");

CREATE INDEX "idx_schedule_calendars_version" ON "procore"."procore_ep_schedule_calendars" ("schedule_version_key");

CREATE INDEX "idx_schedule_relationships_version" ON "procore"."procore_ep_schedule_relationships" ("schedule_version_key");

CREATE INDEX "idx_schedule_udfs_version" ON "procore"."procore_ep_schedule_udf_values" ("schedule_version_key");

CREATE INDEX "idx_schedule_wbs_version" ON "procore"."procore_ep_schedule_wbs_nodes" ("schedule_version_key");

CREATE INDEX "idx_procore_ep_schedules_record_id" ON "procore"."procore_ep_schedules" ("record_id");

CREATE INDEX "idx_procore_ep_schedules_raw_payload_id" ON "procore"."procore_ep_schedules" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_schedules_endpoint_key" ON "procore"."procore_ep_schedules" ("endpoint_key");

CREATE INDEX "idx_procore_ep_schedules_project_key" ON "procore"."procore_ep_schedules" ("project_key");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_change_order_items_ba99627" ON "procore"."procore_ep_subcontractor_invoice_change_order_items" ("record_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_change_order_items_dc7ddd8" ON "procore"."procore_ep_subcontractor_invoice_change_order_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_change_order_items_3b51140" ON "procore"."procore_ep_subcontractor_invoice_change_order_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_change_order_items_f1d3989" ON "procore"."procore_ep_subcontractor_invoice_change_order_items" ("project_key");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_contract_detail_it_d322e8c" ON "procore"."procore_ep_subcontractor_invoice_contract_detail_items" ("record_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_contract_detail_it_cd0e023" ON "procore"."procore_ep_subcontractor_invoice_contract_detail_items" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_contract_detail_it_0a0af3c" ON "procore"."procore_ep_subcontractor_invoice_contract_detail_items" ("endpoint_key");

CREATE INDEX "idx_procore_ep_subcontractor_invoice_contract_detail_it_acc842d" ON "procore"."procore_ep_subcontractor_invoice_contract_detail_items" ("project_key");

CREATE INDEX "idx_procore_ep_subcontractor_invoices_record_id" ON "procore"."procore_ep_subcontractor_invoices" ("record_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoices_raw_payload_id" ON "procore"."procore_ep_subcontractor_invoices" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoices_endpoint_key" ON "procore"."procore_ep_subcontractor_invoices" ("endpoint_key");

CREATE INDEX "idx_procore_ep_subcontractor_invoices_project_key" ON "procore"."procore_ep_subcontractor_invoices" ("project_key");

CREATE INDEX "idx_procore_ep_subcontractor_invoices_attachments_paren_e0b2dec" ON "procore"."procore_ep_subcontractor_invoices_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoices_attachments_raw_p_b9368f3" ON "procore"."procore_ep_subcontractor_invoices_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_subcontractor_invoices_attachments_prima_37a00db" ON "procore"."procore_ep_subcontractor_invoices_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_submittals_record_id" ON "procore"."procore_ep_submittals" ("record_id");

CREATE INDEX "idx_procore_ep_submittals_raw_payload_id" ON "procore"."procore_ep_submittals" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_submittals_endpoint_key" ON "procore"."procore_ep_submittals" ("endpoint_key");

CREATE INDEX "idx_procore_ep_submittals_project_key" ON "procore"."procore_ep_submittals" ("project_key");

CREATE INDEX "idx_procore_ep_submittals_approvers_parent_item_id" ON "procore"."procore_ep_submittals_approvers" ("parent_item_id");

CREATE INDEX "idx_procore_ep_submittals_approvers_raw_payload_id" ON "procore"."procore_ep_submittals_approvers" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_submittals_approvers_primary_record_key" ON "procore"."procore_ep_submittals_approvers" ("primary_record_key");

CREATE INDEX "idx_procore_ep_submittals_approvers_attachments_parent_item_id" ON "procore"."procore_ep_submittals_approvers_attachments" ("parent_item_id");

CREATE INDEX "idx_procore_ep_submittals_approvers_attachments_raw_payload_id" ON "procore"."procore_ep_submittals_approvers_attachments" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_submittals_approvers_attachments_primary_ac5e3ec" ON "procore"."procore_ep_submittals_approvers_attachments" ("primary_record_key");

CREATE INDEX "idx_procore_ep_submittals_ball_in_court_parent_item_id" ON "procore"."procore_ep_submittals_ball_in_court" ("parent_item_id");

CREATE INDEX "idx_procore_ep_submittals_ball_in_court_raw_payload_id" ON "procore"."procore_ep_submittals_ball_in_court" ("raw_payload_id");

CREATE INDEX "idx_procore_ep_submittals_ball_in_court_primary_record_key" ON "procore"."procore_ep_submittals_ball_in_court" ("primary_record_key");

CREATE INDEX "ix_procore_financial_amount_facts_project_name" ON "procore"."procore_financial_amount_facts" ("project_key", "amount_name");

CREATE INDEX "ix_procore_financial_billing_periods_project_status" ON "procore"."procore_financial_billing_periods" ("project_key", "status");

CREATE INDEX "ix_procore_financial_budget_changes_project_kind" ON "procore"."procore_financial_budget_changes" ("project_key", "budget_change_kind");

CREATE INDEX "ix_procore_financial_change_order_line_items_parent" ON "procore"."procore_financial_change_order_line_items" ("change_order_record_key");

CREATE INDEX "ix_procore_financial_change_orders_project_status" ON "procore"."procore_financial_change_orders" ("project_key", "status", "executed", "paid");

CREATE INDEX "ix_procore_financial_compliance_documents_project_status" ON "procore"."procore_financial_compliance_documents" ("project_key", "status");

CREATE INDEX "ix_procore_financial_contracts_project_family" ON "procore"."procore_financial_contracts" ("project_key", "contract_family", "status");

CREATE INDEX "ix_procore_financial_line_items_parent" ON "procore"."procore_financial_line_items" ("parent_record_key");

CREATE INDEX "ix_procore_financial_subcontractor_invoices_project_filters" ON "procore"."procore_financial_subcontractor_invoices" ("project_key", "status", "billing_period_id", "vendor_id");

CREATE UNIQUE INDEX "procore_inspection_evidence_rules_uq2" ON "procore"."procore_inspection_evidence_rules" ("project_key", "item_id");

CREATE INDEX "ix_procore_inspection_items_project_status" ON "procore"."procore_inspection_items" ("project_key", "is_unanswered", "is_deficient");

CREATE UNIQUE INDEX "procore_inspection_items_uq2" ON "procore"."procore_inspection_items" ("project_key", "item_id");

CREATE UNIQUE INDEX "procore_inspection_records_uq2" ON "procore"."procore_inspection_records" ("project_key", "inspection_id");

CREATE UNIQUE INDEX "procore_inspection_response_options_uq2" ON "procore"."procore_inspection_response_options" ("project_key", "response_set_id", "response_option_id");

CREATE UNIQUE INDEX "procore_inspection_response_sets_uq2" ON "procore"."procore_inspection_response_sets" ("project_key", "response_set_id");

CREATE UNIQUE INDEX "procore_inspection_sections_uq2" ON "procore"."procore_inspection_sections" ("project_key", "section_id");

CREATE INDEX "ix_procore_change_events_category" ON "procore"."procore_live_record_change_events" ("change_category");

CREATE INDEX "ix_procore_change_events_project_detected" ON "procore"."procore_live_record_change_events" ("project_key", "detected_at_utc");

CREATE INDEX "ix_procore_change_events_record_detected" ON "procore"."procore_live_record_change_events" ("record_key", "detected_at_utc");

CREATE INDEX "ix_procore_snapshots_project_endpoint" ON "procore"."procore_live_record_snapshots" ("project_key", "endpoint_id", "observed_at_utc");

CREATE INDEX "ix_procore_snapshots_record_observed" ON "procore"."procore_live_record_snapshots" ("record_key", "observed_at_utc");

CREATE UNIQUE INDEX "procore_live_record_snapshots_uq2" ON "procore"."procore_live_record_snapshots" ("record_key", "canonical_hash");

CREATE INDEX "ix_procore_state_index_project_endpoint" ON "procore"."procore_live_record_state_index" ("project_key", "endpoint_id");

CREATE INDEX "ix_procore_live_records_endpoint" ON "procore"."procore_live_records" ("endpoint_id", "project_key");

CREATE INDEX "ix_procore_live_records_review" ON "procore"."procore_live_records" ("review_required");

CREATE INDEX "ix_procore_live_sync_runs_endpoint" ON "procore"."procore_live_sync_runs" ("endpoint_id", "project_key");

CREATE INDEX "ix_procore_raw_attachments_raw_payload" ON "procore"."procore_raw_attachments" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_attachments_source_ref" ON "procore"."procore_raw_attachments" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_attachments_project_date" ON "procore"."procore_raw_attachments" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_attachments_project_status" ON "procore"."procore_raw_attachments" ("project_key", "status");

CREATE INDEX "ix_procore_raw_attachments_endpoint_project" ON "procore"."procore_raw_attachments" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_budget_changes_raw_payload" ON "procore"."procore_raw_budget_changes" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_budget_changes_source_ref" ON "procore"."procore_raw_budget_changes" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_budget_changes_project_date" ON "procore"."procore_raw_budget_changes" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_budget_changes_project_status" ON "procore"."procore_raw_budget_changes" ("project_key", "status");

CREATE INDEX "ix_procore_raw_budget_changes_endpoint_project" ON "procore"."procore_raw_budget_changes" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_budget_columns_raw_payload" ON "procore"."procore_raw_budget_columns" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_budget_columns_source_ref" ON "procore"."procore_raw_budget_columns" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_budget_columns_project_date" ON "procore"."procore_raw_budget_columns" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_budget_columns_project_status" ON "procore"."procore_raw_budget_columns" ("project_key", "status");

CREATE INDEX "ix_procore_raw_budget_columns_endpoint_project" ON "procore"."procore_raw_budget_columns" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_budget_rows_raw_payload" ON "procore"."procore_raw_budget_rows" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_budget_rows_source_ref" ON "procore"."procore_raw_budget_rows" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_budget_rows_project_date" ON "procore"."procore_raw_budget_rows" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_budget_rows_project_status" ON "procore"."procore_raw_budget_rows" ("project_key", "status");

CREATE INDEX "ix_procore_raw_budget_rows_endpoint_project" ON "procore"."procore_raw_budget_rows" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_change_event_comments_raw_payload" ON "procore"."procore_raw_change_event_comments" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_change_event_comments_source_ref" ON "procore"."procore_raw_change_event_comments" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_change_event_comments_project_date" ON "procore"."procore_raw_change_event_comments" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_change_event_comments_project_status" ON "procore"."procore_raw_change_event_comments" ("project_key", "status");

CREATE INDEX "ix_procore_raw_change_event_comments_endpoint_project" ON "procore"."procore_raw_change_event_comments" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_change_order_line_items_raw_payload" ON "procore"."procore_raw_change_order_line_items" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_change_order_line_items_source_ref" ON "procore"."procore_raw_change_order_line_items" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_change_order_line_items_project_date" ON "procore"."procore_raw_change_order_line_items" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_change_order_line_items_project_status" ON "procore"."procore_raw_change_order_line_items" ("project_key", "status");

CREATE INDEX "ix_procore_raw_change_order_line_items_endpoint_project" ON "procore"."procore_raw_change_order_line_items" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_change_orders_raw_payload" ON "procore"."procore_raw_change_orders" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_change_orders_source_ref" ON "procore"."procore_raw_change_orders" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_change_orders_project_date" ON "procore"."procore_raw_change_orders" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_change_orders_project_status" ON "procore"."procore_raw_change_orders" ("project_key", "status");

CREATE INDEX "ix_procore_raw_change_orders_endpoint_project" ON "procore"."procore_raw_change_orders" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_contract_line_items_raw_payload" ON "procore"."procore_raw_contract_line_items" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_contract_line_items_source_ref" ON "procore"."procore_raw_contract_line_items" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_contract_line_items_project_date" ON "procore"."procore_raw_contract_line_items" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_contract_line_items_project_status" ON "procore"."procore_raw_contract_line_items" ("project_key", "status");

CREATE INDEX "ix_procore_raw_contract_line_items_endpoint_project" ON "procore"."procore_raw_contract_line_items" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_contracts_raw_payload" ON "procore"."procore_raw_contracts" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_contracts_source_ref" ON "procore"."procore_raw_contracts" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_contracts_project_date" ON "procore"."procore_raw_contracts" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_contracts_project_status" ON "procore"."procore_raw_contracts" ("project_key", "status");

CREATE INDEX "ix_procore_raw_contracts_endpoint_project" ON "procore"."procore_raw_contracts" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_cost_code_dimensions_raw_payload" ON "procore"."procore_raw_cost_code_dimensions" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_cost_code_dimensions_source_ref" ON "procore"."procore_raw_cost_code_dimensions" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_cost_code_dimensions_project_date" ON "procore"."procore_raw_cost_code_dimensions" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_cost_code_dimensions_project_status" ON "procore"."procore_raw_cost_code_dimensions" ("project_key", "status");

CREATE INDEX "ix_procore_raw_cost_code_dimensions_endpoint_project" ON "procore"."procore_raw_cost_code_dimensions" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_daily_logs_raw_payload" ON "procore"."procore_raw_daily_logs" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_daily_logs_source_ref" ON "procore"."procore_raw_daily_logs" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_daily_logs_project_date" ON "procore"."procore_raw_daily_logs" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_daily_logs_project_status" ON "procore"."procore_raw_daily_logs" ("project_key", "status");

CREATE INDEX "ix_procore_raw_daily_logs_endpoint_project" ON "procore"."procore_raw_daily_logs" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_date_dimensions_raw_payload" ON "procore"."procore_raw_date_dimensions" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_date_dimensions_source_ref" ON "procore"."procore_raw_date_dimensions" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_date_dimensions_project_date" ON "procore"."procore_raw_date_dimensions" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_date_dimensions_project_status" ON "procore"."procore_raw_date_dimensions" ("project_key", "status");

CREATE INDEX "ix_procore_raw_date_dimensions_endpoint_project" ON "procore"."procore_raw_date_dimensions" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_invoice_items_raw_payload" ON "procore"."procore_raw_invoice_items" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_invoice_items_source_ref" ON "procore"."procore_raw_invoice_items" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_invoice_items_project_date" ON "procore"."procore_raw_invoice_items" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_invoice_items_project_status" ON "procore"."procore_raw_invoice_items" ("project_key", "status");

CREATE INDEX "ix_procore_raw_invoice_items_endpoint_project" ON "procore"."procore_raw_invoice_items" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_invoices_raw_payload" ON "procore"."procore_raw_invoices" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_invoices_source_ref" ON "procore"."procore_raw_invoices" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_invoices_project_date" ON "procore"."procore_raw_invoices" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_invoices_project_status" ON "procore"."procore_raw_invoices" ("project_key", "status");

CREATE INDEX "ix_procore_raw_invoices_endpoint_project" ON "procore"."procore_raw_invoices" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_meeting_details_raw_payload" ON "procore"."procore_raw_meeting_details" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_meeting_details_source_ref" ON "procore"."procore_raw_meeting_details" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_meeting_details_project_date" ON "procore"."procore_raw_meeting_details" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_meeting_details_project_status" ON "procore"."procore_raw_meeting_details" ("project_key", "status");

CREATE INDEX "ix_procore_raw_meeting_details_endpoint_project" ON "procore"."procore_raw_meeting_details" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_meeting_topics_raw_payload" ON "procore"."procore_raw_meeting_topics" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_meeting_topics_source_ref" ON "procore"."procore_raw_meeting_topics" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_meeting_topics_project_date" ON "procore"."procore_raw_meeting_topics" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_meeting_topics_project_status" ON "procore"."procore_raw_meeting_topics" ("project_key", "status");

CREATE INDEX "ix_procore_raw_meeting_topics_endpoint_project" ON "procore"."procore_raw_meeting_topics" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_project_dimensions_raw_payload" ON "procore"."procore_raw_project_dimensions" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_project_dimensions_source_ref" ON "procore"."procore_raw_project_dimensions" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_project_dimensions_project_date" ON "procore"."procore_raw_project_dimensions" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_project_dimensions_project_status" ON "procore"."procore_raw_project_dimensions" ("project_key", "status");

CREATE INDEX "ix_procore_raw_project_dimensions_endpoint_project" ON "procore"."procore_raw_project_dimensions" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_rfi_responses_raw_payload" ON "procore"."procore_raw_rfi_responses" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_rfi_responses_source_ref" ON "procore"."procore_raw_rfi_responses" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_rfi_responses_project_date" ON "procore"."procore_raw_rfi_responses" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_rfi_responses_project_status" ON "procore"."procore_raw_rfi_responses" ("project_key", "status");

CREATE INDEX "ix_procore_raw_rfi_responses_endpoint_project" ON "procore"."procore_raw_rfi_responses" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_rfq_responses_raw_payload" ON "procore"."procore_raw_rfq_responses" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_rfq_responses_source_ref" ON "procore"."procore_raw_rfq_responses" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_rfq_responses_project_date" ON "procore"."procore_raw_rfq_responses" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_rfq_responses_project_status" ON "procore"."procore_raw_rfq_responses" ("project_key", "status");

CREATE INDEX "ix_procore_raw_rfq_responses_endpoint_project" ON "procore"."procore_raw_rfq_responses" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_status_dimensions_raw_payload" ON "procore"."procore_raw_status_dimensions" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_status_dimensions_source_ref" ON "procore"."procore_raw_status_dimensions" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_status_dimensions_project_date" ON "procore"."procore_raw_status_dimensions" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_status_dimensions_project_status" ON "procore"."procore_raw_status_dimensions" ("project_key", "status");

CREATE INDEX "ix_procore_raw_status_dimensions_endpoint_project" ON "procore"."procore_raw_status_dimensions" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_raw_submittal_packages_raw_payload" ON "procore"."procore_raw_submittal_packages" ("raw_payload_id");

CREATE INDEX "ix_procore_raw_submittal_packages_source_ref" ON "procore"."procore_raw_submittal_packages" ("source_ref_hash");

CREATE INDEX "ix_procore_raw_submittal_packages_project_date" ON "procore"."procore_raw_submittal_packages" ("project_key", "business_date");

CREATE INDEX "ix_procore_raw_submittal_packages_project_status" ON "procore"."procore_raw_submittal_packages" ("project_key", "status");

CREATE INDEX "ix_procore_raw_submittal_packages_endpoint_project" ON "procore"."procore_raw_submittal_packages" ("endpoint_key", "project_key");

CREATE INDEX "ix_procore_record_edges_to_entity" ON "procore"."procore_record_edges" ("to_entity_key");

CREATE INDEX "ix_procore_record_edges_to_record" ON "procore"."procore_record_edges" ("to_record_key");

CREATE INDEX "ix_procore_record_edges_from" ON "procore"."procore_record_edges" ("from_record_key");

CREATE INDEX "ix_procore_timeline_record_time" ON "procore"."procore_record_timeline_events" ("record_key", "event_time_utc");

CREATE INDEX "ix_procore_timeline_project_time" ON "procore"."procore_record_timeline_events" ("project_key", "event_time_utc");

CREATE INDEX "idx_procore_synced_entities_project_endpoint" ON "procore"."procore_synced_entities" ("source_project_key", "endpoint_id");

CREATE UNIQUE INDEX "procore_synced_entities_uq1" ON "procore"."procore_synced_entities" ("source_project_key", "endpoint_id", "entity_stable_key");

CREATE UNIQUE INDEX "procore_text_intelligence_uq2" ON "procore"."procore_text_intelligence" ("record_key", "source_field_path", "text_hash");

CREATE INDEX "ix_project_issue_history_items_project" ON "core"."project_issue_history_items" ("project_key", "status", "review_required");

CREATE INDEX "ix_project_risk_digest_items_project" ON "core"."project_risk_digest_items" ("project_key", "risk_source_class", "review_required");

CREATE INDEX "idx_project_schedule_baseline_project" ON "schedule"."project_schedule_baseline_selections" ("project_key", "current_schedule_version_key");

CREATE UNIQUE INDEX "idx_project_schedule_baseline_active" ON "schedule"."project_schedule_baseline_selections" ("project_key", "current_schedule_version_key", "selection_status")
    WHERE "selection_status"='active';

CREATE INDEX "idx_ps_named_baseline_review_events_item" ON "schedule"."project_schedule_named_baseline_review_item_events" ("review_item_id", "created_at");

CREATE INDEX "idx_ps_named_baseline_review_project_scope" ON "schedule"."project_schedule_named_baseline_review_items" ("project_key", "comparison_basis", "baseline_schedule_version_key", "current_schedule_version_key");

CREATE UNIQUE INDEX "idx_ps_named_baseline_review_identity" ON "schedule"."project_schedule_named_baseline_review_items" ("project_key", "current_schedule_version_key", "comparison_basis", "baseline_schedule_version_key", "source_stable_key", "source_metric_key", "source_signal_type", COALESCE("source_activity_id", ''));

CREATE INDEX "idx_project_schedule_named_baseline_project" ON "schedule"."project_schedule_named_baseline_slots" ("project_key", "is_active");

CREATE UNIQUE INDEX "idx_project_schedule_named_baseline_active_slot" ON "schedule"."project_schedule_named_baseline_slots" ("project_key", "slot_key")
    WHERE "is_active" = 1;

CREATE INDEX "idx_project_schedule_review_item_events_project" ON "schedule"."project_schedule_review_item_events" ("project_key", "schedule_version_key");

CREATE INDEX "idx_project_schedule_review_item_events_item" ON "schedule"."project_schedule_review_item_events" ("review_item_id", "created_at");

CREATE INDEX "idx_project_schedule_review_items_stable_key" ON "schedule"."project_schedule_review_items" ("project_key", "stable_item_key");

CREATE INDEX "idx_project_schedule_review_items_project_status" ON "schedule"."project_schedule_review_items" ("project_key", "review_status");

CREATE UNIQUE INDEX "idx_project_schedule_review_items_version_key" ON "schedule"."project_schedule_review_items" ("project_key", "schedule_version_key", "stable_item_key");

CREATE INDEX "idx_project_schedule_series_membership_project_status" ON "schedule"."project_schedule_series_membership" ("project_key", "membership_status");

CREATE UNIQUE INDEX "idx_project_schedule_series_membership_version" ON "schedule"."project_schedule_series_membership" ("project_key", "schedule_version_key");

CREATE INDEX "ix_project_source_coverage_project_domain" ON "core"."project_source_coverage_mart" ("project_key", "source_domain");

CREATE INDEX "ix_query_tool_receipts_tool" ON "core"."query_tool_receipts" ("tool_name", "project_key", "status");

CREATE INDEX "ix_ranking_policy_eval_items_family" ON "core"."ranking_policy_eval_items" ("candidate_family");

CREATE INDEX "ix_ranking_policy_eval_items_candidate" ON "core"."ranking_policy_eval_items" ("daily_brief_action_candidate_id");

CREATE INDEX "ix_ranking_policy_eval_items_ranking_run" ON "core"."ranking_policy_eval_items" ("ranking_run_id");

CREATE INDEX "ix_ranking_policy_eval_items_run" ON "core"."ranking_policy_eval_items" ("eval_run_id");

CREATE INDEX "ix_ranking_policy_eval_runs_created" ON "core"."ranking_policy_eval_runs" ("created_utc");

CREATE INDEX "ix_ranking_policy_eval_runs_mode" ON "core"."ranking_policy_eval_runs" ("eval_mode");

CREATE INDEX "ix_ranking_policy_eval_runs_policy" ON "core"."ranking_policy_eval_runs" ("policy_version");

CREATE INDEX "ix_ranking_policy_eval_runs_window" ON "core"."ranking_policy_eval_runs" ("window_start", "window_end");

CREATE INDEX "ix_relationship_quality_project_status" ON "core"."relationship_quality_mart" ("project_key", "relationship_status");

CREATE INDEX "ix_relationship_resolution_to" ON "core"."relationship_resolution_queue" ("to_canonical_record_id");

CREATE INDEX "ix_relationship_resolution_from" ON "core"."relationship_resolution_queue" ("from_canonical_record_id");

CREATE INDEX "ix_relationship_resolution_status_confidence" ON "core"."relationship_resolution_queue" ("relationship_status", "confidence_class");

CREATE INDEX "ix_retrieval_query_receipts_project" ON "core"."retrieval_query_receipts" ("project_key", "created_utc");

CREATE INDEX "idx_schedule_baseline_activities_version" ON "schedule"."schedule_baseline_activities" ("current_schedule_version_key");

CREATE INDEX "idx_schedule_baseline_activities_project" ON "schedule"."schedule_baseline_activities" ("baseline_project_key");

CREATE INDEX "idx_schedule_baseline_crosswalk_version" ON "schedule"."schedule_baseline_activity_crosswalk" ("current_schedule_version_key");

CREATE INDEX "idx_schedule_baseline_health_facts_version" ON "schedule"."schedule_baseline_health_facts" ("current_schedule_version_key");

CREATE INDEX "idx_schedule_baseline_projects_version" ON "schedule"."schedule_baseline_projects" ("current_schedule_version_key");

CREATE INDEX "idx_schedule_baseline_relationships_project" ON "schedule"."schedule_baseline_relationships" ("baseline_project_key");

CREATE INDEX "idx_schedule_distributions_run" ON "schedule"."schedule_cost_distributions" ("mapping_run_id");

CREATE INDEX "idx_schedule_candidates_run" ON "schedule"."schedule_cost_mapping_candidates" ("mapping_run_id");

CREATE INDEX "idx_schedule_mapping_runs_version" ON "schedule"."schedule_cost_mapping_runs" ("schedule_version_key");

CREATE INDEX "idx_schedule_mapping_runs_project" ON "schedule"."schedule_cost_mapping_runs" ("project_key");

CREATE INDEX "idx_schedule_weighting_project" ON "schedule"."schedule_cost_weighting_results" ("project_key");

CREATE INDEX "idx_schedule_cpm_activity_results_run" ON "schedule"."schedule_cpm_activity_results" ("cpm_run_id");

CREATE INDEX "idx_schedule_cpm_activity_results_version" ON "schedule"."schedule_cpm_activity_results" ("schedule_version_key");

CREATE INDEX "idx_schedule_cpm_diagnostics_activity" ON "schedule"."schedule_cpm_diagnostics" ("activity_id");

CREATE INDEX "idx_schedule_cpm_diagnostics_version" ON "schedule"."schedule_cpm_diagnostics" ("schedule_version_key");

CREATE INDEX "idx_schedule_cpm_diagnostics_run" ON "schedule"."schedule_cpm_diagnostics" ("cpm_run_id");

CREATE INDEX "idx_schedule_cpm_import_obs_version" ON "schedule"."schedule_cpm_import_observability" ("schedule_version_key");

CREATE UNIQUE INDEX "idx_schedule_cpm_import_obs_import" ON "schedule"."schedule_cpm_import_observability" ("import_id");

CREATE INDEX "idx_schedule_cpm_path_activities_path" ON "schedule"."schedule_cpm_path_activities" ("path_id");

CREATE INDEX "idx_schedule_cpm_path_activities_run" ON "schedule"."schedule_cpm_path_activities" ("cpm_run_id");

CREATE INDEX "idx_schedule_cpm_paths_version" ON "schedule"."schedule_cpm_paths" ("schedule_version_key");

CREATE INDEX "idx_schedule_cpm_paths_run" ON "schedule"."schedule_cpm_paths" ("cpm_run_id");

CREATE INDEX "idx_schedule_cpm_relationship_results_version" ON "schedule"."schedule_cpm_relationship_results" ("schedule_version_key");

CREATE INDEX "idx_schedule_cpm_relationship_results_run" ON "schedule"."schedule_cpm_relationship_results" ("cpm_run_id");

CREATE INDEX "idx_schedule_cpm_runs_project" ON "schedule"."schedule_cpm_runs" ("project_key");

CREATE INDEX "idx_schedule_cpm_runs_version" ON "schedule"."schedule_cpm_runs" ("schedule_version_key");

CREATE INDEX "idx_schedule_file_imports_version" ON "schedule"."schedule_file_imports" ("schedule_version_key");

CREATE INDEX "idx_schedule_file_imports_status" ON "schedule"."schedule_file_imports" ("import_status");

CREATE INDEX "idx_schedule_file_imports_project" ON "schedule"."schedule_file_imports" ("project_key");

CREATE INDEX "idx_schedule_identities_source_project" ON "schedule"."schedule_identities" ("project_key", "normalized_source_project_id", "normalized_source_project_name");

CREATE INDEX "idx_schedule_identities_latest_version" ON "schedule"."schedule_identities" ("latest_schedule_version_key");

CREATE INDEX "idx_schedule_identities_project" ON "schedule"."schedule_identities" ("project_key");

CREATE INDEX "idx_schedule_identity_manual_actions_target" ON "schedule"."schedule_identity_manual_actions" ("target_identity_key");

CREATE INDEX "idx_schedule_identity_manual_actions_source" ON "schedule"."schedule_identity_manual_actions" ("source_identity_key");

CREATE INDEX "idx_schedule_identity_manual_actions_version" ON "schedule"."schedule_identity_manual_actions" ("schedule_version_key");

CREATE INDEX "idx_schedule_identity_manual_actions_project" ON "schedule"."schedule_identity_manual_actions" ("project_key");

CREATE INDEX "idx_schedule_import_package_files_package" ON "schedule"."schedule_import_package_files" ("package_id");

CREATE INDEX "idx_schedule_import_packages_version" ON "schedule"."schedule_import_packages" ("selected_current_schedule_version_key");

CREATE INDEX "idx_schedule_import_packages_import" ON "schedule"."schedule_import_packages" ("import_id");

CREATE INDEX "idx_schedule_package_equivalence_candidate" ON "schedule"."schedule_package_equivalence_facts" ("candidate_source_file_id");

CREATE INDEX "idx_schedule_package_equivalence_project" ON "schedule"."schedule_package_equivalence_facts" ("project_key");

CREATE INDEX "idx_schedule_package_equivalence_version" ON "schedule"."schedule_package_equivalence_facts" ("schedule_version_key");

CREATE INDEX "idx_schedule_package_equivalence_package" ON "schedule"."schedule_package_equivalence_facts" ("package_id");

CREATE INDEX "idx_schedule_package_field_lineage_family" ON "schedule"."schedule_package_field_lineage" ("field_family");

CREATE INDEX "idx_schedule_package_field_lineage_project" ON "schedule"."schedule_package_field_lineage" ("project_key");

CREATE INDEX "idx_schedule_package_field_lineage_version" ON "schedule"."schedule_package_field_lineage" ("schedule_version_key");

CREATE INDEX "idx_schedule_package_field_lineage_package" ON "schedule"."schedule_package_field_lineage" ("package_id");

CREATE INDEX "idx_sq_runs_latest" ON "schedule"."schedule_quality_evaluation_runs" ("schedule_version_key", "is_latest");

CREATE INDEX "idx_sq_runs_status" ON "schedule"."schedule_quality_evaluation_runs" ("status");

CREATE INDEX "idx_sq_runs_version" ON "schedule"."schedule_quality_evaluation_runs" ("schedule_version_key");

CREATE UNIQUE INDEX "schedule_quality_evaluation_runs_uq2" ON "schedule"."schedule_quality_evaluation_runs" ("schedule_version_key", "idempotency_key");

CREATE INDEX "idx_schedule_quality_run" ON "schedule"."schedule_quality_findings" ("schedule_version_key", "evaluation_run_id");

CREATE INDEX "idx_schedule_quality_version" ON "schedule"."schedule_quality_findings" ("schedule_version_key");

CREATE INDEX "idx_sq_scorecards_version" ON "schedule"."schedule_quality_scorecards" ("schedule_version_key");

CREATE INDEX "idx_schedule_capabilities_package" ON "schedule"."schedule_source_capabilities" ("package_id");

CREATE INDEX "idx_schedule_capabilities_version" ON "schedule"."schedule_source_capabilities" ("schedule_version_key");

CREATE INDEX "idx_schedule_diff_detail_requires_attention" ON "schedule"."schedule_version_diff_detail_facts" ("requires_attention");

CREATE INDEX "idx_schedule_diff_detail_severity" ON "schedule"."schedule_version_diff_detail_facts" ("severity");

CREATE INDEX "idx_schedule_diff_detail_activity" ON "schedule"."schedule_version_diff_detail_facts" ("activity_id");

CREATE INDEX "idx_schedule_diff_detail_domain_type" ON "schedule"."schedule_version_diff_detail_facts" ("change_domain", "change_type");

CREATE INDEX "idx_schedule_diff_detail_project" ON "schedule"."schedule_version_diff_detail_facts" ("project_key");

CREATE INDEX "idx_schedule_diff_detail_diff" ON "schedule"."schedule_version_diff_detail_facts" ("diff_id");

CREATE INDEX "idx_schedule_version_diff_facts_to_version" ON "schedule"."schedule_version_diff_facts" ("to_schedule_version_key");

CREATE INDEX "idx_schedule_diff_impact_rollups_activity" ON "schedule"."schedule_version_diff_impact_rollups" ("activity_id");

CREATE INDEX "idx_schedule_diff_impact_rollups_wbs" ON "schedule"."schedule_version_diff_impact_rollups" ("wbs_code");

CREATE INDEX "idx_schedule_diff_impact_rollups_impact_level" ON "schedule"."schedule_version_diff_impact_rollups" ("impact_level");

CREATE INDEX "idx_schedule_diff_impact_rollups_attention" ON "schedule"."schedule_version_diff_impact_rollups" ("requires_attention");

CREATE INDEX "idx_schedule_diff_impact_rollups_identity_safe" ON "schedule"."schedule_version_diff_impact_rollups" ("identity_safe");

CREATE INDEX "idx_schedule_diff_impact_rollups_type" ON "schedule"."schedule_version_diff_impact_rollups" ("rollup_type");

CREATE INDEX "idx_schedule_diff_impact_rollups_project" ON "schedule"."schedule_version_diff_impact_rollups" ("project_key");

CREATE INDEX "idx_schedule_diff_impact_rollups_diff" ON "schedule"."schedule_version_diff_impact_rollups" ("diff_id");

CREATE INDEX "idx_schedule_diffs_project" ON "schedule"."schedule_version_diffs" ("project_key");

CREATE INDEX "idx_schedule_version_identity_matches_project" ON "schedule"."schedule_version_identity_matches" ("project_key");

CREATE INDEX "idx_schedule_version_identity_matches_import" ON "schedule"."schedule_version_identity_matches" ("import_id");

CREATE INDEX "idx_schedule_version_identity_matches_version" ON "schedule"."schedule_version_identity_matches" ("schedule_version_key");

CREATE INDEX "idx_schedule_version_identity_matches_identity" ON "schedule"."schedule_version_identity_matches" ("schedule_identity_key");

CREATE INDEX "ix_agent_model_receipts_run" ON "core"."second_brain_agent_model_receipts" ("agent_run_id", "created_utc");

CREATE INDEX "ix_agent_run_receipts_agent" ON "core"."second_brain_agent_run_receipts" ("agent_id", "created_utc");

CREATE INDEX "ix_second_brain_evaluation_runs_target" ON "core"."second_brain_evaluation_runs" ("target_kind", "target_id");

CREATE UNIQUE INDEX "second_brain_financial_fact_normalization_runs_uq1" ON "financial"."second_brain_financial_fact_normalization_runs" ("run_id");

CREATE UNIQUE INDEX "second_brain_financial_forecast_readiness_runs_uq1" ON "financial"."second_brain_financial_forecast_readiness_runs" ("run_id");

CREATE UNIQUE INDEX "second_brain_financial_readiness_agent_runs_uq1" ON "financial"."second_brain_financial_readiness_agent_runs" ("run_id");

CREATE INDEX "ix_second_brain_research_packets_project" ON "core"."second_brain_research_packets" ("project_key", "status", "review_tier");

CREATE INDEX "ix_second_brain_retrieval_vector_index_items_run_id" ON "core"."second_brain_retrieval_vector_index_items" ("run_id");

CREATE INDEX "ix_second_brain_retrieval_vector_index_runs_project_key" ON "core"."second_brain_retrieval_vector_index_runs" ("project_key");

CREATE INDEX "ix_source_evidence_trails_project" ON "core"."source_evidence_trails" ("project_key", "confidence_class", "review_required");

CREATE INDEX "idx_source_index_bootstrap_runs_status" ON "core"."source_index_bootstrap_runs" ("status", "heartbeat_at");

CREATE INDEX "idx_source_index_bootstrap_runs_root" ON "core"."source_index_bootstrap_runs" ("root_key", "created_at");

CREATE UNIQUE INDEX "idx_source_index_bootstrap_runs_active" ON "core"."source_index_bootstrap_runs" ("root_key")
    WHERE "status"='running';

CREATE INDEX "idx_source_index_bootstrap_state_ready" ON "core"."source_index_bootstrap_state" ("watcher_ready");

CREATE INDEX "idx_locators_source_id" ON "core"."source_index_locators" ("source_id");

CREATE UNIQUE INDEX "idx_locators_active_path" ON "core"."source_index_locators" ("source_root_key", "rel_path")
    WHERE "is_current_locator"=1 AND "tombstoned_at" IS NULL;

CREATE UNIQUE INDEX "idx_locators_current_per_entity" ON "core"."source_index_locators" ("source_entity_id")
    WHERE "is_current_locator"=1;

CREATE INDEX "idx_source_index_reconciliation_runs_root" ON "core"."source_index_reconciliation_runs" ("root_key", "created_at");

CREATE INDEX "idx_source_index_scan_generations_status" ON "core"."source_index_scan_generations" ("status", "updated_at");

CREATE INDEX "idx_source_index_scan_generations_root" ON "core"."source_index_scan_generations" ("root_key", "started_at");

CREATE UNIQUE INDEX "idx_source_index_scan_generations_active" ON "core"."source_index_scan_generations" ("root_key")
    WHERE "status" IN ('running','partial','reconcile_pending');

CREATE INDEX "idx_si_scan_quarantine_entity" ON "core"."source_index_scan_quarantine" ("source_entity_id");

CREATE INDEX "idx_source_index_scan_quarantine_root_state" ON "core"."source_index_scan_quarantine" ("source_root_key", "resolution_state");

CREATE UNIQUE INDEX "idx_source_index_scan_quarantine_active" ON "core"."source_index_scan_quarantine" ("source_root_key", "rel_path")
    WHERE "resolution_state" = 'unresolved';

CREATE INDEX "idx_si_chunks_source" ON "core"."source_intelligence_chunks" ("source_entity_id");

CREATE UNIQUE INDEX "source_intelligence_chunks_uq2" ON "core"."source_intelligence_chunks" ("source_entity_id", "ordinal");

CREATE INDEX "idx_si_events_entity" ON "core"."source_intelligence_events" ("source_entity_id");

CREATE INDEX "idx_si_events_source" ON "core"."source_intelligence_events" ("source_id");

CREATE INDEX "idx_si_events_status" ON "core"."source_intelligence_events" ("status", "created_at");

CREATE INDEX "idx_si_gennotes_status" ON "core"."source_intelligence_generated_notes" ("generation_status");

CREATE INDEX "idx_si_gennotes_source" ON "core"."source_intelligence_generated_notes" ("source_entity_id");

CREATE UNIQUE INDEX "source_intelligence_generated_notes_uq2" ON "core"."source_intelligence_generated_notes" ("source_entity_id", "note_rel_path");

CREATE INDEX "idx_si_metadata_fts_rowid" ON "core"."source_intelligence_metadata" ("fts_rowid");

CREATE INDEX "idx_si_metadata_sha" ON "core"."source_intelligence_metadata" ("content_sha256");

CREATE INDEX "idx_si_rel_dst" ON "core"."source_intelligence_relationships" ("dst_kind", "dst_ref");

CREATE INDEX "idx_si_rel_src" ON "core"."source_intelligence_relationships" ("src_source_entity_id");

CREATE UNIQUE INDEX "source_intelligence_relationships_uq2" ON "core"."source_intelligence_relationships" ("src_source_entity_id", "dst_kind", "dst_ref", "relation");

CREATE INDEX "idx_si_sources_renamed_from" ON "core"."source_intelligence_sources" ("renamed_from_source_id")
    WHERE "renamed_from_source_id" IS NOT NULL;

CREATE INDEX "idx_si_sources_root" ON "core"."source_intelligence_sources" ("source_root_key");

CREATE INDEX "idx_si_sources_active" ON "core"."source_intelligence_sources" ("active", "deleted");

CREATE INDEX "idx_si_sources_project" ON "core"."source_intelligence_sources" ("project_key");

CREATE UNIQUE INDEX "idx_si_sources_domain" ON "core"."source_intelligence_sources" ("domain_ref_table", "domain_ref_id")
    WHERE "domain_ref_id" IS NOT NULL;

CREATE INDEX "idx_si_summaries_source" ON "core"."source_intelligence_summaries" ("source_entity_id");

CREATE INDEX "ix_source_record_summary_project_system" ON "core"."source_record_summary_mart" ("project_key", "source_system");

CREATE UNIQUE INDEX "source_records_uq1" ON "core"."source_records" ("source_type", "source_key");

CREATE INDEX "idx_source_structure_entities_project" ON "core"."source_structure_entities" ("project_number");

CREATE UNIQUE INDEX "source_structure_entities_uq2" ON "core"."source_structure_entities" ("entity_type", "canonical_key");

CREATE INDEX "idx_source_structure_entity_folders_folder" ON "core"."source_structure_entity_folders" ("folder_id");

CREATE INDEX "idx_source_structure_folders_flags" ON "core"."source_structure_folders" ("is_noise", "is_backup_mirror", "is_generated_output");

CREATE INDEX "idx_source_structure_folders_rank" ON "core"."source_structure_folders" ("root_key", "search_rank");

CREATE INDEX "idx_source_structure_folders_project" ON "core"."source_structure_folders" ("project_number");

CREATE INDEX "idx_source_structure_folders_doc_family" ON "core"."source_structure_folders" ("doc_family");

CREATE INDEX "idx_source_structure_folders_class" ON "core"."source_structure_folders" ("folder_class");

CREATE INDEX "idx_source_structure_folders_parent" ON "core"."source_structure_folders" ("parent_folder_id");

CREATE INDEX "idx_source_structure_folders_root_depth" ON "core"."source_structure_folders" ("root_key", "depth");

CREATE UNIQUE INDEX "source_structure_folders_uq2" ON "core"."source_structure_folders" ("root_key", "rel_path");

CREATE INDEX "idx_source_structure_overrides_active" ON "core"."source_structure_overrides" ("active", "target_type", "root_key");

CREATE UNIQUE INDEX "source_structure_overrides_uq2" ON "core"."source_structure_overrides" ("target_type", "root_key", "rel_path");

CREATE INDEX "idx_source_structure_roots_rank" ON "core"."source_structure_roots" ("default_search_rank", "root_class");

CREATE INDEX "ix_source_record_map_type_status" ON "core"."source_system_record_map" ("record_type", "record_status");

CREATE INDEX "ix_source_record_map_source_key" ON "core"."source_system_record_map" ("source_system", "source_table", "source_primary_key");

CREATE INDEX "ix_source_record_map_project_system" ON "core"."source_system_record_map" ("project_key", "source_system");

CREATE UNIQUE INDEX "source_system_record_map_uq2" ON "core"."source_system_record_map" ("source_system", "source_table", "source_primary_key");

CREATE INDEX "idx_staffing_holiday_calendar_dates_calendar_year" ON "financial"."staffing_holiday_calendar_dates" ("holiday_calendar_id", "calendar_year");

CREATE UNIQUE INDEX "staffing_holiday_calendar_dates_uq2" ON "financial"."staffing_holiday_calendar_dates" ("holiday_calendar_id", "calendar_year", "holiday_key");

CREATE UNIQUE INDEX "staffing_holiday_calendars_uq2" ON "financial"."staffing_holiday_calendars" ("calendar_key");

CREATE UNIQUE INDEX "sync_state_uq1" ON "core"."sync_state" ("source_name");

CREATE INDEX "ix_task_candidates_snoozed_until" ON "core"."task_candidates" ("snoozed_until_utc");

CREATE INDEX "ix_task_candidates_review_status" ON "core"."task_candidates" ("review_status");

CREATE UNIQUE INDEX "task_candidates_uq2" ON "core"."task_candidates" ("stable_key");
