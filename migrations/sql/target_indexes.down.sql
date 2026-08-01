DROP INDEX IF EXISTS "core"."task_candidates_uq2";

DROP INDEX IF EXISTS "core"."ix_task_candidates_review_status";

DROP INDEX IF EXISTS "core"."ix_task_candidates_snoozed_until";

DROP INDEX IF EXISTS "core"."sync_state_uq1";

DROP INDEX IF EXISTS "financial"."staffing_holiday_calendars_uq2";

DROP INDEX IF EXISTS "financial"."staffing_holiday_calendar_dates_uq2";

DROP INDEX IF EXISTS "financial"."idx_staffing_holiday_calendar_dates_calendar_year";

DROP INDEX IF EXISTS "core"."source_system_record_map_uq2";

DROP INDEX IF EXISTS "core"."ix_source_record_map_project_system";

DROP INDEX IF EXISTS "core"."ix_source_record_map_source_key";

DROP INDEX IF EXISTS "core"."ix_source_record_map_type_status";

DROP INDEX IF EXISTS "core"."idx_source_structure_roots_rank";

DROP INDEX IF EXISTS "core"."source_structure_overrides_uq2";

DROP INDEX IF EXISTS "core"."idx_source_structure_overrides_active";

DROP INDEX IF EXISTS "core"."source_structure_folders_uq2";

DROP INDEX IF EXISTS "core"."idx_source_structure_folders_root_depth";

DROP INDEX IF EXISTS "core"."idx_source_structure_folders_parent";

DROP INDEX IF EXISTS "core"."idx_source_structure_folders_class";

DROP INDEX IF EXISTS "core"."idx_source_structure_folders_doc_family";

DROP INDEX IF EXISTS "core"."idx_source_structure_folders_project";

DROP INDEX IF EXISTS "core"."idx_source_structure_folders_rank";

DROP INDEX IF EXISTS "core"."idx_source_structure_folders_flags";

DROP INDEX IF EXISTS "core"."idx_source_structure_entity_folders_folder";

DROP INDEX IF EXISTS "core"."source_structure_entities_uq2";

DROP INDEX IF EXISTS "core"."idx_source_structure_entities_project";

DROP INDEX IF EXISTS "core"."source_records_uq1";

DROP INDEX IF EXISTS "core"."ix_source_record_summary_project_system";

DROP INDEX IF EXISTS "core"."idx_si_summaries_source";

DROP INDEX IF EXISTS "core"."idx_si_sources_domain";

DROP INDEX IF EXISTS "core"."idx_si_sources_project";

DROP INDEX IF EXISTS "core"."idx_si_sources_active";

DROP INDEX IF EXISTS "core"."idx_si_sources_root";

DROP INDEX IF EXISTS "core"."idx_si_sources_renamed_from";

DROP INDEX IF EXISTS "core"."source_intelligence_relationships_uq2";

DROP INDEX IF EXISTS "core"."idx_si_rel_src";

DROP INDEX IF EXISTS "core"."idx_si_rel_dst";

DROP INDEX IF EXISTS "core"."idx_si_metadata_sha";

DROP INDEX IF EXISTS "core"."idx_si_metadata_fts_rowid";

DROP INDEX IF EXISTS "core"."source_intelligence_generated_notes_uq2";

DROP INDEX IF EXISTS "core"."idx_si_gennotes_source";

DROP INDEX IF EXISTS "core"."idx_si_gennotes_status";

DROP INDEX IF EXISTS "core"."idx_si_events_status";

DROP INDEX IF EXISTS "core"."idx_si_events_source";

DROP INDEX IF EXISTS "core"."idx_si_events_entity";

DROP INDEX IF EXISTS "core"."source_intelligence_chunks_uq2";

DROP INDEX IF EXISTS "core"."idx_si_chunks_source";

DROP INDEX IF EXISTS "core"."idx_source_index_scan_quarantine_active";

DROP INDEX IF EXISTS "core"."idx_source_index_scan_quarantine_root_state";

DROP INDEX IF EXISTS "core"."idx_si_scan_quarantine_entity";

DROP INDEX IF EXISTS "core"."idx_source_index_scan_generations_active";

DROP INDEX IF EXISTS "core"."idx_source_index_scan_generations_root";

DROP INDEX IF EXISTS "core"."idx_source_index_scan_generations_status";

DROP INDEX IF EXISTS "core"."idx_source_index_reconciliation_runs_root";

DROP INDEX IF EXISTS "core"."idx_locators_current_per_entity";

DROP INDEX IF EXISTS "core"."idx_locators_active_path";

DROP INDEX IF EXISTS "core"."idx_locators_source_id";

DROP INDEX IF EXISTS "core"."idx_source_index_bootstrap_state_ready";

DROP INDEX IF EXISTS "core"."idx_source_index_bootstrap_runs_active";

DROP INDEX IF EXISTS "core"."idx_source_index_bootstrap_runs_root";

DROP INDEX IF EXISTS "core"."idx_source_index_bootstrap_runs_status";

DROP INDEX IF EXISTS "core"."ix_source_evidence_trails_project";

DROP INDEX IF EXISTS "core"."ix_second_brain_retrieval_vector_index_runs_project_key";

DROP INDEX IF EXISTS "core"."ix_second_brain_retrieval_vector_index_items_run_id";

DROP INDEX IF EXISTS "core"."ix_second_brain_research_packets_project";

DROP INDEX IF EXISTS "financial"."second_brain_financial_readiness_agent_runs_uq1";

DROP INDEX IF EXISTS "financial"."second_brain_financial_forecast_readiness_runs_uq1";

DROP INDEX IF EXISTS "financial"."second_brain_financial_fact_normalization_runs_uq1";

DROP INDEX IF EXISTS "core"."ix_second_brain_evaluation_runs_target";

DROP INDEX IF EXISTS "core"."ix_agent_run_receipts_agent";

DROP INDEX IF EXISTS "core"."ix_agent_model_receipts_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_version_identity_matches_identity";

DROP INDEX IF EXISTS "schedule"."idx_schedule_version_identity_matches_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_version_identity_matches_import";

DROP INDEX IF EXISTS "schedule"."idx_schedule_version_identity_matches_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diffs_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_diff";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_type";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_identity_safe";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_attention";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_impact_level";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_wbs";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_impact_rollups_activity";

DROP INDEX IF EXISTS "schedule"."idx_schedule_version_diff_facts_to_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_detail_diff";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_detail_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_detail_domain_type";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_detail_activity";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_detail_severity";

DROP INDEX IF EXISTS "schedule"."idx_schedule_diff_detail_requires_attention";

DROP INDEX IF EXISTS "schedule"."idx_schedule_capabilities_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_capabilities_package";

DROP INDEX IF EXISTS "schedule"."idx_sq_scorecards_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_quality_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_quality_run";

DROP INDEX IF EXISTS "schedule"."schedule_quality_evaluation_runs_uq2";

DROP INDEX IF EXISTS "schedule"."idx_sq_runs_version";

DROP INDEX IF EXISTS "schedule"."idx_sq_runs_status";

DROP INDEX IF EXISTS "schedule"."idx_sq_runs_latest";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_field_lineage_package";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_field_lineage_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_field_lineage_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_field_lineage_family";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_equivalence_package";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_equivalence_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_equivalence_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_package_equivalence_candidate";

DROP INDEX IF EXISTS "schedule"."idx_schedule_import_packages_import";

DROP INDEX IF EXISTS "schedule"."idx_schedule_import_packages_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_import_package_files_package";

DROP INDEX IF EXISTS "schedule"."idx_schedule_identity_manual_actions_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_identity_manual_actions_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_identity_manual_actions_source";

DROP INDEX IF EXISTS "schedule"."idx_schedule_identity_manual_actions_target";

DROP INDEX IF EXISTS "schedule"."idx_schedule_identities_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_identities_latest_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_identities_source_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_file_imports_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_file_imports_status";

DROP INDEX IF EXISTS "schedule"."idx_schedule_file_imports_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_runs_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_runs_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_relationship_results_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_relationship_results_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_paths_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_paths_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_path_activities_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_path_activities_path";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_import_obs_import";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_import_obs_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_diagnostics_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_diagnostics_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_diagnostics_activity";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_activity_results_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_cpm_activity_results_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_weighting_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_mapping_runs_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_mapping_runs_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_candidates_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_distributions_run";

DROP INDEX IF EXISTS "schedule"."idx_schedule_baseline_relationships_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_baseline_projects_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_baseline_health_facts_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_baseline_crosswalk_version";

DROP INDEX IF EXISTS "schedule"."idx_schedule_baseline_activities_project";

DROP INDEX IF EXISTS "schedule"."idx_schedule_baseline_activities_version";

DROP INDEX IF EXISTS "core"."ix_retrieval_query_receipts_project";

DROP INDEX IF EXISTS "core"."ix_relationship_resolution_status_confidence";

DROP INDEX IF EXISTS "core"."ix_relationship_resolution_from";

DROP INDEX IF EXISTS "core"."ix_relationship_resolution_to";

DROP INDEX IF EXISTS "core"."ix_relationship_quality_project_status";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_runs_window";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_runs_policy";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_runs_mode";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_runs_created";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_items_run";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_items_ranking_run";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_items_candidate";

DROP INDEX IF EXISTS "core"."ix_ranking_policy_eval_items_family";

DROP INDEX IF EXISTS "core"."ix_query_tool_receipts_tool";

DROP INDEX IF EXISTS "core"."ix_project_source_coverage_project_domain";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_series_membership_version";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_series_membership_project_status";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_review_items_version_key";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_review_items_project_status";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_review_items_stable_key";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_review_item_events_item";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_review_item_events_project";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_named_baseline_active_slot";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_named_baseline_project";

DROP INDEX IF EXISTS "schedule"."idx_ps_named_baseline_review_identity";

DROP INDEX IF EXISTS "schedule"."idx_ps_named_baseline_review_project_scope";

DROP INDEX IF EXISTS "schedule"."idx_ps_named_baseline_review_events_item";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_baseline_active";

DROP INDEX IF EXISTS "schedule"."idx_project_schedule_baseline_project";

DROP INDEX IF EXISTS "core"."ix_project_risk_digest_items_project";

DROP INDEX IF EXISTS "core"."ix_project_issue_history_items_project";

DROP INDEX IF EXISTS "procore"."procore_text_intelligence_uq2";

DROP INDEX IF EXISTS "procore"."procore_synced_entities_uq1";

DROP INDEX IF EXISTS "procore"."idx_procore_synced_entities_project_endpoint";

DROP INDEX IF EXISTS "procore"."ix_procore_timeline_project_time";

DROP INDEX IF EXISTS "procore"."ix_procore_timeline_record_time";

DROP INDEX IF EXISTS "procore"."ix_procore_record_edges_from";

DROP INDEX IF EXISTS "procore"."ix_procore_record_edges_to_record";

DROP INDEX IF EXISTS "procore"."ix_procore_record_edges_to_entity";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_submittal_packages_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_submittal_packages_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_submittal_packages_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_submittal_packages_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_submittal_packages_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_status_dimensions_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_status_dimensions_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_status_dimensions_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_status_dimensions_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_status_dimensions_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfq_responses_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfq_responses_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfq_responses_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfq_responses_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfq_responses_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfi_responses_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfi_responses_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfi_responses_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfi_responses_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_rfi_responses_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_project_dimensions_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_project_dimensions_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_project_dimensions_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_project_dimensions_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_project_dimensions_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_topics_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_topics_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_topics_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_topics_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_topics_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_details_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_details_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_details_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_details_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_meeting_details_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoices_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoices_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoices_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoices_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoices_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoice_items_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoice_items_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoice_items_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoice_items_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_invoice_items_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_date_dimensions_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_date_dimensions_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_date_dimensions_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_date_dimensions_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_date_dimensions_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_daily_logs_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_daily_logs_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_daily_logs_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_daily_logs_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_daily_logs_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_cost_code_dimensions_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_cost_code_dimensions_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_cost_code_dimensions_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_cost_code_dimensions_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_cost_code_dimensions_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contracts_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contracts_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contracts_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contracts_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contracts_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contract_line_items_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contract_line_items_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contract_line_items_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contract_line_items_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_contract_line_items_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_orders_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_orders_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_orders_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_orders_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_orders_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_order_line_items_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_order_line_items_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_order_line_items_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_order_line_items_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_order_line_items_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_event_comments_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_event_comments_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_event_comments_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_event_comments_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_change_event_comments_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_rows_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_rows_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_rows_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_rows_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_rows_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_columns_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_columns_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_columns_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_columns_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_columns_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_changes_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_changes_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_changes_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_changes_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_budget_changes_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_attachments_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_attachments_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_attachments_project_date";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_attachments_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_raw_attachments_raw_payload";

DROP INDEX IF EXISTS "procore"."ix_procore_live_sync_runs_endpoint";

DROP INDEX IF EXISTS "procore"."ix_procore_live_records_review";

DROP INDEX IF EXISTS "procore"."ix_procore_live_records_endpoint";

DROP INDEX IF EXISTS "procore"."ix_procore_state_index_project_endpoint";

DROP INDEX IF EXISTS "procore"."procore_live_record_snapshots_uq2";

DROP INDEX IF EXISTS "procore"."ix_procore_snapshots_record_observed";

DROP INDEX IF EXISTS "procore"."ix_procore_snapshots_project_endpoint";

DROP INDEX IF EXISTS "procore"."ix_procore_change_events_record_detected";

DROP INDEX IF EXISTS "procore"."ix_procore_change_events_project_detected";

DROP INDEX IF EXISTS "procore"."ix_procore_change_events_category";

DROP INDEX IF EXISTS "procore"."procore_inspection_sections_uq2";

DROP INDEX IF EXISTS "procore"."procore_inspection_response_sets_uq2";

DROP INDEX IF EXISTS "procore"."procore_inspection_response_options_uq2";

DROP INDEX IF EXISTS "procore"."procore_inspection_records_uq2";

DROP INDEX IF EXISTS "procore"."procore_inspection_items_uq2";

DROP INDEX IF EXISTS "procore"."ix_procore_inspection_items_project_status";

DROP INDEX IF EXISTS "procore"."procore_inspection_evidence_rules_uq2";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_subcontractor_invoices_project_filters";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_line_items_parent";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_contracts_project_family";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_compliance_documents_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_change_orders_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_change_order_line_items_parent";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_budget_changes_project_kind";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_billing_periods_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_financial_amount_facts_project_name";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_ball_in_court_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_ball_in_court_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_ball_in_court_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_approvers_attachments_primary_ac5e3ec";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_approvers_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_approvers_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_approvers_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_approvers_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_approvers_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_submittals_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoices_attachments_prima_37a00db";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoices_attachments_raw_p_b9368f3";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoices_attachments_paren_e0b2dec";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoices_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoices_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoices_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoices_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_contract_detail_it_acc842d";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_contract_detail_it_0a0af3c";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_contract_detail_it_cd0e023";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_contract_detail_it_d322e8c";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_change_order_items_f1d3989";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_change_order_items_3b51140";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_change_order_items_dc7ddd8";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_subcontractor_invoice_change_order_items_ba99627";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_schedules_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_schedules_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_schedules_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_schedules_record_id";

DROP INDEX IF EXISTS "procore"."idx_schedule_wbs_version";

DROP INDEX IF EXISTS "procore"."idx_schedule_udfs_version";

DROP INDEX IF EXISTS "procore"."idx_schedule_relationships_version";

DROP INDEX IF EXISTS "procore"."idx_schedule_calendars_version";

DROP INDEX IF EXISTS "procore"."idx_schedule_codes_version";

DROP INDEX IF EXISTS "procore"."idx_schedule_codes_activity";

DROP INDEX IF EXISTS "procore"."procore_ep_schedule_activities_uq1";

DROP INDEX IF EXISTS "procore"."idx_schedule_activities_project";

DROP INDEX IF EXISTS "procore"."idx_schedule_activities_version";

DROP INDEX IF EXISTS "procore"."idx_schedule_activities_import";

DROP INDEX IF EXISTS "procore"."idx_schedule_activities_schedule";

DROP INDEX IF EXISTS "procore"."idx_schedule_activities_cost_code";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_change_event_line_item_055fdc3";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_change_event_line_item_68d96c8";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_change_event_line_item_6e3f805";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_change_event_line_item_21ece0e";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_change_event_line_item_e623ad0";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_change_event_line_item_f53ca3b";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_attachments_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_change_event_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_attachments_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfqs_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_questions_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_questions_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_questions_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_ball_in_courts_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_ball_in_courts_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_ball_in_courts_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_assignees_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_assignees_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_assignees_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_rfis_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_line_items_cost_code_line_6ef28e2";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_line_items_cost_code_line_56bfd7a";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_line_items_cost_code_line_c9eeee0";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_line_items_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_line_items_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_line_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_line_items_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_contracts_custom_fields_c_3644ca7";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_contracts_custom_fields_c_897f908";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_contracts_custom_fields_c_508be90";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_contracts_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_contracts_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_contracts_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_purchase_order_contracts_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_ball_in_court_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_ball_in_court_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_ball_in_court_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_assignments_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_assignments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_assignments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_assignees_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_assignees_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_assignees_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_punch_items_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1633_deabdf9";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1633_90b3b65";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1633_584171d";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_91712c0";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_7fb176c";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_9af2209";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_0cb3c8d";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_5c2d01d";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_1f6fbe2";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_fcf3f7e";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_9e2509e";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_46ed438";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_3bed7dd";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_ce6f996";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_358a865";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_ad44f46";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_aad5c8e";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_custom_fields_custom_field_1632_6bec471";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_projects_project_key_unique";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contracts_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contracts_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contracts_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contracts_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contract_line_items_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contract_line_items_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contract_line_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_contract_line_items_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_orders_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_orders_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_orders_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_orders_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_order_line_items_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_order_line_items_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_order_line_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_prime_change_order_line_items_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_observations_assignees_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_observations_assignees_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_observations_assignees_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_observations_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_observations_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_observations_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_observations_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_meetings_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_meetings_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_meetings_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_meetings_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_signature_requests_primary_r_ba62056";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_signature_requests_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_signature_requests_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_inspectors_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_inspectors_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_inspectors_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_distribution_members_primary_8d31201";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_distribution_members_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_distribution_members_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_attachments_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspections_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_sections_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_sections_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_sections_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_sections_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_items_response_set_responses__a4e2045";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_items_response_set_responses__c9ffb14";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_items_response_set_responses__2798bc2";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_items_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_items_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_inspection_items_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_weather_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_weather_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_weather_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_weather_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_visitor_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_visitor_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_visitor_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_visitor_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_notes_attachments_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_notes_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_notes_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_notes_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_notes_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_notes_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_notes_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_manpower_attachments_primary_r_9c82a38";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_manpower_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_manpower_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_manpower_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_manpower_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_manpower_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_manpower_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_inspections_attachments_primar_d95b5d8";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_inspections_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_inspections_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_inspections_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_inspections_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_inspections_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_inspections_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_deliveries_attachments_primary_32901d6";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_deliveries_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_deliveries_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_deliveries_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_deliveries_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_deliveries_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_deliveries_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_dcrs_attachments_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_dcrs_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_dcrs_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_dcrs_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_dcrs_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_dcrs_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_daily_log_dcrs_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_line_items_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_line_items_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_line_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_line_items_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_contracts_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_contracts_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_contracts_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_contracts_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_insurance_document_b18d0c9";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_insurance_document_f38c2e3";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_insurance_document_4499d53";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_insurance_document_fe21747";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_insurance_document_018ad0e";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_insurance_document_0b03f8c";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_compliance_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_change_orders_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_change_orders_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_change_orders_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_change_orders_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_attachments_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_attachments_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_commitment_attachments_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_markup_items_wbs_code_segm_586425d";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_markup_items_wbs_code_segm_87f6c74";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_markup_items_wbs_code_segm_43b59f6";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_markup_items_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_markup_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_markup_items_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_change_items_budget_code_s_6703e5b";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_change_items_budget_code_s_fecc078";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_change_items_budget_code_s_d374f10";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_change_items_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_change_items_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_change_items_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_attachments_primary_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_attachments_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_attachments_parent_item_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_change_events_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_views_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_views_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_views_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_views_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_modifications_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_modifications_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_modifications_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_modifications_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_parent_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_budget_view_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_wbs_flat_code";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_canonical_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_cost_code_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_rows_current_quality";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_row_cells_record_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_row_cells_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_row_cells_budget_view_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_row_cells_column_name";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_row_cells_field_path";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_row_cells_current_quality";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_parent_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_budget_view_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_name";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_field_path";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_detail_columns_current_quality";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_change_history_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_change_history_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_change_history_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_budget_change_history_record_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_billing_periods_project_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_billing_periods_endpoint_key";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_billing_periods_raw_payload_id";

DROP INDEX IF EXISTS "procore"."idx_procore_ep_billing_periods_record_id";

DROP INDEX IF EXISTS "procore"."procore_endpoint_raw_payloads_uq2";

DROP INDEX IF EXISTS "procore"."ix_procore_endpoint_raw_payloads_endpoint_project";

DROP INDEX IF EXISTS "procore"."ix_procore_endpoint_raw_payloads_source_ref";

DROP INDEX IF EXISTS "procore"."ix_procore_endpoint_raw_payloads_current";

DROP INDEX IF EXISTS "procore"."ix_procore_endpoint_capture_runs_status";

DROP INDEX IF EXISTS "procore"."ix_procore_endpoint_capture_pages_run";

DROP INDEX IF EXISTS "procore"."procore_custom_field_values_uq2";

DROP INDEX IF EXISTS "procore"."ix_procore_attachment_refs_source";

DROP INDEX IF EXISTS "procore"."ix_procore_action_signals_project_status";

DROP INDEX IF EXISTS "procore"."ix_procore_action_signals_type";

DROP INDEX IF EXISTS "core"."parser_outputs_uq1";

DROP INDEX IF EXISTS "core"."idx_pa_promotion_receipts_bundle";

DROP INDEX IF EXISTS "core"."idx_pa_validation_receipts_bundle";

DROP INDEX IF EXISTS "core"."obsidian_note_index_uq2";

DROP INDEX IF EXISTS "core"."obsidian_managed_section_registry_uq2";

DROP INDEX IF EXISTS "core"."obsidian_index_entries_uq2";

DROP INDEX IF EXISTS "core"."ix_obsidian_index_entries_project";

DROP INDEX IF EXISTS "core"."ix_obsidian_index_entries_hash";

DROP INDEX IF EXISTS "core"."ix_model_profile_eval_results_window";

DROP INDEX IF EXISTS "core"."ix_model_profile_eval_results_profile";

DROP INDEX IF EXISTS "core"."ix_model_profile_eval_results_created";

DROP INDEX IF EXISTS "core"."ix_memory_update_reviews_candidate";

DROP INDEX IF EXISTS "core"."ix_memory_update_candidates_review";

DROP INDEX IF EXISTS "core"."ix_meeting_prep_brief_sections_run";

DROP INDEX IF EXISTS "core"."ix_meeting_prep_brief_runs_project";

DROP INDEX IF EXISTS "core"."ix_meeting_email_candidates_project_event";

DROP INDEX IF EXISTS "core"."ix_meeting_email_candidates_review";

DROP INDEX IF EXISTS "core"."ix_long_term_memory_source_refs_memory";

DROP INDEX IF EXISTS "core"."ix_long_term_memory_quality_signals_memory";

DROP INDEX IF EXISTS "core"."ix_long_term_memory_items_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_validation_events_project";

DROP INDEX IF EXISTS "financial"."forecast_staffing_templates_uq2";

DROP INDEX IF EXISTS "financial"."forecast_staffing_template_versions_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_staffing_template_versions_template";

DROP INDEX IF EXISTS "financial"."idx_forecast_staffing_cost_codes_project";

DROP INDEX IF EXISTS "financial"."forecast_source_ingestions_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_source_ingestions_project_kind";

DROP INDEX IF EXISTS "financial"."idx_forecast_source_ingestions_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_runs_project_created";

DROP INDEX IF EXISTS "financial"."idx_forecast_run_model_versions_model";

DROP INDEX IF EXISTS "financial"."idx_forecast_run_model_versions_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_review_items_forecast";

DROP INDEX IF EXISTS "financial"."idx_forecast_review_items_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_review_items_status";

DROP INDEX IF EXISTS "financial"."forecast_required_assumptions_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_required_assumptions_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_required_assumptions_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_snapshots_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_snapshots_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_snapshot_rows_snapshot";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_config_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_config_cost_code";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_config_person";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_config_template";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_attribution_rules_lookup";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_review_items_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_staffing_absence_project";

DROP INDEX IF EXISTS "financial"."forecast_project_maturity_snapshots_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_maturity_snapshots_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_project_maturity_snapshots_project";

DROP INDEX IF EXISTS "financial"."forecast_package_manifests_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_package_manifests_project_type";

DROP INDEX IF EXISTS "financial"."idx_forecast_package_manifests_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_outputs_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_outputs_run";

DROP INDEX IF EXISTS "financial"."forecast_output_staffing_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_staffing_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_staffing_project";

DROP INDEX IF EXISTS "financial"."forecast_output_schedule_phasing_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_schedule_phasing_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_schedule_phasing_project";

DROP INDEX IF EXISTS "financial"."forecast_output_risks_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_risks_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_risks_project";

DROP INDEX IF EXISTS "financial"."forecast_output_probability_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_probability_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_probability_project";

DROP INDEX IF EXISTS "financial"."forecast_output_narratives_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_narratives_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_narratives_project";

DROP INDEX IF EXISTS "financial"."forecast_output_monthly_table_totals_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_table_totals_output";

DROP INDEX IF EXISTS "financial"."forecast_output_monthly_table_rows_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_table_rows_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_table_rows_output_cost_type";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_table_rows_output_cost_code";

DROP INDEX IF EXISTS "financial"."forecast_output_monthly_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_output_code";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_output_month";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_monthly_output_value_type";

DROP INDEX IF EXISTS "financial"."forecast_output_commitment_exposure_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_commitment_exposure_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_commitment_exposure_project";

DROP INDEX IF EXISTS "financial"."forecast_output_changes_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_changes_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_changes_project";

DROP INDEX IF EXISTS "financial"."forecast_output_budget_codes_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_budget_codes_output";

DROP INDEX IF EXISTS "financial"."idx_forecast_output_budget_codes_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_operator_assumptions_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_operator_assumptions_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_monthly_actuals_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_monthly_actuals_code";

DROP INDEX IF EXISTS "financial"."idx_forecast_monthly_actuals_package";

DROP INDEX IF EXISTS "financial"."idx_forecast_monthly_actuals_month";

DROP INDEX IF EXISTS "financial"."forecast_model_versions_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_model_versions_label";

DROP INDEX IF EXISTS "financial"."idx_forecast_model_versions_sha";

DROP INDEX IF EXISTS "financial"."forecast_model_selection_decisions_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_model_selection_decisions_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_model_selection_decisions_project";

DROP INDEX IF EXISTS "financial"."forecast_method_eligibility_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_method_eligibility_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_method_eligibility_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_generation_requests_project_created";

DROP INDEX IF EXISTS "financial"."forecast_external_forecasts_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_forecasts_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_forecasts_period";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_forecasts_source";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_rows_forecast";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_rows_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_rows_code";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_mappings_forecast";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_mappings_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_external_mappings_status";

DROP INDEX IF EXISTS "financial"."forecast_evidence_packages_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_evidence_packages_forecast";

DROP INDEX IF EXISTS "financial"."idx_forecast_evidence_packages_project";

DROP INDEX IF EXISTS "financial"."forecast_data_availability_profiles_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_data_availability_profiles_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_data_availability_profiles_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_cost_entry_staffing_actuals_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_cost_entry_staffing_actuals_person";

DROP INDEX IF EXISTS "financial"."forecast_cost_entries_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_cost_entries_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_cost_entries_code";

DROP INDEX IF EXISTS "financial"."idx_forecast_cost_entries_package";

DROP INDEX IF EXISTS "financial"."forecast_config_sources_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_sources_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_sources_domain";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_sources_name";

DROP INDEX IF EXISTS "financial"."forecast_config_snapshots_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_snapshots_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_snapshots_name";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_snapshot_items_snapshot";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_snapshot_items_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_snapshot_items_domain";

DROP INDEX IF EXISTS "financial"."forecast_config_items_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_items_source";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_items_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_items_domain";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_items_name";

DROP INDEX IF EXISTS "financial"."idx_forecast_config_items_status";

DROP INDEX IF EXISTS "financial"."forecast_confidence_scorecards_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_confidence_scorecards_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_confidence_scorecards_project";

DROP INDEX IF EXISTS "financial"."forecast_confidence_factors_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_confidence_factors_scorecard";

DROP INDEX IF EXISTS "financial"."idx_forecast_confidence_factors_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_comparison_results_forecast";

DROP INDEX IF EXISTS "financial"."idx_forecast_comparison_results_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_comparison_results_code";

DROP INDEX IF EXISTS "financial"."idx_forecast_comparison_results_baseline";

DROP INDEX IF EXISTS "financial"."forecast_calibration_weights_uq2";

DROP INDEX IF EXISTS "financial"."idx_forecast_calibration_weights_run";

DROP INDEX IF EXISTS "financial"."idx_forecast_calibration_weights_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_budget_details_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_budget_details_code";

DROP INDEX IF EXISTS "financial"."idx_forecast_budget_details_package";

DROP INDEX IF EXISTS "financial"."idx_forecast_anomaly_findings_forecast";

DROP INDEX IF EXISTS "financial"."idx_forecast_anomaly_findings_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_anomaly_findings_severity";

DROP INDEX IF EXISTS "financial"."idx_forecast_accuracy_results_forecast";

DROP INDEX IF EXISTS "financial"."idx_forecast_accuracy_results_project";

DROP INDEX IF EXISTS "financial"."idx_forecast_accuracy_results_baseline";

DROP INDEX IF EXISTS "core"."ix_follow_up_watch_items_status_check";

DROP INDEX IF EXISTS "email"."email_thread_raw_context_uq2";

DROP INDEX IF EXISTS "email"."ix_email_source_locations_owner";

DROP INDEX IF EXISTS "email"."ix_email_source_locations_role";

DROP INDEX IF EXISTS "email"."email_review_queue_uq2";

DROP INDEX IF EXISTS "email"."ix_email_review_queue_status";

DROP INDEX IF EXISTS "email"."ix_email_review_queue_project";

DROP INDEX IF EXISTS "email"."email_relationship_candidates_uq2";

DROP INDEX IF EXISTS "email"."idx_email_raw_thread_structured_raw_row_id";

DROP INDEX IF EXISTS "email"."idx_email_raw_thread_structured_project_key";

DROP INDEX IF EXISTS "email"."idx_email_raw_thread_structured_source_quality";

DROP INDEX IF EXISTS "email"."idx_email_raw_thread_messages_structured_parent_projection_id";

DROP INDEX IF EXISTS "email"."idx_email_raw_thread_messages_structured_raw_row_id";

DROP INDEX IF EXISTS "email"."idx_email_raw_message_structured_raw_row_id";

DROP INDEX IF EXISTS "email"."idx_email_raw_message_structured_project_key";

DROP INDEX IF EXISTS "email"."idx_email_raw_message_structured_source_quality";

DROP INDEX IF EXISTS "email"."idx_email_raw_message_recipients_structured_parent_proj_ad33491";

DROP INDEX IF EXISTS "email"."idx_email_raw_message_recipients_structured_raw_row_id";

DROP INDEX IF EXISTS "email"."idx_email_raw_message_attachments_structured_parent_pro_11a752e";

DROP INDEX IF EXISTS "email"."idx_email_raw_message_attachments_structured_raw_row_id";

DROP INDEX IF EXISTS "email"."email_project_matches_uq2";

DROP INDEX IF EXISTS "email"."ix_email_processing_receipts_run";

DROP INDEX IF EXISTS "email"."email_model_classifications_uq2";

DROP INDEX IF EXISTS "email"."ix_email_model_classifications_project";

DROP INDEX IF EXISTS "email"."ix_email_model_classifications_review";

DROP INDEX IF EXISTS "email"."ix_email_messages_thread";

DROP INDEX IF EXISTS "email"."ix_email_messages_project";

DROP INDEX IF EXISTS "email"."ix_email_messages_received";

DROP INDEX IF EXISTS "email"."ix_email_messages_review";

DROP INDEX IF EXISTS "email"."email_message_recipients_uq1";

DROP INDEX IF EXISTS "email"."idx_email_message_raw_content_conversation";

DROP INDEX IF EXISTS "email"."idx_email_message_raw_content_received";

DROP INDEX IF EXISTS "email"."ix_email_body_vault_refs_review";

DROP INDEX IF EXISTS "email"."email_followup_enrichments_uq2";

DROP INDEX IF EXISTS "email"."ix_email_followup_enrichments_candidate";

DROP INDEX IF EXISTS "email"."ix_email_followup_enrichments_watch_item";

DROP INDEX IF EXISTS "email"."ix_email_followup_enrichments_review_status";

DROP INDEX IF EXISTS "email"."ix_email_followup_enrichments_waiting_state";

DROP INDEX IF EXISTS "email"."ix_email_followup_enrichments_created_utc";

DROP INDEX IF EXISTS "core"."ix_data_quality_gate_results_run_status";

DROP INDEX IF EXISTS "core"."ix_daily_brief_runs_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_ranking_runs_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_ranking_runs_model_status";

DROP INDEX IF EXISTS "core"."ix_daily_brief_ranked_candidates_run";

DROP INDEX IF EXISTS "core"."ix_daily_brief_ranked_candidates_candidate";

DROP INDEX IF EXISTS "core"."ix_daily_brief_ranked_candidates_cluster";

DROP INDEX IF EXISTS "core"."ix_open_receipts_date";

DROP INDEX IF EXISTS "core"."ix_notification_receipts_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_item_outcome_events_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_item_outcome_events_candidate";

DROP INDEX IF EXISTS "core"."ix_daily_brief_item_outcome_events_type";

DROP INDEX IF EXISTS "core"."ix_daily_brief_item_outcome_events_created";

DROP INDEX IF EXISTS "core"."ix_html_render_receipts_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_handoff_lines_run";

DROP INDEX IF EXISTS "core"."ix_daily_brief_exposure_events_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_exposure_events_ranking";

DROP INDEX IF EXISTS "core"."ix_daily_brief_exposure_events_assembly";

DROP INDEX IF EXISTS "core"."ix_daily_brief_exposure_events_candidate";

DROP INDEX IF EXISTS "core"."ix_daily_brief_exposure_events_created";

DROP INDEX IF EXISTS "core"."ix_delivery_receipts_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_change_events_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_change_events_family";

DROP INDEX IF EXISTS "core"."ix_daily_brief_change_events_attention";

DROP INDEX IF EXISTS "core"."ix_daily_brief_change_events_created";

DROP INDEX IF EXISTS "core"."ix_daily_brief_change_event_refs_event";

DROP INDEX IF EXISTS "core"."ix_daily_brief_assembly_sections_run";

DROP INDEX IF EXISTS "core"."ix_daily_brief_assembly_runs_date";

DROP INDEX IF EXISTS "core"."ix_daily_brief_assembly_runs_ranking";

DROP INDEX IF EXISTS "core"."ix_daily_brief_assembly_runs_model_status";

DROP INDEX IF EXISTS "core"."ix_daily_brief_action_candidates_date_section";

DROP INDEX IF EXISTS "core"."cross_source_relationships_uq2";

DROP INDEX IF EXISTS "core"."ix_cross_source_relationships_project";

DROP INDEX IF EXISTS "core"."cross_source_relationship_candidates_uq2";

DROP INDEX IF EXISTS "core"."ix_cross_source_relationship_candidates_project";

DROP INDEX IF EXISTS "core"."ix_cross_source_relationship_candidates_source";

DROP INDEX IF EXISTS "core"."ix_cross_source_relationship_candidates_target";

DROP INDEX IF EXISTS "core"."ix_readiness_project";

DROP INDEX IF EXISTS "core"."content_embeddings_uq1";

DROP INDEX IF EXISTS "construction"."ix_construction_source_locations_project";

DROP INDEX IF EXISTS "construction"."construction_review_queue_uq1";

DROP INDEX IF EXISTS "construction"."ix_construction_review_queue_status";

DROP INDEX IF EXISTS "construction"."ix_construction_review_queue_source";

DROP INDEX IF EXISTS "construction"."construction_project_source_matches_uq1";

DROP INDEX IF EXISTS "construction"."ix_construction_project_source_matches_review";

DROP INDEX IF EXISTS "construction"."construction_project_keyword_registry_uq2";

DROP INDEX IF EXISTS "construction"."ix_project_keyword_registry_project_status";

DROP INDEX IF EXISTS "construction"."ix_project_keyword_registry_project_strength";

DROP INDEX IF EXISTS "construction"."ix_construction_model_decisions_status";

DROP INDEX IF EXISTS "construction"."ix_construction_model_decisions_item";

DROP INDEX IF EXISTS "construction"."ix_construction_graph_link_resolution_source";

DROP INDEX IF EXISTS "construction"."ix_construction_graph_download_receipts_item";

DROP INDEX IF EXISTS "construction"."construction_file_ingestion_decisions_uq2";

DROP INDEX IF EXISTS "construction"."ix_construction_file_ingestion_decisions_source";

DROP INDEX IF EXISTS "construction"."ix_construction_file_ingestion_decisions_review";

DROP INDEX IF EXISTS "construction"."ix_construction_file_extraction_runs_item";

DROP INDEX IF EXISTS "construction"."ix_construction_drive_items_project";

DROP INDEX IF EXISTS "construction"."ix_construction_drive_items_source_modified";

DROP INDEX IF EXISTS "construction"."ix_construction_drive_items_deleted";

DROP INDEX IF EXISTS "construction"."ix_construction_drive_items_project_key";

DROP INDEX IF EXISTS "construction"."ix_construction_drive_items_match_status";

DROP INDEX IF EXISTS "construction"."ix_construction_drive_items_review_required";

DROP INDEX IF EXISTS "construction"."ix_document_relationship_candidates_target";

DROP INDEX IF EXISTS "construction"."ux_document_cards_document_card_id";

DROP INDEX IF EXISTS "construction"."ix_document_cards_project_type";

DROP INDEX IF EXISTS "construction"."ix_document_cards_source";

DROP INDEX IF EXISTS "construction"."ix_document_cards_review";

DROP INDEX IF EXISTS "core"."commitment_candidates_uq2";

DROP INDEX IF EXISTS "core"."ix_commitment_candidates_review_status";

DROP INDEX IF EXISTS "core"."ix_commitment_candidates_snoozed_until";

DROP INDEX IF EXISTS "core"."ix_claude_context_packets_type_date";

DROP INDEX IF EXISTS "core"."candidate_suppression_rules_uq2";

DROP INDEX IF EXISTS "core"."ix_candidate_suppression_rules_scope";

DROP INDEX IF EXISTS "core"."ix_candidate_suppression_rules_group";

DROP INDEX IF EXISTS "core"."ix_candidate_suppression_rules_subject";

DROP INDEX IF EXISTS "core"."ix_candidate_suppression_rules_active";

DROP INDEX IF EXISTS "core"."ix_candidate_source_refs_candidate";

DROP INDEX IF EXISTS "core"."ix_candidate_similarity_edges_date";

DROP INDEX IF EXISTS "core"."ix_candidate_similarity_edges_a";

DROP INDEX IF EXISTS "core"."ix_candidate_similarity_edges_b";

DROP INDEX IF EXISTS "core"."ix_candidate_similarity_edges_cluster";

DROP INDEX IF EXISTS "core"."candidate_merge_links_uq2";

DROP INDEX IF EXISTS "core"."ix_candidate_merge_links_source";

DROP INDEX IF EXISTS "core"."ix_candidate_merge_links_target";

DROP INDEX IF EXISTS "core"."ix_candidate_merge_links_group";

DROP INDEX IF EXISTS "core"."candidate_lifecycle_events_uq2";

DROP INDEX IF EXISTS "core"."ix_candidate_lifecycle_events_subject";

DROP INDEX IF EXISTS "core"."ix_candidate_lifecycle_events_candidate";

DROP INDEX IF EXISTS "core"."ix_candidate_lifecycle_events_new_state";

DROP INDEX IF EXISTS "core"."ix_candidate_lifecycle_events_group";

DROP INDEX IF EXISTS "core"."ix_candidate_lifecycle_events_effective";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_structured_raw_row_id";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_structured_project_key";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_structured_source_quality";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_recurrence_structured_parent_pro_9a848f4";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_recurrence_structured_raw_row_id";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_locations_structured_parent_proj_04e048e";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_locations_structured_raw_row_id";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_attendees_structured_parent_proj_01dfdd5";

DROP INDEX IF EXISTS "calendar"."idx_calendar_raw_event_attendees_structured_raw_row_id";

DROP INDEX IF EXISTS "calendar"."ix_calendar_project_candidates_project";

DROP INDEX IF EXISTS "calendar"."idx_calendar_event_raw_content_start";

DROP INDEX IF EXISTS "calendar"."calendar_event_index_uq2";

DROP INDEX IF EXISTS "calendar"."ix_calendar_event_index_source_start";

DROP INDEX IF EXISTS "calendar"."ix_calendar_event_index_project_start";

DROP INDEX IF EXISTS "calendar"."ix_calendar_event_index_review";

DROP INDEX IF EXISTS "calendar"."calendar_event_attendees_uq1";

DROP INDEX IF EXISTS "core"."ix_brief_effectiveness_rollups_scope";

DROP INDEX IF EXISTS "core"."ix_brief_effectiveness_rollups_window";

DROP INDEX IF EXISTS "core"."ix_brief_effectiveness_rollups_created";

DROP INDEX IF EXISTS "core"."idx_assistant_review_events_item";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packets_type";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packets_projection";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packets_input";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packet_receipts_packet";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packet_items_packet";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packet_items_role";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packet_items_target";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packet_events_packet";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packet_citations_packet";

DROP INDEX IF EXISTS "core"."idx_assistant_research_packet_citations_item";

DROP INDEX IF EXISTS "core"."idx_assistant_quality_runs_target";

DROP INDEX IF EXISTS "core"."idx_assistant_quality_runs_lineage";

DROP INDEX IF EXISTS "core"."idx_assistant_quality_runs_request";

DROP INDEX IF EXISTS "core"."idx_assistant_quality_receipts_run";

DROP INDEX IF EXISTS "core"."idx_assistant_quality_events_run";

DROP INDEX IF EXISTS "core"."idx_assistant_output_file_receipts_output";

DROP INDEX IF EXISTS "core"."idx_assistant_memory_events_node";

DROP INDEX IF EXISTS "core"."idx_assistant_memory_compilations_node";

DROP INDEX IF EXISTS "core"."idx_assistant_memory_compilations_status";

DROP INDEX IF EXISTS "core"."idx_assistant_intelligence_projections_type";

DROP INDEX IF EXISTS "core"."idx_assistant_intelligence_projections_input";

DROP INDEX IF EXISTS "core"."idx_assistant_intelligence_projection_receipts_projection";

DROP INDEX IF EXISTS "core"."idx_assistant_intelligence_projection_items_projection";

DROP INDEX IF EXISTS "core"."idx_assistant_intelligence_projection_items_inclusion";

DROP INDEX IF EXISTS "core"."idx_assistant_intelligence_projection_items_target";

DROP INDEX IF EXISTS "core"."idx_assistant_intelligence_projection_events_projection";

DROP INDEX IF EXISTS "core"."idx_assistant_feedback_receipts_feedback";

DROP INDEX IF EXISTS "core"."idx_assistant_feedback_events_feedback";

DROP INDEX IF EXISTS "core"."idx_assistant_enrichment_receipts_job";

DROP INDEX IF EXISTS "core"."idx_assistant_enrichment_jobs_status";

DROP INDEX IF EXISTS "core"."idx_assistant_enrichment_jobs_type";

DROP INDEX IF EXISTS "core"."idx_assistant_enrichment_jobs_source";

DROP INDEX IF EXISTS "core"."idx_assistant_enrichment_jobs_lease";

DROP INDEX IF EXISTS "core"."idx_assistant_decision_memory_events_record";

DROP INDEX IF EXISTS "core"."idx_assistant_context_packs_type";

DROP INDEX IF EXISTS "core"."idx_assistant_context_packs_status";

DROP INDEX IF EXISTS "core"."idx_assistant_context_pack_receipts_pack";

DROP INDEX IF EXISTS "core"."idx_assistant_context_pack_items_pack";

DROP INDEX IF EXISTS "core"."idx_assistant_context_pack_items_source";

DROP INDEX IF EXISTS "core"."idx_assistant_context_pack_events_pack";

DROP INDEX IF EXISTS "core"."idx_assistant_claim_events_claim";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_drafts_type";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_drafts_packet";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_drafts_input";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_sections_draft";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_sections_type";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_sections_item";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_receipts_draft";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_events_draft";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_citations_draft";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_citations_section";

DROP INDEX IF EXISTS "core"."idx_assistant_answer_draft_citations_packet_citation";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stages_type";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stages_workflow";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stages_lineage";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stage_receipts_stage";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stage_items_stage";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stage_items_kind";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stage_items_target";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stage_events_stage";

DROP INDEX IF EXISTS "core"."idx_assistant_action_stage_citations_stage";

DROP INDEX IF EXISTS "core"."ai_job_queue_uq2";

DROP INDEX IF EXISTS "core"."ix_ai_job_queue_env_status";

DROP INDEX IF EXISTS "financial"."aging_exposure_report_items_uq2";

DROP INDEX IF EXISTS "financial"."ix_aging_exposure_report_items_project";

DROP INDEX IF EXISTS "core"."action_items_uq1";
