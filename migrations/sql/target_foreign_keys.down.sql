ALTER TABLE "financial"."staffing_holiday_calendar_dates" DROP CONSTRAINT IF EXISTS "staffing_holiday_calendar_dates_fk0";

ALTER TABLE "core"."source_links" DROP CONSTRAINT IF EXISTS "source_links_fk2";

ALTER TABLE "core"."source_links" DROP CONSTRAINT IF EXISTS "source_links_fk1";

ALTER TABLE "core"."source_links" DROP CONSTRAINT IF EXISTS "source_links_fk0";

ALTER TABLE "core"."source_intelligence_text" DROP CONSTRAINT IF EXISTS "source_intelligence_text_fk0";

ALTER TABLE "core"."source_intelligence_summaries" DROP CONSTRAINT IF EXISTS "source_intelligence_summaries_fk0";

ALTER TABLE "core"."source_intelligence_sources" DROP CONSTRAINT IF EXISTS "source_intelligence_sources_fk0";

ALTER TABLE "core"."source_intelligence_relationships" DROP CONSTRAINT IF EXISTS "source_intelligence_relationships_fk0";

ALTER TABLE "core"."source_intelligence_metadata" DROP CONSTRAINT IF EXISTS "source_intelligence_metadata_fk0";

ALTER TABLE "core"."source_intelligence_generated_notes" DROP CONSTRAINT IF EXISTS "source_intelligence_generated_notes_fk0";

ALTER TABLE "core"."source_intelligence_events" DROP CONSTRAINT IF EXISTS "source_intelligence_events_fk0";

ALTER TABLE "core"."source_intelligence_chunks" DROP CONSTRAINT IF EXISTS "source_intelligence_chunks_fk0";

ALTER TABLE "core"."source_index_scan_quarantine" DROP CONSTRAINT IF EXISTS "source_index_scan_quarantine_fk0";

ALTER TABLE "core"."source_index_locators" DROP CONSTRAINT IF EXISTS "source_index_locators_fk0";

ALTER TABLE "core"."second_brain_agent_model_receipts" DROP CONSTRAINT IF EXISTS "second_brain_agent_model_receipts_fk0";

ALTER TABLE "schedule"."schedule_version_identity_matches" DROP CONSTRAINT IF EXISTS "schedule_version_identity_matches_fk0";

ALTER TABLE "schedule"."schedule_quality_scorecards" DROP CONSTRAINT IF EXISTS "schedule_quality_scorecards_fk0";

ALTER TABLE "schedule"."schedule_quality_metric_results" DROP CONSTRAINT IF EXISTS "schedule_quality_metric_results_fk0";

ALTER TABLE "schedule"."schedule_import_package_files" DROP CONSTRAINT IF EXISTS "schedule_import_package_files_fk0";

ALTER TABLE "schedule"."schedule_cpm_relationship_results" DROP CONSTRAINT IF EXISTS "schedule_cpm_relationship_results_fk0";

ALTER TABLE "schedule"."schedule_cpm_paths" DROP CONSTRAINT IF EXISTS "schedule_cpm_paths_fk0";

ALTER TABLE "schedule"."schedule_cpm_path_activities" DROP CONSTRAINT IF EXISTS "schedule_cpm_path_activities_fk1";

ALTER TABLE "schedule"."schedule_cpm_path_activities" DROP CONSTRAINT IF EXISTS "schedule_cpm_path_activities_fk0";

ALTER TABLE "schedule"."schedule_cpm_diagnostics" DROP CONSTRAINT IF EXISTS "schedule_cpm_diagnostics_fk0";

ALTER TABLE "schedule"."schedule_cpm_activity_results" DROP CONSTRAINT IF EXISTS "schedule_cpm_activity_results_fk0";

ALTER TABLE "schedule"."schedule_cost_weighting_results" DROP CONSTRAINT IF EXISTS "schedule_cost_weighting_results_fk0";

ALTER TABLE "schedule"."schedule_cost_mapping_candidates" DROP CONSTRAINT IF EXISTS "schedule_cost_mapping_candidates_fk0";

ALTER TABLE "schedule"."schedule_cost_distributions" DROP CONSTRAINT IF EXISTS "schedule_cost_distributions_fk0";

ALTER TABLE "schedule"."schedule_baseline_activities" DROP CONSTRAINT IF EXISTS "schedule_baseline_activities_fk0";

ALTER TABLE "core"."retrieval_context_refs" DROP CONSTRAINT IF EXISTS "retrieval_context_refs_fk0";

ALTER TABLE "procore"."procore_raw_submittal_packages" DROP CONSTRAINT IF EXISTS "procore_raw_submittal_packages_fk0";

ALTER TABLE "procore"."procore_raw_status_dimensions" DROP CONSTRAINT IF EXISTS "procore_raw_status_dimensions_fk0";

ALTER TABLE "procore"."procore_raw_rfq_responses" DROP CONSTRAINT IF EXISTS "procore_raw_rfq_responses_fk0";

ALTER TABLE "procore"."procore_raw_rfi_responses" DROP CONSTRAINT IF EXISTS "procore_raw_rfi_responses_fk0";

ALTER TABLE "procore"."procore_raw_project_dimensions" DROP CONSTRAINT IF EXISTS "procore_raw_project_dimensions_fk0";

ALTER TABLE "procore"."procore_raw_meeting_topics" DROP CONSTRAINT IF EXISTS "procore_raw_meeting_topics_fk0";

ALTER TABLE "procore"."procore_raw_meeting_details" DROP CONSTRAINT IF EXISTS "procore_raw_meeting_details_fk0";

ALTER TABLE "procore"."procore_raw_invoices" DROP CONSTRAINT IF EXISTS "procore_raw_invoices_fk0";

ALTER TABLE "procore"."procore_raw_invoice_items" DROP CONSTRAINT IF EXISTS "procore_raw_invoice_items_fk0";

ALTER TABLE "procore"."procore_raw_date_dimensions" DROP CONSTRAINT IF EXISTS "procore_raw_date_dimensions_fk0";

ALTER TABLE "procore"."procore_raw_daily_logs" DROP CONSTRAINT IF EXISTS "procore_raw_daily_logs_fk0";

ALTER TABLE "procore"."procore_raw_cost_code_dimensions" DROP CONSTRAINT IF EXISTS "procore_raw_cost_code_dimensions_fk0";

ALTER TABLE "procore"."procore_raw_contracts" DROP CONSTRAINT IF EXISTS "procore_raw_contracts_fk0";

ALTER TABLE "procore"."procore_raw_contract_line_items" DROP CONSTRAINT IF EXISTS "procore_raw_contract_line_items_fk0";

ALTER TABLE "procore"."procore_raw_change_orders" DROP CONSTRAINT IF EXISTS "procore_raw_change_orders_fk0";

ALTER TABLE "procore"."procore_raw_change_order_line_items" DROP CONSTRAINT IF EXISTS "procore_raw_change_order_line_items_fk0";

ALTER TABLE "procore"."procore_raw_change_event_comments" DROP CONSTRAINT IF EXISTS "procore_raw_change_event_comments_fk0";

ALTER TABLE "procore"."procore_raw_budget_rows" DROP CONSTRAINT IF EXISTS "procore_raw_budget_rows_fk0";

ALTER TABLE "procore"."procore_raw_budget_columns" DROP CONSTRAINT IF EXISTS "procore_raw_budget_columns_fk0";

ALTER TABLE "procore"."procore_raw_budget_changes" DROP CONSTRAINT IF EXISTS "procore_raw_budget_changes_fk0";

ALTER TABLE "procore"."procore_raw_attachments" DROP CONSTRAINT IF EXISTS "procore_raw_attachments_fk0";

ALTER TABLE "procore"."procore_live_records" DROP CONSTRAINT IF EXISTS "procore_live_records_fk0";

ALTER TABLE "procore"."procore_ep_submittals_ball_in_court" DROP CONSTRAINT IF EXISTS "procore_ep_submittals_ball_in_court_fk1";

ALTER TABLE "procore"."procore_ep_submittals_ball_in_court" DROP CONSTRAINT IF EXISTS "procore_ep_submittals_ball_in_court_fk0";

ALTER TABLE "procore"."procore_ep_submittals_approvers_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_submittals_approvers_attachments_fk1";

ALTER TABLE "procore"."procore_ep_submittals_approvers_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_submittals_approvers_attachments_fk0";

ALTER TABLE "procore"."procore_ep_submittals_approvers" DROP CONSTRAINT IF EXISTS "procore_ep_submittals_approvers_fk1";

ALTER TABLE "procore"."procore_ep_submittals_approvers" DROP CONSTRAINT IF EXISTS "procore_ep_submittals_approvers_fk0";

ALTER TABLE "procore"."procore_ep_submittals" DROP CONSTRAINT IF EXISTS "procore_ep_submittals_fk0";

ALTER TABLE "procore"."procore_ep_subcontractor_invoices_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_subcontractor_invoices_attachments_fk1";

ALTER TABLE "procore"."procore_ep_subcontractor_invoices_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_subcontractor_invoices_attachments_fk0";

ALTER TABLE "procore"."procore_ep_subcontractor_invoices" DROP CONSTRAINT IF EXISTS "procore_ep_subcontractor_invoices_fk0";

ALTER TABLE "procore"."procore_ep_subcontractor_invoice_contract_detail_items" DROP CONSTRAINT IF EXISTS "procore_ep_subcontractor_invoice_contract_detail_items_fk0";

ALTER TABLE "procore"."procore_ep_subcontractor_invoice_change_order_items" DROP CONSTRAINT IF EXISTS "procore_ep_subcontractor_invoice_change_order_items_fk0";

ALTER TABLE "procore"."procore_ep_schedules" DROP CONSTRAINT IF EXISTS "procore_ep_schedules_fk0";

ALTER TABLE "procore"."procore_ep_schedule_wbs_nodes" DROP CONSTRAINT IF EXISTS "procore_ep_schedule_wbs_nodes_fk0";

ALTER TABLE "procore"."procore_ep_schedule_udf_values" DROP CONSTRAINT IF EXISTS "procore_ep_schedule_udf_values_fk0";

ALTER TABLE "procore"."procore_ep_schedule_relationships" DROP CONSTRAINT IF EXISTS "procore_ep_schedule_relationships_fk0";

ALTER TABLE "procore"."procore_ep_schedule_calendars" DROP CONSTRAINT IF EXISTS "procore_ep_schedule_calendars_fk0";

ALTER TABLE "procore"."procore_ep_schedule_activity_code_assignments" DROP CONSTRAINT IF EXISTS "procore_ep_schedule_activity_code_assignments_fk0";

ALTER TABLE "procore"."procore_ep_schedule_activities" DROP CONSTRAINT IF EXISTS "procore_ep_schedule_activities_fk0";

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_change_event_change_event_line_items__0_fceb630";

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items__0a3e8d" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_change_event_change_event_line_items__0_cf38b3d";

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_change_event_change_event_line_items_fk1";

ALTER TABLE "procore"."procore_ep_rfqs_change_event_change_event_line_items" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_change_event_change_event_line_items_fk0";

ALTER TABLE "procore"."procore_ep_rfqs_change_event_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_change_event_attachments_fk1";

ALTER TABLE "procore"."procore_ep_rfqs_change_event_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_change_event_attachments_fk0";

ALTER TABLE "procore"."procore_ep_rfqs_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_attachments_fk1";

ALTER TABLE "procore"."procore_ep_rfqs_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_attachments_fk0";

ALTER TABLE "procore"."procore_ep_rfqs" DROP CONSTRAINT IF EXISTS "procore_ep_rfqs_fk0";

ALTER TABLE "procore"."procore_ep_rfis_questions" DROP CONSTRAINT IF EXISTS "procore_ep_rfis_questions_fk1";

ALTER TABLE "procore"."procore_ep_rfis_questions" DROP CONSTRAINT IF EXISTS "procore_ep_rfis_questions_fk0";

ALTER TABLE "procore"."procore_ep_rfis_ball_in_courts" DROP CONSTRAINT IF EXISTS "procore_ep_rfis_ball_in_courts_fk1";

ALTER TABLE "procore"."procore_ep_rfis_ball_in_courts" DROP CONSTRAINT IF EXISTS "procore_ep_rfis_ball_in_courts_fk0";

ALTER TABLE "procore"."procore_ep_rfis_assignees" DROP CONSTRAINT IF EXISTS "procore_ep_rfis_assignees_fk1";

ALTER TABLE "procore"."procore_ep_rfis_assignees" DROP CONSTRAINT IF EXISTS "procore_ep_rfis_assignees_fk0";

ALTER TABLE "procore"."procore_ep_rfis" DROP CONSTRAINT IF EXISTS "procore_ep_rfis_fk0";

ALTER TABLE "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd" DROP CONSTRAINT IF EXISTS "procore_ep_purchase_order_line_items_cost_code_line_i_7_3f92a3e";

ALTER TABLE "procore"."procore_ep_purchase_order_line_items_cost_code_line_i_779dbd" DROP CONSTRAINT IF EXISTS "procore_ep_purchase_order_line_items_cost_code_line_i_7_41f7610";

ALTER TABLE "procore"."procore_ep_purchase_order_line_items" DROP CONSTRAINT IF EXISTS "procore_ep_purchase_order_line_items_fk0";

ALTER TABLE "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65" DROP CONSTRAINT IF EXISTS "procore_ep_purchase_order_contracts_custom_fields_cus_a_704520b";

ALTER TABLE "procore"."procore_ep_purchase_order_contracts_custom_fields_cus_a0fe65" DROP CONSTRAINT IF EXISTS "procore_ep_purchase_order_contracts_custom_fields_cus_a_0ac8f8d";

ALTER TABLE "procore"."procore_ep_purchase_order_contracts" DROP CONSTRAINT IF EXISTS "procore_ep_purchase_order_contracts_fk0";

ALTER TABLE "procore"."procore_ep_punch_items_ball_in_court" DROP CONSTRAINT IF EXISTS "procore_ep_punch_items_ball_in_court_fk1";

ALTER TABLE "procore"."procore_ep_punch_items_ball_in_court" DROP CONSTRAINT IF EXISTS "procore_ep_punch_items_ball_in_court_fk0";

ALTER TABLE "procore"."procore_ep_punch_items_assignments" DROP CONSTRAINT IF EXISTS "procore_ep_punch_items_assignments_fk1";

ALTER TABLE "procore"."procore_ep_punch_items_assignments" DROP CONSTRAINT IF EXISTS "procore_ep_punch_items_assignments_fk0";

ALTER TABLE "procore"."procore_ep_punch_items_assignees" DROP CONSTRAINT IF EXISTS "procore_ep_punch_items_assignees_fk1";

ALTER TABLE "procore"."procore_ep_punch_items_assignees" DROP CONSTRAINT IF EXISTS "procore_ep_punch_items_assignees_fk0";

ALTER TABLE "procore"."procore_ep_punch_items" DROP CONSTRAINT IF EXISTS "procore_ep_punch_items_fk0";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163302_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163302_value_fk1";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163302_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163302_value_fk0";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163299_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163299_value_fk1";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163299_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163299_value_fk0";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163296_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163296_value_fk1";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163296_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163296_value_fk0";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163293_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163293_value_fk1";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163293_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163293_value_fk0";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163290_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163290_value_fk1";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163290_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163290_value_fk0";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163287_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163287_value_fk1";

ALTER TABLE "procore"."procore_ep_projects_custom_fields_custom_field_163287_value" DROP CONSTRAINT IF EXISTS "procore_ep_projects_custom_fields_custom_field_163287_value_fk0";

ALTER TABLE "procore"."procore_ep_projects" DROP CONSTRAINT IF EXISTS "procore_ep_projects_fk0";

ALTER TABLE "procore"."procore_ep_prime_contracts" DROP CONSTRAINT IF EXISTS "procore_ep_prime_contracts_fk0";

ALTER TABLE "procore"."procore_ep_prime_contract_line_items" DROP CONSTRAINT IF EXISTS "procore_ep_prime_contract_line_items_fk0";

ALTER TABLE "procore"."procore_ep_prime_change_orders" DROP CONSTRAINT IF EXISTS "procore_ep_prime_change_orders_fk0";

ALTER TABLE "procore"."procore_ep_prime_change_order_line_items" DROP CONSTRAINT IF EXISTS "procore_ep_prime_change_order_line_items_fk0";

ALTER TABLE "procore"."procore_ep_observations_assignees" DROP CONSTRAINT IF EXISTS "procore_ep_observations_assignees_fk1";

ALTER TABLE "procore"."procore_ep_observations_assignees" DROP CONSTRAINT IF EXISTS "procore_ep_observations_assignees_fk0";

ALTER TABLE "procore"."procore_ep_observations" DROP CONSTRAINT IF EXISTS "procore_ep_observations_fk0";

ALTER TABLE "procore"."procore_ep_meetings" DROP CONSTRAINT IF EXISTS "procore_ep_meetings_fk0";

ALTER TABLE "procore"."procore_ep_inspections_signature_requests" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_signature_requests_fk1";

ALTER TABLE "procore"."procore_ep_inspections_signature_requests" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_signature_requests_fk0";

ALTER TABLE "procore"."procore_ep_inspections_inspectors" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_inspectors_fk1";

ALTER TABLE "procore"."procore_ep_inspections_inspectors" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_inspectors_fk0";

ALTER TABLE "procore"."procore_ep_inspections_distribution_members" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_distribution_members_fk1";

ALTER TABLE "procore"."procore_ep_inspections_distribution_members" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_distribution_members_fk0";

ALTER TABLE "procore"."procore_ep_inspections_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_attachments_fk1";

ALTER TABLE "procore"."procore_ep_inspections_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_attachments_fk0";

ALTER TABLE "procore"."procore_ep_inspections" DROP CONSTRAINT IF EXISTS "procore_ep_inspections_fk0";

ALTER TABLE "procore"."procore_ep_inspection_sections" DROP CONSTRAINT IF EXISTS "procore_ep_inspection_sections_fk0";

ALTER TABLE "procore"."procore_ep_inspection_items_response_set_responses" DROP CONSTRAINT IF EXISTS "procore_ep_inspection_items_response_set_responses_fk1";

ALTER TABLE "procore"."procore_ep_inspection_items_response_set_responses" DROP CONSTRAINT IF EXISTS "procore_ep_inspection_items_response_set_responses_fk0";

ALTER TABLE "procore"."procore_ep_inspection_items" DROP CONSTRAINT IF EXISTS "procore_ep_inspection_items_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_weather" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_weather_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_visitor" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_visitor_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_notes_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_notes_attachments_fk1";

ALTER TABLE "procore"."procore_ep_daily_log_notes_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_notes_attachments_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_notes" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_notes_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_manpower_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_manpower_attachments_fk1";

ALTER TABLE "procore"."procore_ep_daily_log_manpower_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_manpower_attachments_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_manpower" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_manpower_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_inspections_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_inspections_attachments_fk1";

ALTER TABLE "procore"."procore_ep_daily_log_inspections_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_inspections_attachments_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_inspections" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_inspections_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_deliveries_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_deliveries_attachments_fk1";

ALTER TABLE "procore"."procore_ep_daily_log_deliveries_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_deliveries_attachments_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_deliveries" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_deliveries_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_dcrs_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_dcrs_attachments_fk1";

ALTER TABLE "procore"."procore_ep_daily_log_dcrs_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_dcrs_attachments_fk0";

ALTER TABLE "procore"."procore_ep_daily_log_dcrs" DROP CONSTRAINT IF EXISTS "procore_ep_daily_log_dcrs_fk0";

ALTER TABLE "procore"."procore_ep_commitment_line_items" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_line_items_fk0";

ALTER TABLE "procore"."procore_ep_commitment_contracts" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_contracts_fk0";

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_compliance_insurance_documents__5_75c8e3c";

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents__52b7bf" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_compliance_insurance_documents__5_41ce87c";

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_compliance_insurance_documents_fk1";

ALTER TABLE "procore"."procore_ep_commitment_compliance_insurance_documents" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_compliance_insurance_documents_fk0";

ALTER TABLE "procore"."procore_ep_commitment_compliance" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_compliance_fk0";

ALTER TABLE "procore"."procore_ep_commitment_change_orders" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_change_orders_fk0";

ALTER TABLE "procore"."procore_ep_commitment_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_commitment_attachments_fk0";

ALTER TABLE "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_markup_items_wbs_code_segment__ff5a597";

ALTER TABLE "procore"."procore_ep_change_events_markup_items_wbs_code_segment_items" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_markup_items_wbs_code_segment__31f7e91";

ALTER TABLE "procore"."procore_ep_change_events_markup_items" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_markup_items_fk1";

ALTER TABLE "procore"."procore_ep_change_events_markup_items" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_markup_items_fk0";

ALTER TABLE "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_change_items_budget_code_seg_2_69e5270";

ALTER TABLE "procore"."procore_ep_change_events_change_items_budget_code_seg_2dff22" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_change_items_budget_code_seg_2_9ebf97c";

ALTER TABLE "procore"."procore_ep_change_events_change_items" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_change_items_fk1";

ALTER TABLE "procore"."procore_ep_change_events_change_items" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_change_items_fk0";

ALTER TABLE "procore"."procore_ep_change_events_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_attachments_fk1";

ALTER TABLE "procore"."procore_ep_change_events_attachments" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_attachments_fk0";

ALTER TABLE "procore"."procore_ep_change_events" DROP CONSTRAINT IF EXISTS "procore_ep_change_events_fk0";

ALTER TABLE "procore"."procore_ep_budget_views" DROP CONSTRAINT IF EXISTS "procore_ep_budget_views_fk0";

ALTER TABLE "procore"."procore_ep_budget_modifications" DROP CONSTRAINT IF EXISTS "procore_ep_budget_modifications_fk0";

ALTER TABLE "procore"."procore_ep_budget_detail_rows" DROP CONSTRAINT IF EXISTS "procore_ep_budget_detail_rows_fk0";

ALTER TABLE "procore"."procore_ep_budget_detail_row_cells" DROP CONSTRAINT IF EXISTS "procore_ep_budget_detail_row_cells_fk1";

ALTER TABLE "procore"."procore_ep_budget_detail_row_cells" DROP CONSTRAINT IF EXISTS "procore_ep_budget_detail_row_cells_fk0";

ALTER TABLE "procore"."procore_ep_budget_detail_columns" DROP CONSTRAINT IF EXISTS "procore_ep_budget_detail_columns_fk0";

ALTER TABLE "procore"."procore_ep_budget_change_history" DROP CONSTRAINT IF EXISTS "procore_ep_budget_change_history_fk0";

ALTER TABLE "procore"."procore_ep_billing_periods" DROP CONSTRAINT IF EXISTS "procore_ep_billing_periods_fk0";

ALTER TABLE "procore"."procore_endpoint_capture_pages" DROP CONSTRAINT IF EXISTS "procore_endpoint_capture_pages_fk0";

ALTER TABLE "core"."parser_outputs" DROP CONSTRAINT IF EXISTS "parser_outputs_fk0";

ALTER TABLE "core"."obsidian_note_tag_index" DROP CONSTRAINT IF EXISTS "obsidian_note_tag_index_fk0";

ALTER TABLE "core"."obsidian_managed_section_registry" DROP CONSTRAINT IF EXISTS "obsidian_managed_section_registry_fk0";

ALTER TABLE "core"."obsidian_index_entries" DROP CONSTRAINT IF EXISTS "obsidian_index_entries_fk0";

ALTER TABLE "core"."memory_update_reviews" DROP CONSTRAINT IF EXISTS "memory_update_reviews_fk0";

ALTER TABLE "core"."meeting_prep_brief_sections" DROP CONSTRAINT IF EXISTS "meeting_prep_brief_sections_fk0";

ALTER TABLE "core"."meeting_email_relationship_candidates" DROP CONSTRAINT IF EXISTS "meeting_email_relationship_candidates_fk0";

ALTER TABLE "core"."long_term_memory_source_refs" DROP CONSTRAINT IF EXISTS "long_term_memory_source_refs_fk0";

ALTER TABLE "core"."long_term_memory_quality_signals" DROP CONSTRAINT IF EXISTS "long_term_memory_quality_signals_fk0";

ALTER TABLE "core"."interactive_chat_message_receipts" DROP CONSTRAINT IF EXISTS "interactive_chat_message_receipts_fk0";

ALTER TABLE "financial"."forecast_staffing_template_versions" DROP CONSTRAINT IF EXISTS "forecast_staffing_template_versions_fk0";

ALTER TABLE "financial"."forecast_run_model_versions" DROP CONSTRAINT IF EXISTS "forecast_run_model_versions_fk1";

ALTER TABLE "financial"."forecast_run_model_versions" DROP CONSTRAINT IF EXISTS "forecast_run_model_versions_fk0";

ALTER TABLE "financial"."forecast_review_items" DROP CONSTRAINT IF EXISTS "forecast_review_items_fk0";

ALTER TABLE "financial"."forecast_required_assumptions" DROP CONSTRAINT IF EXISTS "forecast_required_assumptions_fk0";

ALTER TABLE "financial"."forecast_project_staffing_snapshot_rows" DROP CONSTRAINT IF EXISTS "forecast_project_staffing_snapshot_rows_fk0";

ALTER TABLE "financial"."forecast_project_staffing_attribution_rules" DROP CONSTRAINT IF EXISTS "forecast_project_staffing_attribution_rules_fk0";

ALTER TABLE "financial"."forecast_project_staffing_assumptions" DROP CONSTRAINT IF EXISTS "forecast_project_staffing_assumptions_fk0";

ALTER TABLE "financial"."forecast_project_staffing_absence_overrides" DROP CONSTRAINT IF EXISTS "forecast_project_staffing_absence_overrides_fk0";

ALTER TABLE "financial"."forecast_project_maturity_snapshots" DROP CONSTRAINT IF EXISTS "forecast_project_maturity_snapshots_fk0";

ALTER TABLE "financial"."forecast_outputs" DROP CONSTRAINT IF EXISTS "forecast_outputs_fk0";

ALTER TABLE "financial"."forecast_output_staffing" DROP CONSTRAINT IF EXISTS "forecast_output_staffing_fk0";

ALTER TABLE "financial"."forecast_output_schedule_phasing" DROP CONSTRAINT IF EXISTS "forecast_output_schedule_phasing_fk0";

ALTER TABLE "financial"."forecast_output_risks" DROP CONSTRAINT IF EXISTS "forecast_output_risks_fk0";

ALTER TABLE "financial"."forecast_output_probability" DROP CONSTRAINT IF EXISTS "forecast_output_probability_fk0";

ALTER TABLE "financial"."forecast_output_narratives" DROP CONSTRAINT IF EXISTS "forecast_output_narratives_fk0";

ALTER TABLE "financial"."forecast_output_monthly_table_totals" DROP CONSTRAINT IF EXISTS "forecast_output_monthly_table_totals_fk0";

ALTER TABLE "financial"."forecast_output_monthly_table_rows" DROP CONSTRAINT IF EXISTS "forecast_output_monthly_table_rows_fk0";

ALTER TABLE "financial"."forecast_output_monthly" DROP CONSTRAINT IF EXISTS "forecast_output_monthly_fk0";

ALTER TABLE "financial"."forecast_output_commitment_exposure" DROP CONSTRAINT IF EXISTS "forecast_output_commitment_exposure_fk0";

ALTER TABLE "financial"."forecast_output_changes" DROP CONSTRAINT IF EXISTS "forecast_output_changes_fk0";

ALTER TABLE "financial"."forecast_output_budget_codes" DROP CONSTRAINT IF EXISTS "forecast_output_budget_codes_fk0";

ALTER TABLE "financial"."forecast_operator_assumptions" DROP CONSTRAINT IF EXISTS "forecast_operator_assumptions_fk0";

ALTER TABLE "financial"."forecast_model_selection_decisions" DROP CONSTRAINT IF EXISTS "forecast_model_selection_decisions_fk0";

ALTER TABLE "financial"."forecast_method_eligibility" DROP CONSTRAINT IF EXISTS "forecast_method_eligibility_fk0";

ALTER TABLE "financial"."forecast_external_forecast_rows" DROP CONSTRAINT IF EXISTS "forecast_external_forecast_rows_fk0";

ALTER TABLE "financial"."forecast_external_forecast_mappings" DROP CONSTRAINT IF EXISTS "forecast_external_forecast_mappings_fk0";

ALTER TABLE "financial"."forecast_evidence_packages" DROP CONSTRAINT IF EXISTS "forecast_evidence_packages_fk0";

ALTER TABLE "financial"."forecast_data_availability_profiles" DROP CONSTRAINT IF EXISTS "forecast_data_availability_profiles_fk0";

ALTER TABLE "financial"."forecast_config_snapshot_items" DROP CONSTRAINT IF EXISTS "forecast_config_snapshot_items_fk1";

ALTER TABLE "financial"."forecast_config_snapshot_items" DROP CONSTRAINT IF EXISTS "forecast_config_snapshot_items_fk0";

ALTER TABLE "financial"."forecast_config_items" DROP CONSTRAINT IF EXISTS "forecast_config_items_fk0";

ALTER TABLE "financial"."forecast_confidence_scorecards" DROP CONSTRAINT IF EXISTS "forecast_confidence_scorecards_fk1";

ALTER TABLE "financial"."forecast_confidence_scorecards" DROP CONSTRAINT IF EXISTS "forecast_confidence_scorecards_fk0";

ALTER TABLE "financial"."forecast_confidence_factors" DROP CONSTRAINT IF EXISTS "forecast_confidence_factors_fk0";

ALTER TABLE "financial"."forecast_comparison_results" DROP CONSTRAINT IF EXISTS "forecast_comparison_results_fk0";

ALTER TABLE "financial"."forecast_calibration_weights" DROP CONSTRAINT IF EXISTS "forecast_calibration_weights_fk0";

ALTER TABLE "financial"."forecast_anomaly_findings" DROP CONSTRAINT IF EXISTS "forecast_anomaly_findings_fk0";

ALTER TABLE "financial"."forecast_accuracy_results" DROP CONSTRAINT IF EXISTS "forecast_accuracy_results_fk0";

ALTER TABLE "core"."follow_up_status_events" DROP CONSTRAINT IF EXISTS "follow_up_status_events_fk0";

ALTER TABLE "core"."files" DROP CONSTRAINT IF EXISTS "files_fk0";

ALTER TABLE "email"."email_sync_state" DROP CONSTRAINT IF EXISTS "email_sync_state_fk0";

ALTER TABLE "email"."email_review_queue" DROP CONSTRAINT IF EXISTS "email_review_queue_fk0";

ALTER TABLE "email"."email_relationship_candidates" DROP CONSTRAINT IF EXISTS "email_relationship_candidates_fk0";

ALTER TABLE "email"."email_project_matches" DROP CONSTRAINT IF EXISTS "email_project_matches_fk0";

ALTER TABLE "email"."email_model_classifications" DROP CONSTRAINT IF EXISTS "email_model_classifications_fk0";

ALTER TABLE "email"."email_messages" DROP CONSTRAINT IF EXISTS "email_messages_fk0";

ALTER TABLE "email"."email_message_recipients" DROP CONSTRAINT IF EXISTS "email_message_recipients_fk0";

ALTER TABLE "email"."email_message_body_vault_refs" DROP CONSTRAINT IF EXISTS "email_message_body_vault_refs_fk0";

ALTER TABLE "email"."email_message_attachments" DROP CONSTRAINT IF EXISTS "email_message_attachments_fk0";

ALTER TABLE "email"."email_crawl_runs" DROP CONSTRAINT IF EXISTS "email_crawl_runs_fk0";

ALTER TABLE "core"."daily_brief_source_refs" DROP CONSTRAINT IF EXISTS "daily_brief_source_refs_fk0";

ALTER TABLE "core"."daily_brief_open_receipts" DROP CONSTRAINT IF EXISTS "daily_brief_open_receipts_fk0";

ALTER TABLE "core"."daily_brief_notification_receipts" DROP CONSTRAINT IF EXISTS "daily_brief_notification_receipts_fk0";

ALTER TABLE "core"."daily_brief_html_render_receipts" DROP CONSTRAINT IF EXISTS "daily_brief_html_render_receipts_fk0";

ALTER TABLE "core"."daily_brief_handoff_lines" DROP CONSTRAINT IF EXISTS "daily_brief_handoff_lines_fk0";

ALTER TABLE "core"."daily_brief_delivery_receipts" DROP CONSTRAINT IF EXISTS "daily_brief_delivery_receipts_fk0";

ALTER TABLE "core"."cross_source_relationships" DROP CONSTRAINT IF EXISTS "cross_source_relationships_fk0";

ALTER TABLE "core"."content_embeddings" DROP CONSTRAINT IF EXISTS "content_embeddings_fk0";

ALTER TABLE "construction"."construction_source_sync_state" DROP CONSTRAINT IF EXISTS "construction_source_sync_state_fk0";

ALTER TABLE "construction"."construction_source_crawl_runs" DROP CONSTRAINT IF EXISTS "construction_source_crawl_runs_fk0";

ALTER TABLE "construction"."construction_project_source_matches" DROP CONSTRAINT IF EXISTS "construction_project_source_matches_fk1";

ALTER TABLE "construction"."construction_project_source_matches" DROP CONSTRAINT IF EXISTS "construction_project_source_matches_fk0";

ALTER TABLE "construction"."construction_project_keyword_registry" DROP CONSTRAINT IF EXISTS "construction_project_keyword_registry_fk0";

ALTER TABLE "construction"."construction_drive_items" DROP CONSTRAINT IF EXISTS "construction_drive_items_fk0";

ALTER TABLE "construction"."construction_document_relationship_candidates" DROP CONSTRAINT IF EXISTS "construction_document_relationship_candidates_fk0";

ALTER TABLE "construction"."construction_document_project_match_candidates" DROP CONSTRAINT IF EXISTS "construction_document_project_match_candidates_fk0";

ALTER TABLE "construction"."construction_document_intelligence_previews" DROP CONSTRAINT IF EXISTS "construction_document_intelligence_previews_fk0";

ALTER TABLE "construction"."construction_document_classification_candidates" DROP CONSTRAINT IF EXISTS "construction_document_classification_candidates_fk0";

ALTER TABLE "core"."claude_context_packet_items" DROP CONSTRAINT IF EXISTS "claude_context_packet_items_fk0";

ALTER TABLE "calendar"."calendar_sync_state" DROP CONSTRAINT IF EXISTS "calendar_sync_state_fk0";

ALTER TABLE "calendar"."calendar_project_match_candidates" DROP CONSTRAINT IF EXISTS "calendar_project_match_candidates_fk0";

ALTER TABLE "calendar"."calendar_event_index" DROP CONSTRAINT IF EXISTS "calendar_event_index_fk0";

ALTER TABLE "calendar"."calendar_event_attendees" DROP CONSTRAINT IF EXISTS "calendar_event_attendees_fk0";

ALTER TABLE "calendar"."calendar_crawl_runs" DROP CONSTRAINT IF EXISTS "calendar_crawl_runs_fk0";

ALTER TABLE "core"."attachments" DROP CONSTRAINT IF EXISTS "attachments_fk1";

ALTER TABLE "core"."attachments" DROP CONSTRAINT IF EXISTS "attachments_fk0";

ALTER TABLE "core"."ai_job_runs" DROP CONSTRAINT IF EXISTS "ai_job_runs_fk0";

ALTER TABLE "core"."accepted_tasks" DROP CONSTRAINT IF EXISTS "accepted_tasks_fk0";

ALTER TABLE "core"."accepted_commitments" DROP CONSTRAINT IF EXISTS "accepted_commitments_fk0";
