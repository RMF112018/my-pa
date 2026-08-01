DROP TABLE IF EXISTS "core"."task_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."sync_state" CASCADE;

DROP TABLE IF EXISTS "financial"."staffing_holiday_calendars" CASCADE;

DROP TABLE IF EXISTS "financial"."staffing_holiday_calendar_dates" CASCADE;

DROP TABLE IF EXISTS "core"."source_system_record_map" CASCADE;

DROP TABLE IF EXISTS "core"."source_structure_roots" CASCADE;

DROP TABLE IF EXISTS "core"."source_structure_overrides" CASCADE;

DROP TABLE IF EXISTS "core"."source_structure_folders" CASCADE;

DROP TABLE IF EXISTS "core"."source_structure_entity_folders" CASCADE;

DROP TABLE IF EXISTS "core"."source_structure_entities" CASCADE;

DROP TABLE IF EXISTS "core"."source_records" CASCADE;

DROP TABLE IF EXISTS "core"."source_record_summary_mart" CASCADE;

DROP TABLE IF EXISTS "core"."source_links" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_text" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_summaries" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_state" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_sources" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_relationships" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_metadata" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_generated_notes" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_events" CASCADE;

DROP TABLE IF EXISTS "core"."source_intelligence_chunks" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_scan_quarantine" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_scan_generations" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_reconciliation_runs" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_move_signals" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_locators" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_entities" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_bootstrap_state" CASCADE;

DROP TABLE IF EXISTS "core"."source_index_bootstrap_runs" CASCADE;

DROP TABLE IF EXISTS "core"."source_evidence_trails" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_runtime_config_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_retrieval_vector_index_runs" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_retrieval_vector_index_items" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_retrieval_approved_source_manifests" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_research_packets" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_mcp_tool_registry_snapshots" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_mcp_tool_call_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_mcp_server_config_snapshots" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_mcp_resource_registry_snapshots" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_mcp_prompt_registry_snapshots" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_mcp_permission_audit_runs" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_mcp_claude_desktop_config_previews" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_wbs_cost_code_snapshots" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_source_coverage_snapshots" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_review_required_items" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_readiness_agent_runs" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_forecast_readiness_runs" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_fact_normalization_runs" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_exposure_summary_items" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_currency_completeness_snapshots" CASCADE;

DROP TABLE IF EXISTS "financial"."second_brain_financial_amount_facts_normalized" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_evaluation_runs" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_agent_run_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."second_brain_agent_model_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."schema_migrations" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_version_identity_matches" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_version_diffs" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_version_diff_impact_rollups" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_version_diff_facts" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_version_diff_detail_facts" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_source_capabilities" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_quality_scorecards" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_quality_metric_results" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_quality_findings" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_quality_evaluation_runs" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_package_field_lineage" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_package_equivalence_facts" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_import_packages" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_import_package_files" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_identity_manual_actions" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_identities" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_file_imports" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cpm_runs" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cpm_relationship_results" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cpm_paths" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cpm_path_activities" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cpm_import_observability" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cpm_diagnostics" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cpm_activity_results" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cost_weighting_results" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cost_mapping_runs" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cost_mapping_candidates" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_cost_distributions" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_wbs" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_udfs" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_relationships" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_projects" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_health_facts" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_activity_crosswalk" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_activity_codes" CASCADE;

DROP TABLE IF EXISTS "schedule"."schedule_baseline_activities" CASCADE;

DROP TABLE IF EXISTS "core"."retrieval_query_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."retrieval_context_refs" CASCADE;

DROP TABLE IF EXISTS "core"."relationship_resolution_queue" CASCADE;

DROP TABLE IF EXISTS "core"."relationship_quality_mart" CASCADE;

DROP TABLE IF EXISTS "core"."raw_content_source_quality_snapshots" CASCADE;

DROP TABLE IF EXISTS "core"."raw_content_policy_state" CASCADE;

DROP TABLE IF EXISTS "core"."raw_content_access_events" CASCADE;

DROP TABLE IF EXISTS "core"."ranking_policy_eval_runs" CASCADE;

DROP TABLE IF EXISTS "core"."ranking_policy_eval_items" CASCADE;

DROP TABLE IF EXISTS "core"."query_tool_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."project_source_coverage_mart" CASCADE;

DROP TABLE IF EXISTS "schedule"."project_schedule_series_membership" CASCADE;

DROP TABLE IF EXISTS "schedule"."project_schedule_review_items" CASCADE;

DROP TABLE IF EXISTS "schedule"."project_schedule_review_item_events" CASCADE;

DROP TABLE IF EXISTS "schedule"."project_schedule_named_baseline_slots" CASCADE;

DROP TABLE IF EXISTS "schedule"."project_schedule_named_baseline_review_items" CASCADE;

DROP TABLE IF EXISTS "schedule"."project_schedule_named_baseline_review_item_events" CASCADE;

DROP TABLE IF EXISTS "schedule"."project_schedule_baseline_selections" CASCADE;

DROP TABLE IF EXISTS "core"."project_risk_digest_items" CASCADE;

DROP TABLE IF EXISTS "core"."project_issue_history_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_text_intelligence" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_synced_entities" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_sync_watermarks" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_sync_runs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_sync_errors" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_record_timeline_events" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_record_edges" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_submittal_packages" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_status_dimensions" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_rfq_responses" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_rfi_responses" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_project_dimensions" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_meeting_topics" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_meeting_details" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_invoices" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_invoice_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_date_dimensions" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_daily_logs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_cost_code_dimensions" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_contracts" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_contract_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_change_orders" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_change_order_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_change_event_comments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_budget_rows" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_budget_columns" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_budget_changes" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_raw_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_people_entities" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_location_entities" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_live_sync_watermarks" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_live_sync_runs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_live_records" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_live_record_state_index" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_live_record_snapshots" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_live_record_change_events" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_inspection_sections" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_inspection_response_sets" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_inspection_response_options" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_inspection_records" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_inspection_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_inspection_evidence_rules" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_subcontractor_invoices" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_rfqs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_invoice_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_contracts" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_compliance_documents" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_change_orders" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_change_order_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_change_events" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_budget_views" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_budget_rows" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_budget_changes" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_billing_periods" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_financial_amount_facts" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_submittals_ball_in_court" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_submittals_approvers_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_submittals_approvers" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_submittals" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_subcontractor_invoices_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_subcontractor_invoices" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_subcontractor_invoice_contract_detail_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_subcontractor_invoice_change_order_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_schedules" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_schedule_wbs_nodes" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_schedule_udf_values" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_schedule_relationships" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_schedule_calendars" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_schedule_activity_code_assignments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_schedule_activities" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfqs_change_event_change_event_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfqs_change_event_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfqs_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfqs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfis_questions" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfis_ball_in_courts" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfis_assignees" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_rfis" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_purchase_order_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_purchase_order_contracts" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_punch_items_ball_in_court" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_punch_items_assignments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_punch_items_assignees" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_punch_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_projects_custom_fields_custom_field_163302_value" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_projects_custom_fields_custom_field_163299_value" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_projects_custom_fields_custom_field_163296_value" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_projects_custom_fields_custom_field_163293_value" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_projects_custom_fields_custom_field_163290_value" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_projects_custom_fields_custom_field_163287_value" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_projects" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_prime_contracts" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_prime_contract_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_prime_change_orders" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_prime_change_order_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_observations_assignees" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_observations" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_meetings" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspections_signature_requests" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspections_inspectors" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspections_distribution_members" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspections_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspections" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspection_sections" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspection_items_response_set_responses" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_inspection_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_weather" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_visitor" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_notes_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_notes" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_manpower_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_manpower" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_inspections_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_inspections" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_deliveries_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_deliveries" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_dcrs_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_daily_log_dcrs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_commitment_line_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_commitment_contracts" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_commitment_compliance_insurance_documents" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_commitment_compliance" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_commitment_change_orders" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_commitment_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_change_events_markup_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_change_events_change_items" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_change_events_attachments" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_change_events" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_budget_views" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_budget_modifications" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_budget_detail_rows" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_budget_detail_row_cells" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_budget_detail_columns" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_budget_change_history" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_ep_billing_periods" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_endpoint_raw_payloads" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_endpoint_capture_runs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_endpoint_capture_pages" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_endpoint_capture_errors" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_custom_field_values" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_company_entities" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_attachment_refs" CASCADE;

DROP TABLE IF EXISTS "procore"."procore_action_signals" CASCADE;

DROP TABLE IF EXISTS "core"."phase10_relationship_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."parser_outputs" CASCADE;

DROP TABLE IF EXISTS "core"."pa_promotion_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."pa_artifact_validation_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."obsidian_note_update_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."obsidian_note_tag_index" CASCADE;

DROP TABLE IF EXISTS "core"."obsidian_note_index" CASCADE;

DROP TABLE IF EXISTS "core"."obsidian_managed_section_registry" CASCADE;

DROP TABLE IF EXISTS "core"."obsidian_index_manifests" CASCADE;

DROP TABLE IF EXISTS "core"."obsidian_index_entries" CASCADE;

DROP TABLE IF EXISTS "core"."model_profile_eval_results" CASCADE;

DROP TABLE IF EXISTS "core"."memory_update_reviews" CASCADE;

DROP TABLE IF EXISTS "core"."memory_update_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."meeting_prep_brief_sections" CASCADE;

DROP TABLE IF EXISTS "core"."meeting_prep_brief_runs" CASCADE;

DROP TABLE IF EXISTS "core"."meeting_email_relationship_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."long_term_memory_source_refs" CASCADE;

DROP TABLE IF EXISTS "core"."long_term_memory_quality_signals" CASCADE;

DROP TABLE IF EXISTS "core"."long_term_memory_items" CASCADE;

DROP TABLE IF EXISTS "core"."local_model_status_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."local_model_run_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."local_model_profiles" CASCADE;

DROP TABLE IF EXISTS "core"."launchd_schedule_previews" CASCADE;

DROP TABLE IF EXISTS "core"."interactive_chat_sessions" CASCADE;

DROP TABLE IF EXISTS "core"."interactive_chat_message_receipts" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_validation_events" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_staffing_templates" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_staffing_template_versions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_staffing_cost_codes" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_source_ingestions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_runs" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_run_model_versions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_review_items" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_required_assumptions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_projects" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_staffing_snapshots" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_staffing_snapshot_rows" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_staffing_config" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_staffing_attribution_rules" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_staffing_attribution_review_items" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_staffing_assumptions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_staffing_absence_overrides" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_project_maturity_snapshots" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_package_manifests" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_outputs" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_staffing" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_schedule_phasing" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_risks" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_probability" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_narratives" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_monthly_table_totals" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_monthly_table_rows" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_monthly" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_commitment_exposure" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_changes" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_output_budget_codes" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_operator_assumptions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_monthly_actuals_by_budget_code" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_model_versions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_model_selection_decisions" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_method_eligibility" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_generation_requests" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_external_forecasts" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_external_forecast_rows" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_external_forecast_mappings" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_evidence_packages" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_data_availability_profiles" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_cost_entry_staffing_actuals" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_cost_entries" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_config_sources" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_config_snapshots" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_config_snapshot_items" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_config_items" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_confidence_scorecards" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_confidence_factors" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_comparison_results" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_calibration_weights" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_budget_details" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_anomaly_findings" CASCADE;

DROP TABLE IF EXISTS "financial"."forecast_accuracy_results" CASCADE;

DROP TABLE IF EXISTS "core"."follow_up_watch_items" CASCADE;

DROP TABLE IF EXISTS "core"."follow_up_status_events" CASCADE;

DROP TABLE IF EXISTS "core"."files" CASCADE;

DROP TABLE IF EXISTS "email"."email_thread_summary_materialization_runs" CASCADE;

DROP TABLE IF EXISTS "email"."email_thread_summaries" CASCADE;

DROP TABLE IF EXISTS "email"."email_thread_raw_context" CASCADE;

DROP TABLE IF EXISTS "email"."email_sync_state" CASCADE;

DROP TABLE IF EXISTS "email"."email_source_locations" CASCADE;

DROP TABLE IF EXISTS "email"."email_review_queue" CASCADE;

DROP TABLE IF EXISTS "email"."email_relationship_candidates" CASCADE;

DROP TABLE IF EXISTS "email"."email_raw_thread_structured" CASCADE;

DROP TABLE IF EXISTS "email"."email_raw_thread_messages_structured" CASCADE;

DROP TABLE IF EXISTS "email"."email_raw_message_structured" CASCADE;

DROP TABLE IF EXISTS "email"."email_raw_message_recipients_structured" CASCADE;

DROP TABLE IF EXISTS "email"."email_raw_message_attachments_structured" CASCADE;

DROP TABLE IF EXISTS "email"."email_project_matches" CASCADE;

DROP TABLE IF EXISTS "email"."email_processing_receipts" CASCADE;

DROP TABLE IF EXISTS "email"."email_model_classifications" CASCADE;

DROP TABLE IF EXISTS "email"."email_messages" CASCADE;

DROP TABLE IF EXISTS "email"."email_message_recipients" CASCADE;

DROP TABLE IF EXISTS "email"."email_message_raw_content" CASCADE;

DROP TABLE IF EXISTS "email"."email_message_body_vault_refs" CASCADE;

DROP TABLE IF EXISTS "email"."email_message_attachments" CASCADE;

DROP TABLE IF EXISTS "email"."email_intelligence_active_policy" CASCADE;

DROP TABLE IF EXISTS "email"."email_followup_enrichments" CASCADE;

DROP TABLE IF EXISTS "email"."email_crawl_runs" CASCADE;

DROP TABLE IF EXISTS "email"."email_calendar_raw_ingestion_runs" CASCADE;

DROP TABLE IF EXISTS "email"."email_calendar_projection_runs" CASCADE;

DROP TABLE IF EXISTS "email"."email_calendar_projection_coverage" CASCADE;

DROP TABLE IF EXISTS "core"."data_quality_gate_results" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_source_refs" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_runs" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_ranking_runs" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_ranked_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_open_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_notification_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_item_outcome_events" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_html_render_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_handoff_lines" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_exposure_events" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_delivery_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_change_events" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_change_event_refs" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_assembly_sections" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_assembly_runs" CASCADE;

DROP TABLE IF EXISTS "core"."daily_brief_action_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."cross_source_relationships" CASCADE;

DROP TABLE IF EXISTS "core"."cross_source_relationship_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."cross_source_intelligence_obsidian_runs" CASCADE;

DROP TABLE IF EXISTS "core"."cross_domain_context_readiness_mart" CASCADE;

DROP TABLE IF EXISTS "core"."content_embeddings" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_table_lifecycle_registry" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_sync_errors" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_source_sync_state" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_source_resolutions" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_source_locations" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_source_crawl_runs" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_review_queue" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_project_source_matches" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_project_keyword_registry" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_project_identity" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_processing_receipts" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_model_decisions" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_graph_link_resolution" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_graph_download_receipts" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_file_ingestion_decisions" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_file_extraction_runs" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_drive_items" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_drive_item_inventory" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_document_relationship_candidates" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_document_project_match_candidates" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_document_intelligence_previews" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_document_classification_candidates" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_document_cards" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_delta_tokens" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_data_quality_runs" CASCADE;

DROP TABLE IF EXISTS "construction"."construction_crawl_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."commitment_candidates" CASCADE;

DROP TABLE IF EXISTS "core"."claude_context_packets" CASCADE;

DROP TABLE IF EXISTS "core"."claude_context_packet_items" CASCADE;

DROP TABLE IF EXISTS "core"."candidate_suppression_rules" CASCADE;

DROP TABLE IF EXISTS "core"."candidate_source_refs" CASCADE;

DROP TABLE IF EXISTS "core"."candidate_similarity_edges" CASCADE;

DROP TABLE IF EXISTS "core"."candidate_review_events" CASCADE;

DROP TABLE IF EXISTS "core"."candidate_merge_links" CASCADE;

DROP TABLE IF EXISTS "core"."candidate_lifecycle_events" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_sync_state" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_source_locations" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_raw_event_structured" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_raw_event_recurrence_structured" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_raw_event_locations_structured" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_raw_event_attendees_structured" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_project_match_candidates" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_event_raw_content" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_event_index" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_event_attendees" CASCADE;

DROP TABLE IF EXISTS "calendar"."calendar_crawl_runs" CASCADE;

DROP TABLE IF EXISTS "core"."brief_effectiveness_rollups" CASCADE;

DROP TABLE IF EXISTS "core"."attachments" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_runs" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_review_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_research_packets" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_research_packet_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_research_packet_items" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_research_packet_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_research_packet_citations" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_quality_runs" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_quality_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_quality_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_output_file_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_memory_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_memory_compilations" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_intelligence_projections" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_intelligence_projection_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_intelligence_projection_items" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_intelligence_projection_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_feedback_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_feedback_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_enrichment_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_enrichment_jobs" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_decision_memory_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_context_packs" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_context_pack_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_context_pack_items" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_context_pack_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_claim_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_answer_drafts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_answer_draft_sections" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_answer_draft_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_answer_draft_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_answer_draft_citations" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_action_stages" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_action_stage_receipts" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_action_stage_items" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_action_stage_events" CASCADE;

DROP TABLE IF EXISTS "core"."assistant_action_stage_citations" CASCADE;

DROP TABLE IF EXISTS "core"."ai_job_runs" CASCADE;

DROP TABLE IF EXISTS "core"."ai_job_queue" CASCADE;

DROP TABLE IF EXISTS "financial"."aging_exposure_report_items" CASCADE;

DROP TABLE IF EXISTS "core"."action_items" CASCADE;

DROP TABLE IF EXISTS "core"."accepted_tasks" CASCADE;

DROP TABLE IF EXISTS "core"."accepted_commitments" CASCADE;
