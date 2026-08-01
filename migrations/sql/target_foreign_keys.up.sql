ALTER TABLE "core"."accepted_commitments"
    ADD CONSTRAINT "accepted_commitments_fk0" FOREIGN KEY ("candidate_id")
    REFERENCES "core"."commitment_candidates" ("candidate_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."accepted_tasks"
    ADD CONSTRAINT "accepted_tasks_fk0" FOREIGN KEY ("candidate_id")
    REFERENCES "core"."task_candidates" ("candidate_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."ai_job_runs"
    ADD CONSTRAINT "ai_job_runs_fk0" FOREIGN KEY ("job_id")
    REFERENCES "core"."ai_job_queue" ("job_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."attachments"
    ADD CONSTRAINT "attachments_fk0" FOREIGN KEY ("parent_source_record_id")
    REFERENCES "core"."source_records" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."attachments"
    ADD CONSTRAINT "attachments_fk1" FOREIGN KEY ("source_record_id")
    REFERENCES "core"."source_records" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "calendar"."calendar_crawl_runs"
    ADD CONSTRAINT "calendar_crawl_runs_fk0" FOREIGN KEY ("source_id")
    REFERENCES "calendar"."calendar_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "calendar"."calendar_event_attendees"
    ADD CONSTRAINT "calendar_event_attendees_fk0" FOREIGN KEY ("event_index_id")
    REFERENCES "calendar"."calendar_event_index" ("event_index_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "calendar"."calendar_event_index"
    ADD CONSTRAINT "calendar_event_index_fk0" FOREIGN KEY ("source_id")
    REFERENCES "calendar"."calendar_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "calendar"."calendar_project_match_candidates"
    ADD CONSTRAINT "calendar_project_match_candidates_fk0" FOREIGN KEY ("event_index_id")
    REFERENCES "calendar"."calendar_event_index" ("event_index_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "calendar"."calendar_sync_state"
    ADD CONSTRAINT "calendar_sync_state_fk0" FOREIGN KEY ("source_id")
    REFERENCES "calendar"."calendar_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."claude_context_packet_items"
    ADD CONSTRAINT "claude_context_packet_items_fk0" FOREIGN KEY ("packet_id")
    REFERENCES "core"."claude_context_packets" ("packet_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_document_classification_candidates"
    ADD CONSTRAINT "construction_document_classification_candidates_fk0" FOREIGN KEY ("document_card_id")
    REFERENCES "construction"."construction_document_cards" ("document_card_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_document_intelligence_previews"
    ADD CONSTRAINT "construction_document_intelligence_previews_fk0" FOREIGN KEY ("document_card_id")
    REFERENCES "construction"."construction_document_cards" ("document_card_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_document_project_match_candidates"
    ADD CONSTRAINT "construction_document_project_match_candidates_fk0" FOREIGN KEY ("document_card_id")
    REFERENCES "construction"."construction_document_cards" ("document_card_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_document_relationship_candidates"
    ADD CONSTRAINT "construction_document_relationship_candidates_fk0" FOREIGN KEY ("document_card_id")
    REFERENCES "construction"."construction_document_cards" ("document_card_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_drive_items"
    ADD CONSTRAINT "construction_drive_items_fk0" FOREIGN KEY ("source_id")
    REFERENCES "construction"."construction_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_project_keyword_registry"
    ADD CONSTRAINT "construction_project_keyword_registry_fk0" FOREIGN KEY ("project_key")
    REFERENCES "construction"."construction_project_identity" ("project_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_project_source_matches"
    ADD CONSTRAINT "construction_project_source_matches_fk0" FOREIGN KEY ("source_id")
    REFERENCES "construction"."construction_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_project_source_matches"
    ADD CONSTRAINT "construction_project_source_matches_fk1" FOREIGN KEY ("project_key")
    REFERENCES "construction"."construction_project_identity" ("project_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_source_crawl_runs"
    ADD CONSTRAINT "construction_source_crawl_runs_fk0" FOREIGN KEY ("source_id")
    REFERENCES "construction"."construction_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "construction"."construction_source_sync_state"
    ADD CONSTRAINT "construction_source_sync_state_fk0" FOREIGN KEY ("source_id")
    REFERENCES "construction"."construction_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."content_embeddings"
    ADD CONSTRAINT "content_embeddings_fk0" FOREIGN KEY ("source_record_id")
    REFERENCES "core"."source_records" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."cross_source_relationships"
    ADD CONSTRAINT "cross_source_relationships_fk0" FOREIGN KEY ("candidate_id")
    REFERENCES "core"."cross_source_relationship_candidates" ("candidate_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."daily_brief_delivery_receipts"
    ADD CONSTRAINT "daily_brief_delivery_receipts_fk0" FOREIGN KEY ("brief_run_id")
    REFERENCES "core"."daily_brief_runs" ("brief_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."daily_brief_handoff_lines"
    ADD CONSTRAINT "daily_brief_handoff_lines_fk0" FOREIGN KEY ("brief_run_id")
    REFERENCES "core"."daily_brief_runs" ("brief_run_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."daily_brief_html_render_receipts"
    ADD CONSTRAINT "daily_brief_html_render_receipts_fk0" FOREIGN KEY ("brief_run_id")
    REFERENCES "core"."daily_brief_runs" ("brief_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."daily_brief_notification_receipts"
    ADD CONSTRAINT "daily_brief_notification_receipts_fk0" FOREIGN KEY ("brief_run_id")
    REFERENCES "core"."daily_brief_runs" ("brief_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."daily_brief_open_receipts"
    ADD CONSTRAINT "daily_brief_open_receipts_fk0" FOREIGN KEY ("brief_run_id")
    REFERENCES "core"."daily_brief_runs" ("brief_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."daily_brief_source_refs"
    ADD CONSTRAINT "daily_brief_source_refs_fk0" FOREIGN KEY ("brief_run_id")
    REFERENCES "core"."daily_brief_runs" ("brief_run_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_crawl_runs"
    ADD CONSTRAINT "email_crawl_runs_fk0" FOREIGN KEY ("source_id")
    REFERENCES "email"."email_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_message_attachments"
    ADD CONSTRAINT "email_message_attachments_fk0" FOREIGN KEY ("message_id")
    REFERENCES "email"."email_messages" ("message_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_message_body_vault_refs"
    ADD CONSTRAINT "email_message_body_vault_refs_fk0" FOREIGN KEY ("message_id")
    REFERENCES "email"."email_messages" ("message_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_message_recipients"
    ADD CONSTRAINT "email_message_recipients_fk0" FOREIGN KEY ("message_id")
    REFERENCES "email"."email_messages" ("message_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_messages"
    ADD CONSTRAINT "email_messages_fk0" FOREIGN KEY ("source_id")
    REFERENCES "email"."email_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_model_classifications"
    ADD CONSTRAINT "email_model_classifications_fk0" FOREIGN KEY ("message_id")
    REFERENCES "email"."email_messages" ("message_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_project_matches"
    ADD CONSTRAINT "email_project_matches_fk0" FOREIGN KEY ("message_id")
    REFERENCES "email"."email_messages" ("message_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_relationship_candidates"
    ADD CONSTRAINT "email_relationship_candidates_fk0" FOREIGN KEY ("message_id")
    REFERENCES "email"."email_messages" ("message_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_review_queue"
    ADD CONSTRAINT "email_review_queue_fk0" FOREIGN KEY ("message_id")
    REFERENCES "email"."email_messages" ("message_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "email"."email_sync_state"
    ADD CONSTRAINT "email_sync_state_fk0" FOREIGN KEY ("source_id")
    REFERENCES "email"."email_source_locations" ("source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."files"
    ADD CONSTRAINT "files_fk0" FOREIGN KEY ("source_record_id")
    REFERENCES "core"."source_records" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."follow_up_status_events"
    ADD CONSTRAINT "follow_up_status_events_fk0" FOREIGN KEY ("watch_item_id")
    REFERENCES "core"."follow_up_watch_items" ("watch_item_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_accuracy_results"
    ADD CONSTRAINT "forecast_accuracy_results_fk0" FOREIGN KEY ("external_forecast_id")
    REFERENCES "financial"."forecast_external_forecasts" ("external_forecast_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_anomaly_findings"
    ADD CONSTRAINT "forecast_anomaly_findings_fk0" FOREIGN KEY ("external_forecast_id")
    REFERENCES "financial"."forecast_external_forecasts" ("external_forecast_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_calibration_weights"
    ADD CONSTRAINT "forecast_calibration_weights_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_comparison_results"
    ADD CONSTRAINT "forecast_comparison_results_fk0" FOREIGN KEY ("external_forecast_id")
    REFERENCES "financial"."forecast_external_forecasts" ("external_forecast_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_confidence_factors"
    ADD CONSTRAINT "forecast_confidence_factors_fk0" FOREIGN KEY ("scorecard_id")
    REFERENCES "financial"."forecast_confidence_scorecards" ("scorecard_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_confidence_scorecards"
    ADD CONSTRAINT "forecast_confidence_scorecards_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_confidence_scorecards"
    ADD CONSTRAINT "forecast_confidence_scorecards_fk1" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_config_items"
    ADD CONSTRAINT "forecast_config_items_fk0" FOREIGN KEY ("config_source_id")
    REFERENCES "financial"."forecast_config_sources" ("config_source_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_config_snapshot_items"
    ADD CONSTRAINT "forecast_config_snapshot_items_fk0" FOREIGN KEY ("config_item_id")
    REFERENCES "financial"."forecast_config_items" ("config_item_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_config_snapshot_items"
    ADD CONSTRAINT "forecast_config_snapshot_items_fk1" FOREIGN KEY ("config_snapshot_id")
    REFERENCES "financial"."forecast_config_snapshots" ("config_snapshot_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_data_availability_profiles"
    ADD CONSTRAINT "forecast_data_availability_profiles_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_evidence_packages"
    ADD CONSTRAINT "forecast_evidence_packages_fk0" FOREIGN KEY ("external_forecast_id")
    REFERENCES "financial"."forecast_external_forecasts" ("external_forecast_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_external_forecast_mappings"
    ADD CONSTRAINT "forecast_external_forecast_mappings_fk0" FOREIGN KEY ("external_forecast_id")
    REFERENCES "financial"."forecast_external_forecasts" ("external_forecast_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_external_forecast_rows"
    ADD CONSTRAINT "forecast_external_forecast_rows_fk0" FOREIGN KEY ("external_forecast_id")
    REFERENCES "financial"."forecast_external_forecasts" ("external_forecast_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_method_eligibility"
    ADD CONSTRAINT "forecast_method_eligibility_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_model_selection_decisions"
    ADD CONSTRAINT "forecast_model_selection_decisions_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_operator_assumptions"
    ADD CONSTRAINT "forecast_operator_assumptions_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_budget_codes"
    ADD CONSTRAINT "forecast_output_budget_codes_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_changes"
    ADD CONSTRAINT "forecast_output_changes_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_commitment_exposure"
    ADD CONSTRAINT "forecast_output_commitment_exposure_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_monthly"
    ADD CONSTRAINT "forecast_output_monthly_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_monthly_table_rows"
    ADD CONSTRAINT "forecast_output_monthly_table_rows_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_monthly_table_totals"
    ADD CONSTRAINT "forecast_output_monthly_table_totals_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_narratives"
    ADD CONSTRAINT "forecast_output_narratives_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_probability"
    ADD CONSTRAINT "forecast_output_probability_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_risks"
    ADD CONSTRAINT "forecast_output_risks_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_schedule_phasing"
    ADD CONSTRAINT "forecast_output_schedule_phasing_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_output_staffing"
    ADD CONSTRAINT "forecast_output_staffing_fk0" FOREIGN KEY ("output_id")
    REFERENCES "financial"."forecast_outputs" ("output_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_outputs"
    ADD CONSTRAINT "forecast_outputs_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_project_maturity_snapshots"
    ADD CONSTRAINT "forecast_project_maturity_snapshots_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_project_staffing_absence_overrides"
    ADD CONSTRAINT "forecast_project_staffing_absence_overrides_fk0" FOREIGN KEY ("staffing_config_id")
    REFERENCES "financial"."forecast_project_staffing_config" ("staffing_config_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_project_staffing_assumptions"
    ADD CONSTRAINT "forecast_project_staffing_assumptions_fk0" FOREIGN KEY ("holiday_calendar_id")
    REFERENCES "financial"."staffing_holiday_calendars" ("holiday_calendar_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_project_staffing_attribution_rules"
    ADD CONSTRAINT "forecast_project_staffing_attribution_rules_fk0" FOREIGN KEY ("staffing_config_id")
    REFERENCES "financial"."forecast_project_staffing_config" ("staffing_config_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_project_staffing_snapshot_rows"
    ADD CONSTRAINT "forecast_project_staffing_snapshot_rows_fk0" FOREIGN KEY ("staffing_snapshot_id")
    REFERENCES "financial"."forecast_project_staffing_snapshots" ("staffing_snapshot_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_required_assumptions"
    ADD CONSTRAINT "forecast_required_assumptions_fk0" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_review_items"
    ADD CONSTRAINT "forecast_review_items_fk0" FOREIGN KEY ("external_forecast_id")
    REFERENCES "financial"."forecast_external_forecasts" ("external_forecast_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_run_model_versions"
    ADD CONSTRAINT "forecast_run_model_versions_fk0" FOREIGN KEY ("model_version_id")
    REFERENCES "financial"."forecast_model_versions" ("model_version_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_run_model_versions"
    ADD CONSTRAINT "forecast_run_model_versions_fk1" FOREIGN KEY ("run_id")
    REFERENCES "financial"."forecast_runs" ("run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."forecast_staffing_template_versions"
    ADD CONSTRAINT "forecast_staffing_template_versions_fk0" FOREIGN KEY ("template_id")
    REFERENCES "financial"."forecast_staffing_templates" ("template_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."interactive_chat_message_receipts"
    ADD CONSTRAINT "interactive_chat_message_receipts_fk0" FOREIGN KEY ("session_id")
    REFERENCES "core"."interactive_chat_sessions" ("session_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."long_term_memory_quality_signals"
    ADD CONSTRAINT "long_term_memory_quality_signals_fk0" FOREIGN KEY ("memory_id")
    REFERENCES "core"."long_term_memory_items" ("memory_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."long_term_memory_source_refs"
    ADD CONSTRAINT "long_term_memory_source_refs_fk0" FOREIGN KEY ("memory_id")
    REFERENCES "core"."long_term_memory_items" ("memory_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."meeting_email_relationship_candidates"
    ADD CONSTRAINT "meeting_email_relationship_candidates_fk0" FOREIGN KEY ("event_index_id")
    REFERENCES "calendar"."calendar_event_index" ("event_index_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."meeting_prep_brief_sections"
    ADD CONSTRAINT "meeting_prep_brief_sections_fk0" FOREIGN KEY ("brief_run_id")
    REFERENCES "core"."meeting_prep_brief_runs" ("brief_run_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."memory_update_reviews"
    ADD CONSTRAINT "memory_update_reviews_fk0" FOREIGN KEY ("candidate_id")
    REFERENCES "core"."memory_update_candidates" ("candidate_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."obsidian_index_entries"
    ADD CONSTRAINT "obsidian_index_entries_fk0" FOREIGN KEY ("manifest_id")
    REFERENCES "core"."obsidian_index_manifests" ("manifest_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."obsidian_managed_section_registry"
    ADD CONSTRAINT "obsidian_managed_section_registry_fk0" FOREIGN KEY ("note_id")
    REFERENCES "core"."obsidian_note_index" ("note_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."obsidian_note_tag_index"
    ADD CONSTRAINT "obsidian_note_tag_index_fk0" FOREIGN KEY ("note_id")
    REFERENCES "core"."obsidian_note_index" ("note_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."parser_outputs"
    ADD CONSTRAINT "parser_outputs_fk0" FOREIGN KEY ("file_source_record_id")
    REFERENCES "core"."source_records" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_endpoint_capture_pages"
    ADD CONSTRAINT "procore_endpoint_capture_pages_fk0" FOREIGN KEY ("capture_run_id")
    REFERENCES "procore"."procore_endpoint_capture_runs" ("capture_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_billing_periods"
    ADD CONSTRAINT "procore_ep_billing_periods_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_budget_change_history"
    ADD CONSTRAINT "procore_ep_budget_change_history_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_budget_detail_columns"
    ADD CONSTRAINT "procore_ep_budget_detail_columns_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_budget_detail_row_cells"
    ADD CONSTRAINT "procore_ep_budget_detail_row_cells_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_budget_detail_row_cells"
    ADD CONSTRAINT "procore_ep_budget_detail_row_cells_fk1" FOREIGN KEY ("record_key")
    REFERENCES "procore"."procore_ep_budget_detail_rows" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_budget_detail_rows"
    ADD CONSTRAINT "procore_ep_budget_detail_rows_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_budget_modifications"
    ADD CONSTRAINT "procore_ep_budget_modifications_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_budget_views"
    ADD CONSTRAINT "procore_ep_budget_views_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events"
    ADD CONSTRAINT "procore_ep_change_events_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_attachments"
    ADD CONSTRAINT "procore_ep_change_events_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_attachments"
    ADD CONSTRAINT "procore_ep_change_events_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_change_events" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_change_items"
    ADD CONSTRAINT "procore_ep_change_events_change_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_change_items"
    ADD CONSTRAINT "procore_ep_change_events_change_items_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_change_events" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22"
    ADD CONSTRAINT "procore_ep_change_events_change_items_budget_code_seg_2_9ebf97c" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22"
    ADD CONSTRAINT "procore_ep_change_events_change_items_budget_code_seg_2_69e5270" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_change_events" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_markup_items"
    ADD CONSTRAINT "procore_ep_change_events_markup_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_markup_items"
    ADD CONSTRAINT "procore_ep_change_events_markup_items_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_change_events" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items"
    ADD CONSTRAINT "procore_ep_change_events_markup_items_wbs_code_segment__31f7e91" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items"
    ADD CONSTRAINT "procore_ep_change_events_markup_items_wbs_code_segment__ff5a597" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_change_events" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_attachments"
    ADD CONSTRAINT "procore_ep_commitment_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_change_orders"
    ADD CONSTRAINT "procore_ep_commitment_change_orders_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_compliance"
    ADD CONSTRAINT "procore_ep_commitment_compliance_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents"
    ADD CONSTRAINT "procore_ep_commitment_compliance_insurance_documents_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents"
    ADD CONSTRAINT "procore_ep_commitment_compliance_insurance_documents_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_commitment_compliance" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf"
    ADD CONSTRAINT "procore_ep_commitment_compliance_insurance_documents__5_41ce87c" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf"
    ADD CONSTRAINT "procore_ep_commitment_compliance_insurance_documents__5_75c8e3c" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_commitment_compliance" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_contracts"
    ADD CONSTRAINT "procore_ep_commitment_contracts_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_commitment_line_items"
    ADD CONSTRAINT "procore_ep_commitment_line_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_dcrs"
    ADD CONSTRAINT "procore_ep_daily_log_dcrs_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_dcrs_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_dcrs_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_dcrs_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_dcrs_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_daily_log_dcrs" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_deliveries"
    ADD CONSTRAINT "procore_ep_daily_log_deliveries_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_deliveries_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_deliveries_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_deliveries_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_deliveries_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_daily_log_deliveries" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_inspections"
    ADD CONSTRAINT "procore_ep_daily_log_inspections_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_inspections_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_inspections_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_inspections_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_inspections_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_daily_log_inspections" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_manpower"
    ADD CONSTRAINT "procore_ep_daily_log_manpower_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_manpower_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_manpower_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_manpower_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_manpower_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_daily_log_manpower" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_notes"
    ADD CONSTRAINT "procore_ep_daily_log_notes_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_notes_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_notes_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_notes_attachments"
    ADD CONSTRAINT "procore_ep_daily_log_notes_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_daily_log_notes" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_visitor"
    ADD CONSTRAINT "procore_ep_daily_log_visitor_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_daily_log_weather"
    ADD CONSTRAINT "procore_ep_daily_log_weather_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspection_items"
    ADD CONSTRAINT "procore_ep_inspection_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspection_items_response_set_responses"
    ADD CONSTRAINT "procore_ep_inspection_items_response_set_responses_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspection_items_response_set_responses"
    ADD CONSTRAINT "procore_ep_inspection_items_response_set_responses_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_inspection_items" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspection_sections"
    ADD CONSTRAINT "procore_ep_inspection_sections_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections"
    ADD CONSTRAINT "procore_ep_inspections_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_attachments"
    ADD CONSTRAINT "procore_ep_inspections_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_attachments"
    ADD CONSTRAINT "procore_ep_inspections_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_inspections" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_distribution_members"
    ADD CONSTRAINT "procore_ep_inspections_distribution_members_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_distribution_members"
    ADD CONSTRAINT "procore_ep_inspections_distribution_members_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_inspections" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_inspectors"
    ADD CONSTRAINT "procore_ep_inspections_inspectors_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_inspectors"
    ADD CONSTRAINT "procore_ep_inspections_inspectors_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_inspections" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_signature_requests"
    ADD CONSTRAINT "procore_ep_inspections_signature_requests_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_inspections_signature_requests"
    ADD CONSTRAINT "procore_ep_inspections_signature_requests_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_inspections" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_meetings"
    ADD CONSTRAINT "procore_ep_meetings_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_observations"
    ADD CONSTRAINT "procore_ep_observations_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_observations_assignees"
    ADD CONSTRAINT "procore_ep_observations_assignees_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_observations_assignees"
    ADD CONSTRAINT "procore_ep_observations_assignees_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_observations" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_prime_change_order_line_items"
    ADD CONSTRAINT "procore_ep_prime_change_order_line_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_prime_change_orders"
    ADD CONSTRAINT "procore_ep_prime_change_orders_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_prime_contract_line_items"
    ADD CONSTRAINT "procore_ep_prime_contract_line_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_prime_contracts"
    ADD CONSTRAINT "procore_ep_prime_contracts_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects"
    ADD CONSTRAINT "procore_ep_projects_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163287_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163287_value_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163287_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163287_value_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_projects" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163290_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163290_value_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163290_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163290_value_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_projects" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163293_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163293_value_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163293_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163293_value_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_projects" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163296_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163296_value_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163296_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163296_value_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_projects" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163299_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163299_value_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163299_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163299_value_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_projects" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163302_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163302_value_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163302_value"
    ADD CONSTRAINT "procore_ep_projects_custom_fields_custom_field_163302_value_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_projects" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_punch_items"
    ADD CONSTRAINT "procore_ep_punch_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_punch_items_assignees"
    ADD CONSTRAINT "procore_ep_punch_items_assignees_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_punch_items_assignees"
    ADD CONSTRAINT "procore_ep_punch_items_assignees_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_punch_items" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_punch_items_assignments"
    ADD CONSTRAINT "procore_ep_punch_items_assignments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_punch_items_assignments"
    ADD CONSTRAINT "procore_ep_punch_items_assignments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_punch_items" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_punch_items_ball_in_court"
    ADD CONSTRAINT "procore_ep_punch_items_ball_in_court_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_punch_items_ball_in_court"
    ADD CONSTRAINT "procore_ep_punch_items_ball_in_court_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_punch_items" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_purchase_order_contracts"
    ADD CONSTRAINT "procore_ep_purchase_order_contracts_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65"
    ADD CONSTRAINT "procore_ep_purchase_order_contracts_custom_fields_cus_a_0ac8f8d" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65"
    ADD CONSTRAINT "procore_ep_purchase_order_contracts_custom_fields_cus_a_704520b" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_purchase_order_contracts" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_purchase_order_line_items"
    ADD CONSTRAINT "procore_ep_purchase_order_line_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd"
    ADD CONSTRAINT "procore_ep_purchase_order_line_items_cost_code_line_i_7_41f7610" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd"
    ADD CONSTRAINT "procore_ep_purchase_order_line_items_cost_code_line_i_7_3f92a3e" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_purchase_order_line_items" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfis"
    ADD CONSTRAINT "procore_ep_rfis_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfis_assignees"
    ADD CONSTRAINT "procore_ep_rfis_assignees_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfis_assignees"
    ADD CONSTRAINT "procore_ep_rfis_assignees_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_rfis" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfis_ball_in_courts"
    ADD CONSTRAINT "procore_ep_rfis_ball_in_courts_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfis_ball_in_courts"
    ADD CONSTRAINT "procore_ep_rfis_ball_in_courts_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_rfis" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfis_questions"
    ADD CONSTRAINT "procore_ep_rfis_questions_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfis_questions"
    ADD CONSTRAINT "procore_ep_rfis_questions_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_rfis" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs"
    ADD CONSTRAINT "procore_ep_rfqs_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_attachments"
    ADD CONSTRAINT "procore_ep_rfqs_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_attachments"
    ADD CONSTRAINT "procore_ep_rfqs_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_rfqs" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_change_event_attachments"
    ADD CONSTRAINT "procore_ep_rfqs_change_event_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_change_event_attachments"
    ADD CONSTRAINT "procore_ep_rfqs_change_event_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_rfqs" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items"
    ADD CONSTRAINT "procore_ep_rfqs_change_event_change_event_line_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items"
    ADD CONSTRAINT "procore_ep_rfqs_change_event_change_event_line_items_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_rfqs" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d"
    ADD CONSTRAINT "procore_ep_rfqs_change_event_change_event_line_items__0_cf38b3d" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d"
    ADD CONSTRAINT "procore_ep_rfqs_change_event_change_event_line_items__0_fceb630" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_rfqs" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_schedule_activities"
    ADD CONSTRAINT "procore_ep_schedule_activities_fk0" FOREIGN KEY ("import_id")
    REFERENCES "schedule"."schedule_file_imports" ("import_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_schedule_activity_code_assignments"
    ADD CONSTRAINT "procore_ep_schedule_activity_code_assignments_fk0" FOREIGN KEY ("import_id")
    REFERENCES "schedule"."schedule_file_imports" ("import_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_schedule_calendars"
    ADD CONSTRAINT "procore_ep_schedule_calendars_fk0" FOREIGN KEY ("import_id")
    REFERENCES "schedule"."schedule_file_imports" ("import_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_schedule_relationships"
    ADD CONSTRAINT "procore_ep_schedule_relationships_fk0" FOREIGN KEY ("import_id")
    REFERENCES "schedule"."schedule_file_imports" ("import_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_schedule_udf_values"
    ADD CONSTRAINT "procore_ep_schedule_udf_values_fk0" FOREIGN KEY ("import_id")
    REFERENCES "schedule"."schedule_file_imports" ("import_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_schedule_wbs_nodes"
    ADD CONSTRAINT "procore_ep_schedule_wbs_nodes_fk0" FOREIGN KEY ("import_id")
    REFERENCES "schedule"."schedule_file_imports" ("import_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_schedules"
    ADD CONSTRAINT "procore_ep_schedules_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_subcontractor_invoice_change_order_items"
    ADD CONSTRAINT "procore_ep_subcontractor_invoice_change_order_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_subcontractor_invoice_contract_detail_items"
    ADD CONSTRAINT "procore_ep_subcontractor_invoice_contract_detail_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_subcontractor_invoices"
    ADD CONSTRAINT "procore_ep_subcontractor_invoices_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_subcontractor_invoices_attachments"
    ADD CONSTRAINT "procore_ep_subcontractor_invoices_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_subcontractor_invoices_attachments"
    ADD CONSTRAINT "procore_ep_subcontractor_invoices_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_subcontractor_invoices" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_submittals"
    ADD CONSTRAINT "procore_ep_submittals_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_submittals_approvers"
    ADD CONSTRAINT "procore_ep_submittals_approvers_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_submittals_approvers"
    ADD CONSTRAINT "procore_ep_submittals_approvers_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_submittals" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_submittals_approvers_attachments"
    ADD CONSTRAINT "procore_ep_submittals_approvers_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_submittals_approvers_attachments"
    ADD CONSTRAINT "procore_ep_submittals_approvers_attachments_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_submittals" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_submittals_ball_in_court"
    ADD CONSTRAINT "procore_ep_submittals_ball_in_court_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_ep_submittals_ball_in_court"
    ADD CONSTRAINT "procore_ep_submittals_ball_in_court_fk1" FOREIGN KEY ("primary_record_key")
    REFERENCES "procore"."procore_ep_submittals" ("record_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_live_records"
    ADD CONSTRAINT "procore_live_records_fk0" FOREIGN KEY ("last_sync_run_id")
    REFERENCES "procore"."procore_live_sync_runs" ("sync_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_attachments"
    ADD CONSTRAINT "procore_raw_attachments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_budget_changes"
    ADD CONSTRAINT "procore_raw_budget_changes_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_budget_columns"
    ADD CONSTRAINT "procore_raw_budget_columns_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_budget_rows"
    ADD CONSTRAINT "procore_raw_budget_rows_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_change_event_comments"
    ADD CONSTRAINT "procore_raw_change_event_comments_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_change_order_line_items"
    ADD CONSTRAINT "procore_raw_change_order_line_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_change_orders"
    ADD CONSTRAINT "procore_raw_change_orders_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_contract_line_items"
    ADD CONSTRAINT "procore_raw_contract_line_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_contracts"
    ADD CONSTRAINT "procore_raw_contracts_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_cost_code_dimensions"
    ADD CONSTRAINT "procore_raw_cost_code_dimensions_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_daily_logs"
    ADD CONSTRAINT "procore_raw_daily_logs_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_date_dimensions"
    ADD CONSTRAINT "procore_raw_date_dimensions_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_invoice_items"
    ADD CONSTRAINT "procore_raw_invoice_items_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_invoices"
    ADD CONSTRAINT "procore_raw_invoices_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_meeting_details"
    ADD CONSTRAINT "procore_raw_meeting_details_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_meeting_topics"
    ADD CONSTRAINT "procore_raw_meeting_topics_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_project_dimensions"
    ADD CONSTRAINT "procore_raw_project_dimensions_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_rfi_responses"
    ADD CONSTRAINT "procore_raw_rfi_responses_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_rfq_responses"
    ADD CONSTRAINT "procore_raw_rfq_responses_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_status_dimensions"
    ADD CONSTRAINT "procore_raw_status_dimensions_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "procore"."procore_raw_submittal_packages"
    ADD CONSTRAINT "procore_raw_submittal_packages_fk0" FOREIGN KEY ("raw_payload_id")
    REFERENCES "procore"."procore_endpoint_raw_payloads" ("raw_payload_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."retrieval_context_refs"
    ADD CONSTRAINT "retrieval_context_refs_fk0" FOREIGN KEY ("retrieval_receipt_id")
    REFERENCES "core"."retrieval_query_receipts" ("retrieval_receipt_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_baseline_activities"
    ADD CONSTRAINT "schedule_baseline_activities_fk0" FOREIGN KEY ("baseline_project_key")
    REFERENCES "schedule"."schedule_baseline_projects" ("baseline_project_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cost_distributions"
    ADD CONSTRAINT "schedule_cost_distributions_fk0" FOREIGN KEY ("mapping_run_id")
    REFERENCES "schedule"."schedule_cost_mapping_runs" ("mapping_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cost_mapping_candidates"
    ADD CONSTRAINT "schedule_cost_mapping_candidates_fk0" FOREIGN KEY ("mapping_run_id")
    REFERENCES "schedule"."schedule_cost_mapping_runs" ("mapping_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cost_weighting_results"
    ADD CONSTRAINT "schedule_cost_weighting_results_fk0" FOREIGN KEY ("mapping_run_id")
    REFERENCES "schedule"."schedule_cost_mapping_runs" ("mapping_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cpm_activity_results"
    ADD CONSTRAINT "schedule_cpm_activity_results_fk0" FOREIGN KEY ("cpm_run_id")
    REFERENCES "schedule"."schedule_cpm_runs" ("cpm_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cpm_diagnostics"
    ADD CONSTRAINT "schedule_cpm_diagnostics_fk0" FOREIGN KEY ("cpm_run_id")
    REFERENCES "schedule"."schedule_cpm_runs" ("cpm_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cpm_path_activities"
    ADD CONSTRAINT "schedule_cpm_path_activities_fk0" FOREIGN KEY ("cpm_run_id")
    REFERENCES "schedule"."schedule_cpm_runs" ("cpm_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cpm_path_activities"
    ADD CONSTRAINT "schedule_cpm_path_activities_fk1" FOREIGN KEY ("path_id")
    REFERENCES "schedule"."schedule_cpm_paths" ("path_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cpm_paths"
    ADD CONSTRAINT "schedule_cpm_paths_fk0" FOREIGN KEY ("cpm_run_id")
    REFERENCES "schedule"."schedule_cpm_runs" ("cpm_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_cpm_relationship_results"
    ADD CONSTRAINT "schedule_cpm_relationship_results_fk0" FOREIGN KEY ("cpm_run_id")
    REFERENCES "schedule"."schedule_cpm_runs" ("cpm_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_import_package_files"
    ADD CONSTRAINT "schedule_import_package_files_fk0" FOREIGN KEY ("package_id")
    REFERENCES "schedule"."schedule_import_packages" ("package_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_quality_metric_results"
    ADD CONSTRAINT "schedule_quality_metric_results_fk0" FOREIGN KEY ("evaluation_run_id")
    REFERENCES "schedule"."schedule_quality_evaluation_runs" ("evaluation_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_quality_scorecards"
    ADD CONSTRAINT "schedule_quality_scorecards_fk0" FOREIGN KEY ("evaluation_run_id")
    REFERENCES "schedule"."schedule_quality_evaluation_runs" ("evaluation_run_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "schedule"."schedule_version_identity_matches"
    ADD CONSTRAINT "schedule_version_identity_matches_fk0" FOREIGN KEY ("schedule_identity_key")
    REFERENCES "schedule"."schedule_identities" ("schedule_identity_key")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."second_brain_agent_model_receipts"
    ADD CONSTRAINT "second_brain_agent_model_receipts_fk0" FOREIGN KEY ("agent_run_id")
    REFERENCES "core"."second_brain_agent_run_receipts" ("agent_run_id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_index_locators"
    ADD CONSTRAINT "source_index_locators_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_index_scan_quarantine"
    ADD CONSTRAINT "source_index_scan_quarantine_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_chunks"
    ADD CONSTRAINT "source_intelligence_chunks_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_events"
    ADD CONSTRAINT "source_intelligence_events_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_generated_notes"
    ADD CONSTRAINT "source_intelligence_generated_notes_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_metadata"
    ADD CONSTRAINT "source_intelligence_metadata_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_relationships"
    ADD CONSTRAINT "source_intelligence_relationships_fk0" FOREIGN KEY ("src_source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_sources"
    ADD CONSTRAINT "source_intelligence_sources_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_summaries"
    ADD CONSTRAINT "source_intelligence_summaries_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_intelligence_text"
    ADD CONSTRAINT "source_intelligence_text_fk0" FOREIGN KEY ("source_entity_id")
    REFERENCES "core"."source_index_entities" ("source_entity_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_links"
    ADD CONSTRAINT "source_links_fk0" FOREIGN KEY ("action_item_id")
    REFERENCES "core"."action_items" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_links"
    ADD CONSTRAINT "source_links_fk1" FOREIGN KEY ("to_source_record_id")
    REFERENCES "core"."source_records" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "core"."source_links"
    ADD CONSTRAINT "source_links_fk2" FOREIGN KEY ("from_source_record_id")
    REFERENCES "core"."source_records" ("id")
    ON DELETE CASCADE ON UPDATE NO ACTION
    NOT VALID;

ALTER TABLE "financial"."staffing_holiday_calendar_dates"
    ADD CONSTRAINT "staffing_holiday_calendar_dates_fk0" FOREIGN KEY ("holiday_calendar_id")
    REFERENCES "financial"."staffing_holiday_calendars" ("holiday_calendar_id")
    ON DELETE NO ACTION ON UPDATE NO ACTION
    NOT VALID;
