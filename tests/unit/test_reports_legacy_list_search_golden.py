"""Reports Modernization WP04: the legacy `reports.list` and `reports.search` are byte-identical.

Both capabilities now take a `plane` selector and, in the `standalone` and
`all` planes, catalog filters (contract C1, C9). The default plane -- `plane`
omitted or `"intelligence"` -- must answer exactly as before for every input
the pipeline plane already accepted and every refusal it already gave, the
catalog fields included: before the extension they were unknown fields, a bare
`invalid_request`, and in the pipeline plane they still are.

`GOLDEN` was captured by running `_transcript(scene)` (no `plane`) against a
fresh export of the base tree `f933f9fb3`, before the extension:

    git archive f933f9fb3 | tar -x -C <scratchpad>/wp04/base_f933f9fb3
    cp tests/unit/test_reports_legacy_list_search_golden.py \\
        <scratchpad>/wp04/base_f933f9fb3/tests/unit/
    # plus a one-test capture module that writes `_transcript(scene)` to a file
    cd <scratchpad>/wp04/base_f933f9fb3
    PYTHONPATH=<scratchpad>/wp04/base_f933f9fb3/src \\
        /Users/bobbyfetting/my-pa/.venv/bin/python -m pytest -q -p no:cacheprovider \\
        tests/unit/capture_legacy_list_search_golden.py

Every case naming `plane` is kept out of the base transcript, because at base
`plane` itself was an unknown field. An explicit `plane: "intelligence"` is
proven instead to give exactly the base transcript, case for case. Each answer
includes the disclosure's truncation, the legacy list's page signal.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from my_pa.adapters.normalization import normalize
from my_pa.application.errors import ApplicationError, problem_detail
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    STAGE_FOR_KIND,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    SourceLaneId,
)
from my_pa.domain.intelligence.models import IntelligenceArtifact, content_digest
from tests.conftest import Scene, build_service

#: Captured at base `f933f9fb3` by `_transcript`; see the module docstring.
GOLDEN: Final = (
    '{"list":{"artifact_kind":{"error":null,"result":{"items":[{"artifact_kind":"rese'
    'arch_context","artifact_state":"partial","content_sha256":"74f091b294c2bb5a26968'
    'f2552c0579b089a8bcb9628c61f92638802e58a1fee","cycle_run_id":"micr_goldencycle000'
    '1","focus_area_id":"communications","report_id":"rpt_goldenaa0002","source_lane"'
    ':"outlook","stage":"researcher","title":"Heron research"}],"next_cursor":null},"'
    'truncation":{"is_truncated":false,"next_cursor":null,"reason":null}},"bad_artifa'
    'ct_kind":{"error":{"code":"invalid_request","correlation_id":"<correlation_id>",'
    '"message":"the request is malformed, incomplete, or contradictory","retry":"afte'
    'r_correction","safe_details":["artifact_kind"]},"refused_by":"normalize"},"bad_c'
    'ursor_malformed":{"error":{"code":"invalid_request","correlation_id":"<correlati'
    'on_id>","message":"the request is malformed, incomplete, or contradictory","retr'
    'y":"after_correction","safe_details":["cursor"]},"refused_by":"normalize"},"bad_'
    'cursor_unknown":{"error":{"code":"invalid_request","correlation_id":"<correlatio'
    'n_id>","message":"the request is malformed, incomplete, or contradictory","retry'
    '":"after_correction","safe_details":["cursor"]},"result":null,"truncation":null}'
    ',"bad_cursor_wrong_kind":{"error":{"code":"invalid_request","correlation_id":"<c'
    'orrelation_id>","message":"the request is malformed, incomplete, or contradictor'
    'y","retry":"after_correction","safe_details":["cursor"]},"refused_by":"normalize'
    '"},"bad_cycle_run_id":{"error":{"code":"invalid_request","correlation_id":"<corr'
    'elation_id>","message":"the request is malformed, incomplete, or contradictory",'
    '"retry":"after_correction","safe_details":["cycle_run_id"]},"refused_by":"normal'
    'ize"},"bad_focus_area_id":{"error":{"allowed_values":[{"detail":"focus_area_id",'
    '"truncated":false,"values":["risk_deadline_exception","decision_approval","commu'
    'nications","project_program_pulse","watchlist_dependency","action_commitment","c'
    'aptures","notes","field_intelligence"]}],"code":"invalid_request","correlation_i'
    'd":"<correlation_id>","message":"the request is malformed, incomplete, or contra'
    'dictory","retry":"after_correction","safe_details":["focus_area_id"]},"refused_b'
    'y":"normalize"},"bad_page_size_bool":{"error":{"code":"invalid_request","correla'
    'tion_id":"<correlation_id>","message":"the request is malformed, incomplete, or '
    'contradictory","retry":"after_correction","safe_details":["page_size"]},"refused'
    '_by":"normalize"},"bad_page_size_text":{"error":{"code":"invalid_request","corre'
    'lation_id":"<correlation_id>","message":"the request is malformed, incomplete, o'
    'r contradictory","retry":"after_correction","safe_details":["page_size"]},"refus'
    'ed_by":"normalize"},"bad_page_size_zero":{"error":{"code":"invalid_request","cor'
    'relation_id":"<correlation_id>","message":"the request is malformed, incomplete,'
    ' or contradictory","retry":"after_correction","safe_details":["page_size"]},"ref'
    'used_by":"normalize"},"bad_report_date":{"error":{"code":"invalid_request","corr'
    'elation_id":"<correlation_id>","message":"the request is malformed, incomplete, '
    'or contradictory","retry":"after_correction","safe_details":["report_date"]},"re'
    'fused_by":"normalize"},"bad_stage":{"error":{"allowed_values":[{"detail":"stage"'
    ',"truncated":false,"values":["collector","researcher","synthesizer","reporter","'
    'morning_brief"]}],"code":"invalid_request","correlation_id":"<correlation_id>","'
    'message":"the request is malformed, incomplete, or contradictory","retry":"after'
    '_correction","safe_details":["stage"]},"refused_by":"normalize"},"bad_stage_with'
    '_catalog_field":{"error":{"allowed_values":[{"detail":"stage","truncated":false,'
    '"values":["collector","researcher","synthesizer","reporter","morning_brief"]}],"'
    'code":"invalid_request","correlation_id":"<correlation_id>","message":"the reque'
    'st is malformed, incomplete, or contradictory","retry":"after_correction","safe_'
    'details":["stage"]},"refused_by":"normalize"},"catalog_associated_with":{"error"'
    ':{"code":"invalid_request","correlation_id":"<correlation_id>","message":"the re'
    'quest is malformed, incomplete, or contradictory","retry":"after_correction","sa'
    'fe_details":[]},"refused_by":"normalize"},"catalog_created_from":{"error":{"code'
    '":"invalid_request","correlation_id":"<correlation_id>","message":"the request i'
    's malformed, incomplete, or contradictory","retry":"after_correction","safe_deta'
    'ils":[]},"refused_by":"normalize"},"catalog_created_to_null":{"error":{"code":"i'
    'nvalid_request","correlation_id":"<correlation_id>","message":"the request is ma'
    'lformed, incomplete, or contradictory","retry":"after_correction","safe_details"'
    ':[]},"refused_by":"normalize"},"catalog_field_with_bad_page_size":{"error":{"cod'
    'e":"invalid_request","correlation_id":"<correlation_id>","message":"the request '
    'is malformed, incomplete, or contradictory","retry":"after_correction","safe_det'
    'ails":[]},"refused_by":"normalize"},"catalog_lifecycle_states_default":{"error":'
    '{"code":"invalid_request","correlation_id":"<correlation_id>","message":"the req'
    'uest is malformed, incomplete, or contradictory","retry":"after_correction","saf'
    'e_details":[]},"refused_by":"normalize"},"catalog_report_date_from":{"error":{"c'
    'ode":"invalid_request","correlation_id":"<correlation_id>","message":"the reques'
    't is malformed, incomplete, or contradictory","retry":"after_correction","safe_d'
    'etails":[]},"refused_by":"normalize"},"catalog_report_date_to":{"error":{"code":'
    '"invalid_request","correlation_id":"<correlation_id>","message":"the request is '
    'malformed, incomplete, or contradictory","retry":"after_correction","safe_detail'
    's":[]},"refused_by":"normalize"},"catalog_tags_empty":{"error":{"code":"invalid_'
    'request","correlation_id":"<correlation_id>","message":"the request is malformed'
    ', incomplete, or contradictory","retry":"after_correction","safe_details":[]},"r'
    'efused_by":"normalize"},"catalog_topics":{"error":{"code":"invalid_request","cor'
    'relation_id":"<correlation_id>","message":"the request is malformed, incomplete,'
    ' or contradictory","retry":"after_correction","safe_details":[]},"refused_by":"n'
    'ormalize"},"catalog_type":{"error":{"code":"invalid_request","correlation_id":"<'
    'correlation_id>","message":"the request is malformed, incomplete, or contradicto'
    'ry","retry":"after_correction","safe_details":[]},"refused_by":"normalize"},"cat'
    'alog_type_null":{"error":{"code":"invalid_request","correlation_id":"<correlatio'
    'n_id>","message":"the request is malformed, incomplete, or contradictory","retry'
    '":"after_correction","safe_details":[]},"refused_by":"normalize"},"cycle_run_id"'
    ':{"error":null,"result":{"items":[{"artifact_kind":"morning_brief","artifact_sta'
    'te":"final","content_sha256":"d96b6d5c99813d4eaf504dd69b897541fbb64f8777c38bcf71'
    '11945bb14f9b9e","cycle_run_id":"micr_goldencycle0001","focus_area_id":"communica'
    'tions","report_id":"rpt_goldenaa0005","source_lane":null,"stage":"morning_brief"'
    ',"title":"Morning brief"},{"artifact_kind":"focus_report","artifact_state":"fina'
    'l","content_sha256":"2ed5212b22ed615244de59b9076f2556041ef69ea2c779121802f19fd39'
    'c3761","cycle_run_id":"micr_goldencycle0001","focus_area_id":"decision_approval"'
    ',"report_id":"rpt_goldenaa0003","source_lane":null,"stage":"reporter","title":"G'
    'olden focus"},{"artifact_kind":"research_context","artifact_state":"partial","co'
    'ntent_sha256":"74f091b294c2bb5a26968f2552c0579b089a8bcb9628c61f92638802e58a1fee"'
    ',"cycle_run_id":"micr_goldencycle0001","focus_area_id":"communications","report_'
    'id":"rpt_goldenaa0002","source_lane":"outlook","stage":"researcher","title":"Her'
    'on research"},{"artifact_kind":"collector_candidates","artifact_state":"final","'
    'content_sha256":"53ec1e1e778cb4dfb4fa08652e37704cac1145d741ba4ac4a8be2f9b0790442'
    '3","cycle_run_id":"micr_goldencycle0001","focus_area_id":"communications","repor'
    't_id":"rpt_goldenaa0001","source_lane":null,"stage":"collector","title":"Golden '
    'collector"}],"next_cursor":null},"truncation":{"is_truncated":false,"next_cursor'
    '":null,"reason":null}},"default":{"error":null,"result":{"items":[{"artifact_kin'
    'd":"morning_brief","artifact_state":"final","content_sha256":"d96b6d5c99813d4eaf'
    '504dd69b897541fbb64f8777c38bcf7111945bb14f9b9e","cycle_run_id":"micr_goldencycle'
    '0001","focus_area_id":"communications","report_id":"rpt_goldenaa0005","source_la'
    'ne":null,"stage":"morning_brief","title":"Morning brief"},{"artifact_kind":"focu'
    's_report","artifact_state":"final","content_sha256":"2ed5212b22ed615244de59b9076'
    'f2556041ef69ea2c779121802f19fd39c3761","cycle_run_id":"micr_goldencycle0001","fo'
    'cus_area_id":"decision_approval","report_id":"rpt_goldenaa0003","source_lane":nu'
    'll,"stage":"reporter","title":"Golden focus"},{"artifact_kind":"research_context'
    '","artifact_state":"partial","content_sha256":"74f091b294c2bb5a26968f2552c0579b0'
    '89a8bcb9628c61f92638802e58a1fee","cycle_run_id":"micr_goldencycle0001","focus_ar'
    'ea_id":"communications","report_id":"rpt_goldenaa0002","source_lane":"outlook","'
    'stage":"researcher","title":"Heron research"},{"artifact_kind":"collector_candid'
    'ates","artifact_state":"final","content_sha256":"53ec1e1e778cb4dfb4fa08652e37704'
    'cac1145d741ba4ac4a8be2f9b07904423","cycle_run_id":"micr_goldencycle0001","focus_'
    'area_id":"communications","report_id":"rpt_goldenaa0001","source_lane":null,"sta'
    'ge":"collector","title":"Golden collector"}],"next_cursor":null},"truncation":{"'
    'is_truncated":false,"next_cursor":null,"reason":null}},"focus_area_id":{"error":'
    'null,"result":{"items":[{"artifact_kind":"focus_report","artifact_state":"final"'
    ',"content_sha256":"2ed5212b22ed615244de59b9076f2556041ef69ea2c779121802f19fd39c3'
    '761","cycle_run_id":"micr_goldencycle0001","focus_area_id":"decision_approval","'
    'report_id":"rpt_goldenaa0003","source_lane":null,"stage":"reporter","title":"Gol'
    'den focus"}],"next_cursor":null},"truncation":{"is_truncated":false,"next_cursor'
    '":null,"reason":null}},"include_superseded":{"error":null,"result":{"items":[{"a'
    'rtifact_kind":"morning_brief","artifact_state":"final","content_sha256":"d96b6d5'
    'c99813d4eaf504dd69b897541fbb64f8777c38bcf7111945bb14f9b9e","cycle_run_id":"micr_'
    'goldencycle0001","focus_area_id":"communications","report_id":"rpt_goldenaa0005"'
    ',"source_lane":null,"stage":"morning_brief","title":"Morning brief"},{"artifact_'
    'kind":"focus_report","artifact_state":"superseded","content_sha256":"b7ed0d58a20'
    '591278d82f24c10ab817460c3e0739d24f8d2900dae562b6cce97","cycle_run_id":"micr_gold'
    'encycle0001","focus_area_id":"decision_approval","report_id":"rpt_goldenaa0004",'
    '"source_lane":null,"stage":"reporter","title":"Golden focus, superseded"},{"arti'
    'fact_kind":"focus_report","artifact_state":"final","content_sha256":"2ed5212b22e'
    'd615244de59b9076f2556041ef69ea2c779121802f19fd39c3761","cycle_run_id":"micr_gold'
    'encycle0001","focus_area_id":"decision_approval","report_id":"rpt_goldenaa0003",'
    '"source_lane":null,"stage":"reporter","title":"Golden focus"},{"artifact_kind":"'
    'research_context","artifact_state":"partial","content_sha256":"74f091b294c2bb5a2'
    '6968f2552c0579b089a8bcb9628c61f92638802e58a1fee","cycle_run_id":"micr_goldencycl'
    'e0001","focus_area_id":"communications","report_id":"rpt_goldenaa0002","source_l'
    'ane":"outlook","stage":"researcher","title":"Heron research"},{"artifact_kind":"'
    'collector_candidates","artifact_state":"final","content_sha256":"53ec1e1e778cb4d'
    'fb4fa08652e37704cac1145d741ba4ac4a8be2f9b07904423","cycle_run_id":"micr_goldency'
    'cle0001","focus_area_id":"communications","report_id":"rpt_goldenaa0001","source'
    '_lane":null,"stage":"collector","title":"Golden collector"}],"next_cursor":null}'
    ',"truncation":{"is_truncated":false,"next_cursor":null,"reason":null}},"include_'
    'superseded_not_bool":{"error":null,"result":{"items":[{"artifact_kind":"morning_'
    'brief","artifact_state":"final","content_sha256":"d96b6d5c99813d4eaf504dd69b8975'
    '41fbb64f8777c38bcf7111945bb14f9b9e","cycle_run_id":"micr_goldencycle0001","focus'
    '_area_id":"communications","report_id":"rpt_goldenaa0005","source_lane":null,"st'
    'age":"morning_brief","title":"Morning brief"},{"artifact_kind":"focus_report","a'
    'rtifact_state":"superseded","content_sha256":"b7ed0d58a20591278d82f24c10ab817460'
    'c3e0739d24f8d2900dae562b6cce97","cycle_run_id":"micr_goldencycle0001","focus_are'
    'a_id":"decision_approval","report_id":"rpt_goldenaa0004","source_lane":null,"sta'
    'ge":"reporter","title":"Golden focus, superseded"},{"artifact_kind":"focus_repor'
    't","artifact_state":"final","content_sha256":"2ed5212b22ed615244de59b9076f255604'
    '1ef69ea2c779121802f19fd39c3761","cycle_run_id":"micr_goldencycle0001","focus_are'
    'a_id":"decision_approval","report_id":"rpt_goldenaa0003","source_lane":null,"sta'
    'ge":"reporter","title":"Golden focus"},{"artifact_kind":"research_context","arti'
    'fact_state":"partial","content_sha256":"74f091b294c2bb5a26968f2552c0579b089a8bcb'
    '9628c61f92638802e58a1fee","cycle_run_id":"micr_goldencycle0001","focus_area_id":'
    '"communications","report_id":"rpt_goldenaa0002","source_lane":"outlook","stage":'
    '"researcher","title":"Heron research"},{"artifact_kind":"collector_candidates","'
    'artifact_state":"final","content_sha256":"53ec1e1e778cb4dfb4fa08652e37704cac1145'
    'd741ba4ac4a8be2f9b07904423","cycle_run_id":"micr_goldencycle0001","focus_area_id'
    '":"communications","report_id":"rpt_goldenaa0001","source_lane":null,"stage":"co'
    'llector","title":"Golden collector"}],"next_cursor":null},"truncation":{"is_trun'
    'cated":false,"next_cursor":null,"reason":null}},"last_page_of_two":{"error":null'
    ',"result":{"items":[{"artifact_kind":"collector_candidates","artifact_state":"fi'
    'nal","content_sha256":"53ec1e1e778cb4dfb4fa08652e37704cac1145d741ba4ac4a8be2f9b0'
    '7904423","cycle_run_id":"micr_goldencycle0001","focus_area_id":"communications",'
    '"report_id":"rpt_goldenaa0001","source_lane":null,"stage":"collector","title":"G'
    'olden collector"}],"next_cursor":null},"truncation":{"is_truncated":false,"next_'
    'cursor":null,"reason":null}},"other_cycle_run_id":{"error":null,"result":{"items'
    '":[],"next_cursor":null},"truncation":{"is_truncated":false,"next_cursor":null,"'
    'reason":null}},"page_of_two":{"error":null,"result":{"items":[{"artifact_kind":"'
    'morning_brief","artifact_state":"final","content_sha256":"d96b6d5c99813d4eaf504d'
    'd69b897541fbb64f8777c38bcf7111945bb14f9b9e","cycle_run_id":"micr_goldencycle0001'
    '","focus_area_id":"communications","report_id":"rpt_goldenaa0005","source_lane":'
    'null,"stage":"morning_brief","title":"Morning brief"},{"artifact_kind":"focus_re'
    'port","artifact_state":"final","content_sha256":"2ed5212b22ed615244de59b9076f255'
    '6041ef69ea2c779121802f19fd39c3761","cycle_run_id":"micr_goldencycle0001","focus_'
    'area_id":"decision_approval","report_id":"rpt_goldenaa0003","source_lane":null,"'
    'stage":"reporter","title":"Golden focus"}],"next_cursor":"rpt_goldenaa0003"},"tr'
    'uncation":{"is_truncated":true,"next_cursor":"rpt_goldenaa0003","reason":"page_s'
    'ize_reached"}},"page_size_over_maximum":{"error":null,"result":{"items":[{"artif'
    'act_kind":"morning_brief","artifact_state":"final","content_sha256":"d96b6d5c998'
    '13d4eaf504dd69b897541fbb64f8777c38bcf7111945bb14f9b9e","cycle_run_id":"micr_gold'
    'encycle0001","focus_area_id":"communications","report_id":"rpt_goldenaa0005","so'
    'urce_lane":null,"stage":"morning_brief","title":"Morning brief"},{"artifact_kind'
    '":"focus_report","artifact_state":"final","content_sha256":"2ed5212b22ed615244de'
    '59b9076f2556041ef69ea2c779121802f19fd39c3761","cycle_run_id":"micr_goldencycle00'
    '01","focus_area_id":"decision_approval","report_id":"rpt_goldenaa0003","source_l'
    'ane":null,"stage":"reporter","title":"Golden focus"},{"artifact_kind":"research_'
    'context","artifact_state":"partial","content_sha256":"74f091b294c2bb5a26968f2552'
    'c0579b089a8bcb9628c61f92638802e58a1fee","cycle_run_id":"micr_goldencycle0001","f'
    'ocus_area_id":"communications","report_id":"rpt_goldenaa0002","source_lane":"out'
    'look","stage":"researcher","title":"Heron research"},{"artifact_kind":"collector'
    '_candidates","artifact_state":"final","content_sha256":"53ec1e1e778cb4dfb4fa0865'
    '2e37704cac1145d741ba4ac4a8be2f9b07904423","cycle_run_id":"micr_goldencycle0001",'
    '"focus_area_id":"communications","report_id":"rpt_goldenaa0001","source_lane":nu'
    'll,"stage":"collector","title":"Golden collector"}],"next_cursor":null},"truncat'
    'ion":{"is_truncated":false,"next_cursor":null,"reason":null}},"report_date":{"er'
    'ror":null,"result":{"items":[{"artifact_kind":"morning_brief","artifact_state":"'
    'final","content_sha256":"d96b6d5c99813d4eaf504dd69b897541fbb64f8777c38bcf7111945'
    'bb14f9b9e","cycle_run_id":"micr_goldencycle0001","focus_area_id":"communications'
    '","report_id":"rpt_goldenaa0005","source_lane":null,"stage":"morning_brief","tit'
    'le":"Morning brief"},{"artifact_kind":"focus_report","artifact_state":"final","c'
    'ontent_sha256":"2ed5212b22ed615244de59b9076f2556041ef69ea2c779121802f19fd39c3761'
    '","cycle_run_id":"micr_goldencycle0001","focus_area_id":"decision_approval","rep'
    'ort_id":"rpt_goldenaa0003","source_lane":null,"stage":"reporter","title":"Golden'
    ' focus"}],"next_cursor":null},"truncation":{"is_truncated":false,"next_cursor":n'
    'ull,"reason":null}},"second_page_of_two":{"error":null,"result":{"items":[{"arti'
    'fact_kind":"research_context","artifact_state":"partial","content_sha256":"74f09'
    '1b294c2bb5a26968f2552c0579b089a8bcb9628c61f92638802e58a1fee","cycle_run_id":"mic'
    'r_goldencycle0001","focus_area_id":"communications","report_id":"rpt_goldenaa000'
    '2","source_lane":"outlook","stage":"researcher","title":"Heron research"},{"arti'
    'fact_kind":"collector_candidates","artifact_state":"final","content_sha256":"53e'
    'c1e1e778cb4dfb4fa08652e37704cac1145d741ba4ac4a8be2f9b07904423","cycle_run_id":"m'
    'icr_goldencycle0001","focus_area_id":"communications","report_id":"rpt_goldenaa0'
    '001","source_lane":null,"stage":"collector","title":"Golden collector"}],"next_c'
    'ursor":null},"truncation":{"is_truncated":false,"next_cursor":null,"reason":null'
    '}},"source_lane":{"error":null,"result":{"items":[{"artifact_kind":"research_con'
    'text","artifact_state":"partial","content_sha256":"74f091b294c2bb5a26968f2552c05'
    '79b089a8bcb9628c61f92638802e58a1fee","cycle_run_id":"micr_goldencycle0001","focu'
    's_area_id":"communications","report_id":"rpt_goldenaa0002","source_lane":"outloo'
    'k","stage":"researcher","title":"Heron research"}],"next_cursor":null},"truncati'
    'on":{"is_truncated":false,"next_cursor":null,"reason":null}},"stage":{"error":nu'
    'll,"result":{"items":[{"artifact_kind":"focus_report","artifact_state":"final","'
    'content_sha256":"2ed5212b22ed615244de59b9076f2556041ef69ea2c779121802f19fd39c376'
    '1","cycle_run_id":"micr_goldencycle0001","focus_area_id":"decision_approval","re'
    'port_id":"rpt_goldenaa0003","source_lane":null,"stage":"reporter","title":"Golde'
    'n focus"}],"next_cursor":null},"truncation":{"is_truncated":false,"next_cursor":'
    'null,"reason":null}},"unknown_field":{"error":{"code":"invalid_request","correla'
    'tion_id":"<correlation_id>","message":"the request is malformed, incomplete, or '
    'contradictory","retry":"after_correction","safe_details":[]},"refused_by":"norma'
    'lize"}},"search":{"artifact_kind":{"error":null,"result":{"items":[{"artifact_ki'
    'nd":"morning_brief","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_golde'
    'naa0005","snippet":"everything golden","stage":"morning_brief","title":"Morning '
    'brief"}]},"truncation":{"is_truncated":false,"next_cursor":null,"reason":null}},'
    '"bad_artifact_kind":{"error":{"code":"invalid_request","correlation_id":"<correl'
    'ation_id>","message":"the request is malformed, incomplete, or contradictory","r'
    'etry":"after_correction","safe_details":["artifact_kind"]},"refused_by":"normali'
    'ze"},"bad_page_size":{"error":{"code":"invalid_request","correlation_id":"<corre'
    'lation_id>","message":"the request is malformed, incomplete, or contradictory","'
    'retry":"after_correction","safe_details":["page_size"]},"refused_by":"normalize"'
    '},"bad_stage":{"error":{"allowed_values":[{"detail":"stage","truncated":false,"v'
    'alues":["collector","researcher","synthesizer","reporter","morning_brief"]}],"co'
    'de":"invalid_request","correlation_id":"<correlation_id>","message":"the request'
    ' is malformed, incomplete, or contradictory","retry":"after_correction","safe_de'
    'tails":["stage"]},"refused_by":"normalize"},"bad_stage_with_catalog_field":{"err'
    'or":{"allowed_values":[{"detail":"stage","truncated":false,"values":["collector"'
    ',"researcher","synthesizer","reporter","morning_brief"]}],"code":"invalid_reques'
    't","correlation_id":"<correlation_id>","message":"the request is malformed, inco'
    'mplete, or contradictory","retry":"after_correction","safe_details":["stage"]},"'
    'refused_by":"normalize"},"case_folded":{"error":null,"result":{"items":[{"artifa'
    'ct_kind":"focus_report","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_g'
    'oldenaa0003","snippet":"Golden focus","stage":"reporter","title":"Golden focus"}'
    ',{"artifact_kind":"collector_candidates","cycle_run_id":"micr_goldencycle0001","'
    'report_id":"rpt_goldenaa0001","snippet":"Golden collector","stage":"collector","'
    'title":"Golden collector"},{"artifact_kind":"morning_brief","cycle_run_id":"micr'
    '_goldencycle0001","report_id":"rpt_goldenaa0005","snippet":"everything golden","'
    'stage":"morning_brief","title":"Morning brief"},{"artifact_kind":"research_conte'
    'xt","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0002","snippe'
    't":"golden research body","stage":"researcher","title":"Heron research"}]},"trun'
    'cation":{"is_truncated":false,"next_cursor":null,"reason":null}},"catalog_associ'
    'ated_with":{"error":{"code":"invalid_request","correlation_id":"<correlation_id>'
    '","message":"the request is malformed, incomplete, or contradictory","retry":"af'
    'ter_correction","safe_details":[]},"refused_by":"normalize"},"catalog_created_fr'
    'om":{"error":{"code":"invalid_request","correlation_id":"<correlation_id>","mess'
    'age":"the request is malformed, incomplete, or contradictory","retry":"after_cor'
    'rection","safe_details":[]},"refused_by":"normalize"},"catalog_created_to":{"err'
    'or":{"code":"invalid_request","correlation_id":"<correlation_id>","message":"the'
    ' request is malformed, incomplete, or contradictory","retry":"after_correction",'
    '"safe_details":[]},"refused_by":"normalize"},"catalog_cursor":{"error":{"code":"'
    'invalid_request","correlation_id":"<correlation_id>","message":"the request is m'
    'alformed, incomplete, or contradictory","retry":"after_correction","safe_details'
    '":[]},"refused_by":"normalize"},"catalog_cursor_null":{"error":{"code":"invalid_'
    'request","correlation_id":"<correlation_id>","message":"the request is malformed'
    ', incomplete, or contradictory","retry":"after_correction","safe_details":[]},"r'
    'efused_by":"normalize"},"catalog_lifecycle_states":{"error":{"code":"invalid_req'
    'uest","correlation_id":"<correlation_id>","message":"the request is malformed, i'
    'ncomplete, or contradictory","retry":"after_correction","safe_details":[]},"refu'
    'sed_by":"normalize"},"catalog_report_date_from":{"error":{"code":"invalid_reques'
    't","correlation_id":"<correlation_id>","message":"the request is malformed, inco'
    'mplete, or contradictory","retry":"after_correction","safe_details":[]},"refused'
    '_by":"normalize"},"catalog_report_date_to_null":{"error":{"code":"invalid_reques'
    't","correlation_id":"<correlation_id>","message":"the request is malformed, inco'
    'mplete, or contradictory","retry":"after_correction","safe_details":[]},"refused'
    '_by":"normalize"},"catalog_tags":{"error":{"code":"invalid_request","correlation'
    '_id":"<correlation_id>","message":"the request is malformed, incomplete, or cont'
    'radictory","retry":"after_correction","safe_details":[]},"refused_by":"normalize'
    '"},"catalog_topics":{"error":{"code":"invalid_request","correlation_id":"<correl'
    'ation_id>","message":"the request is malformed, incomplete, or contradictory","r'
    'etry":"after_correction","safe_details":[]},"refused_by":"normalize"},"catalog_t'
    'ype":{"error":{"code":"invalid_request","correlation_id":"<correlation_id>","mes'
    'sage":"the request is malformed, incomplete, or contradictory","retry":"after_co'
    'rrection","safe_details":[]},"refused_by":"normalize"},"cycle_run_id":{"error":n'
    'ull,"result":{"items":[{"artifact_kind":"focus_report","cycle_run_id":"micr_gold'
    'encycle0001","report_id":"rpt_goldenaa0003","snippet":"Golden focus","stage":"re'
    'porter","title":"Golden focus"},{"artifact_kind":"collector_candidates","cycle_r'
    'un_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0001","snippet":"Golden c'
    'ollector","stage":"collector","title":"Golden collector"},{"artifact_kind":"morn'
    'ing_brief","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0005",'
    '"snippet":"everything golden","stage":"morning_brief","title":"Morning brief"},{'
    '"artifact_kind":"research_context","cycle_run_id":"micr_goldencycle0001","report'
    '_id":"rpt_goldenaa0002","snippet":"golden research body","stage":"researcher","t'
    'itle":"Heron research"}]},"truncation":{"is_truncated":false,"next_cursor":null,'
    '"reason":null}},"empty_query":{"error":null,"result":{"items":[{"artifact_kind":'
    '"morning_brief","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0'
    '005","snippet":"Morning brief","stage":"morning_brief","title":"Morning brief"},'
    '{"artifact_kind":"focus_report","cycle_run_id":"micr_goldencycle0001","report_id'
    '":"rpt_goldenaa0003","snippet":"Golden focus","stage":"reporter","title":"Golden'
    ' focus"},{"artifact_kind":"research_context","cycle_run_id":"micr_goldencycle000'
    '1","report_id":"rpt_goldenaa0002","snippet":"Heron research","stage":"researcher'
    '","title":"Heron research"},{"artifact_kind":"collector_candidates","cycle_run_i'
    'd":"micr_goldencycle0001","report_id":"rpt_goldenaa0001","snippet":"Golden colle'
    'ctor","stage":"collector","title":"Golden collector"}]},"truncation":{"is_trunca'
    'ted":false,"next_cursor":null,"reason":null}},"focus_area_id":{"error":null,"res'
    'ult":{"items":[{"artifact_kind":"collector_candidates","cycle_run_id":"micr_gold'
    'encycle0001","report_id":"rpt_goldenaa0001","snippet":"Golden collector","stage"'
    ':"collector","title":"Golden collector"},{"artifact_kind":"morning_brief","cycle'
    '_run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0005","snippet":"everyt'
    'hing golden","stage":"morning_brief","title":"Morning brief"},{"artifact_kind":"'
    'research_context","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_goldena'
    'a0002","snippet":"golden research body","stage":"researcher","title":"Heron rese'
    'arch"}]},"truncation":{"is_truncated":false,"next_cursor":null,"reason":null}},"'
    'golden":{"error":null,"result":{"items":[{"artifact_kind":"focus_report","cycle_'
    'run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0003","snippet":"Golden '
    'focus","stage":"reporter","title":"Golden focus"},{"artifact_kind":"collector_ca'
    'ndidates","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0001","'
    'snippet":"Golden collector","stage":"collector","title":"Golden collector"},{"ar'
    'tifact_kind":"morning_brief","cycle_run_id":"micr_goldencycle0001","report_id":"'
    'rpt_goldenaa0005","snippet":"everything golden","stage":"morning_brief","title":'
    '"Morning brief"},{"artifact_kind":"research_context","cycle_run_id":"micr_golden'
    'cycle0001","report_id":"rpt_goldenaa0002","snippet":"golden research body","stag'
    'e":"researcher","title":"Heron research"}]},"truncation":{"is_truncated":false,"'
    'next_cursor":null,"reason":null}},"heron":{"error":null,"result":{"items":[{"art'
    'ifact_kind":"research_context","cycle_run_id":"micr_goldencycle0001","report_id"'
    ':"rpt_goldenaa0002","snippet":"Heron research","stage":"researcher","title":"Her'
    'on research"},{"artifact_kind":"focus_report","cycle_run_id":"micr_goldencycle00'
    '01","report_id":"rpt_goldenaa0003","snippet":"a focus on herons","stage":"report'
    'er","title":"Golden focus"},{"artifact_kind":"collector_candidates","cycle_run_i'
    'd":"micr_goldencycle0001","report_id":"rpt_goldenaa0001","snippet":"alpha heron '
    'notes","stage":"collector","title":"Golden collector"}]},"truncation":{"is_trunc'
    'ated":false,"next_cursor":null,"reason":null}},"include_superseded_unknown_here"'
    ':{"error":{"code":"invalid_request","correlation_id":"<correlation_id>","message'
    '":"the request is malformed, incomplete, or contradictory","retry":"after_correc'
    'tion","safe_details":[]},"refused_by":"normalize"},"missing_query":{"error":{"co'
    'de":"invalid_request","correlation_id":"<correlation_id>","message":"the request'
    ' is malformed, incomplete, or contradictory","retry":"after_correction","safe_de'
    'tails":[]},"refused_by":"normalize"},"no_match":{"error":null,"result":{"items":'
    '[]},"truncation":{"is_truncated":false,"next_cursor":null,"reason":null}},"page_'
    'of_one":{"error":null,"result":{"items":[{"artifact_kind":"focus_report","cycle_'
    'run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0003","snippet":"Golden '
    'focus","stage":"reporter","title":"Golden focus"}]},"truncation":{"is_truncated"'
    ':false,"next_cursor":null,"reason":null}},"page_size_over_maximum":{"error":null'
    ',"result":{"items":[{"artifact_kind":"focus_report","cycle_run_id":"micr_goldenc'
    'ycle0001","report_id":"rpt_goldenaa0003","snippet":"Golden focus","stage":"repor'
    'ter","title":"Golden focus"},{"artifact_kind":"collector_candidates","cycle_run_'
    'id":"micr_goldencycle0001","report_id":"rpt_goldenaa0001","snippet":"Golden coll'
    'ector","stage":"collector","title":"Golden collector"},{"artifact_kind":"morning'
    '_brief","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0005","sn'
    'ippet":"everything golden","stage":"morning_brief","title":"Morning brief"},{"ar'
    'tifact_kind":"research_context","cycle_run_id":"micr_goldencycle0001","report_id'
    '":"rpt_goldenaa0002","snippet":"golden research body","stage":"researcher","titl'
    'e":"Heron research"}]},"truncation":{"is_truncated":false,"next_cursor":null,"re'
    'ason":null}},"query_not_text":{"error":{"code":"invalid_request","correlation_id'
    '":"<correlation_id>","message":"the request is malformed, incomplete, or contrad'
    'ictory","retry":"after_correction","safe_details":["query"]},"refused_by":"norma'
    'lize"},"report_date_unknown_here":{"error":{"code":"invalid_request","correlatio'
    'n_id":"<correlation_id>","message":"the request is malformed, incomplete, or con'
    'tradictory","retry":"after_correction","safe_details":[]},"refused_by":"normaliz'
    'e"},"source_lane":{"error":null,"result":{"items":[{"artifact_kind":"research_co'
    'ntext","cycle_run_id":"micr_goldencycle0001","report_id":"rpt_goldenaa0002","sni'
    'ppet":"golden research body","stage":"researcher","title":"Heron research"}]},"t'
    'runcation":{"is_truncated":false,"next_cursor":null,"reason":null}},"stage":{"er'
    'ror":null,"result":{"items":[{"artifact_kind":"focus_report","cycle_run_id":"mic'
    'r_goldencycle0001","report_id":"rpt_goldenaa0003","snippet":"Golden focus","stag'
    'e":"reporter","title":"Golden focus"}]},"truncation":{"is_truncated":false,"next'
    '_cursor":null,"reason":null}},"unknown_field":{"error":{"code":"invalid_request"'
    ',"correlation_id":"<correlation_id>","message":"the request is malformed, incomp'
    'lete, or contradictory","retry":"after_correction","safe_details":[]},"refused_b'
    'y":"normalize"}}}'
)

T0: Final = datetime(2026, 8, 1, 6, 0, tzinfo=UTC)

#: (id, kind, focus area, source lane, report date, title, body, state,
#: is_current, hours after T0). Fixed ids and distinct commit times, so no order
#: depends on a randomly minted identifier.
_Seed = tuple[
    str, ArtifactKind, FocusAreaId, SourceLaneId | None, str, str, str, ArtifactState, bool, int
]
_SEED: Final[tuple[_Seed, ...]] = (
    (
        "rpt_goldenaa0001",
        ArtifactKind.COLLECTOR_CANDIDATES,
        FocusAreaId.COMMUNICATIONS,
        None,
        "2026-08-20",
        "Golden collector",
        "alpha heron notes",
        ArtifactState.FINAL,
        True,
        0,
    ),
    (
        "rpt_goldenaa0002",
        ArtifactKind.RESEARCH_CONTEXT,
        FocusAreaId.COMMUNICATIONS,
        SourceLaneId.OUTLOOK,
        "2026-08-20",
        "Heron research",
        "golden research body",
        ArtifactState.PARTIAL,
        True,
        1,
    ),
    (
        "rpt_goldenaa0003",
        ArtifactKind.FOCUS_REPORT,
        FocusAreaId.DECISION_APPROVAL,
        None,
        "2026-08-21",
        "Golden focus",
        "a focus on herons",
        ArtifactState.FINAL,
        True,
        2,
    ),
    (
        "rpt_goldenaa0004",
        ArtifactKind.FOCUS_REPORT,
        FocusAreaId.DECISION_APPROVAL,
        None,
        "2026-08-19",
        "Golden focus, superseded",
        "an older focus",
        ArtifactState.SUPERSEDED,
        False,
        3,
    ),
    (
        "rpt_goldenaa0005",
        ArtifactKind.MORNING_BRIEF,
        FocusAreaId.COMMUNICATIONS,
        None,
        "2026-08-21",
        "Morning brief",
        "everything golden",
        ArtifactState.FINAL,
        True,
        4,
    ),
)

_CYCLE: Final = "micr_goldencycle0001"


def _seed(scene: Scene) -> None:
    """Place the artifacts directly in the in-memory store (legacy rows, no manifest)."""
    principal_id = scene.principal.principal_id
    for index, (
        artifact_id,
        kind,
        focus_area,
        lane,
        report_date,
        title,
        body,
        state,
        is_current,
        hours,
    ) in enumerate(_SEED):
        at = T0 + timedelta(hours=hours)
        scene.world.intelligence.artifacts[(principal_id, artifact_id)] = IntelligenceArtifact(
            artifact_id=artifact_id,
            principal_id=principal_id,
            cycle_run_id=_CYCLE,
            producer_run_id=f"rrun_goldenrun{index:04d}",
            stage=STAGE_FOR_KIND[kind],
            artifact_kind=kind.value,
            report_date=date.fromisoformat(report_date),
            title=title,
            body_markdown=body,
            content_sha256=content_digest(body),
            content_bytes=len(body.encode("utf-8")),
            artifact_state=state,
            schema_version="1",
            generated_at=at,
            committed_at=at,
            version=1,
            is_current=is_current,
            focus_area_id=focus_area,
            source_lane=lane,
        )


#: The `reports.list` cases, by name. None names `plane`.
LIST_CASES: Final[dict[str, dict[str, object]]] = {
    "default": {},
    "page_of_two": {"page_size": 2},
    "second_page_of_two": {"page_size": 2, "cursor": "rpt_goldenaa0003"},
    "last_page_of_two": {"page_size": 2, "cursor": "rpt_goldenaa0002"},
    "include_superseded": {"include_superseded": True},
    "include_superseded_not_bool": {"include_superseded": "yes"},
    "cycle_run_id": {"cycle_run_id": _CYCLE},
    "other_cycle_run_id": {"cycle_run_id": "micr_goldencycle0002"},
    "stage": {"stage": "reporter"},
    "artifact_kind": {"artifact_kind": "research_context"},
    "focus_area_id": {"focus_area_id": "decision_approval"},
    "source_lane": {"source_lane": "outlook"},
    "report_date": {"report_date": "2026-08-21"},
    "page_size_over_maximum": {"page_size": 1000},
    "bad_page_size_zero": {"page_size": 0},
    "bad_page_size_text": {"page_size": "2"},
    "bad_page_size_bool": {"page_size": True},
    "bad_cursor_malformed": {"cursor": "rpt_x"},
    "bad_cursor_unknown": {"cursor": "rpt_0000000000000000golden"},
    "bad_cursor_wrong_kind": {"cursor": "grpt_aaaaaaaa11111111"},
    "bad_stage": {"stage": "nowhere"},
    "bad_artifact_kind": {"artifact_kind": "Not A Kind"},
    "bad_focus_area_id": {"focus_area_id": "nowhere"},
    "bad_report_date": {"report_date": "2026-13-01"},
    "bad_cycle_run_id": {"cycle_run_id": "micr_x"},
    "unknown_field": {"color": "blue"},
    # The catalog fields, each alone and at a default value: unknown here.
    "catalog_type": {"type": "focus_report"},
    "catalog_type_null": {"type": None},
    "catalog_topics": {"topics": ["alpha"]},
    "catalog_tags_empty": {"tags": []},
    "catalog_associated_with": {
        "associated_with": {"target_kind": "project", "target_ref": "prj_aaaaaaaa11111111"}
    },
    "catalog_lifecycle_states_default": {"lifecycle_states": ["active"]},
    "catalog_created_from": {"created_from": "2026-08-01T00:00:00Z"},
    "catalog_created_to_null": {"created_to": None},
    "catalog_report_date_from": {"report_date_from": "2026-08-01"},
    "catalog_report_date_to": {"report_date_to": "2026-08-31"},
    # A pipeline refusal still comes first, where the constructor came after it.
    "bad_stage_with_catalog_field": {"stage": "nowhere", "topics": ["alpha"]},
    "catalog_field_with_bad_page_size": {"page_size": 0, "type": "focus_report"},
}

#: The `reports.search` cases, by name. None names `plane`.
SEARCH_CASES: Final[dict[str, dict[str, object]]] = {
    "golden": {"query": "golden"},
    "heron": {"query": "heron"},
    "case_folded": {"query": "GOLDEN"},
    "no_match": {"query": "zebra"},
    "empty_query": {"query": ""},
    "page_of_one": {"query": "golden", "page_size": 1},
    "page_size_over_maximum": {"query": "golden", "page_size": 1000},
    "stage": {"query": "golden", "stage": "reporter"},
    "artifact_kind": {"query": "golden", "artifact_kind": "morning_brief"},
    "focus_area_id": {"query": "golden", "focus_area_id": "communications"},
    "source_lane": {"query": "golden", "source_lane": "outlook"},
    "cycle_run_id": {"query": "golden", "cycle_run_id": _CYCLE},
    "missing_query": {},
    "query_not_text": {"query": 5},
    "bad_page_size": {"query": "golden", "page_size": 0},
    "bad_stage": {"query": "golden", "stage": "nowhere"},
    "bad_artifact_kind": {"query": "golden", "artifact_kind": "Not A Kind"},
    "unknown_field": {"query": "golden", "color": "blue"},
    "report_date_unknown_here": {"query": "golden", "report_date": "2026-08-21"},
    "include_superseded_unknown_here": {"query": "golden", "include_superseded": False},
    # The catalog fields (the cursor included: the pipeline search had none).
    "catalog_cursor": {"query": "golden", "cursor": "rpt_goldenaa0003"},
    "catalog_cursor_null": {"query": "golden", "cursor": None},
    "catalog_type": {"query": "golden", "type": "focus_report"},
    "catalog_topics": {"query": "golden", "topics": ["alpha"]},
    "catalog_tags": {"query": "golden", "tags": ["red"]},
    "catalog_associated_with": {
        "query": "golden",
        "associated_with": {"target_kind": "project", "target_ref": "prj_aaaaaaaa11111111"},
    },
    "catalog_lifecycle_states": {"query": "golden", "lifecycle_states": ["active"]},
    "catalog_created_from": {"query": "golden", "created_from": "2026-08-01T00:00:00Z"},
    "catalog_created_to": {"query": "golden", "created_to": "2026-09-01T00:00:00Z"},
    "catalog_report_date_from": {"query": "golden", "report_date_from": "2026-08-01"},
    "catalog_report_date_to_null": {"query": "golden", "report_date_to": None},
    "bad_stage_with_catalog_field": {"query": "golden", "stage": "nowhere", "type": "x"},
}


def _answer(
    service: ApplicationService, scene: Scene, capability: Capability, payload: dict[str, object]
) -> Any:  # noqa: ANN401
    try:
        metadata, command = normalize(capability.value, _wire(scene, payload))
    except ApplicationError as error:
        problem = problem_detail(error, correlation_id="corr_golden0000000000000000000000")
        return {"refused_by": "normalize", "error": problem.model_dump(mode="json")}
    envelope = service.invoke(metadata, command, principal=scene.principal)
    rendered = envelope.model_dump(mode="json")
    disclosure = rendered.get("disclosure") or {}
    return {
        "result": rendered["result"],
        "error": rendered["error"],
        "truncation": disclosure.get("truncation"),
    }


def _wire(scene: Scene, payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-golden-catalog",
        "purpose": Purpose.REPORT_READ.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-08-20T12:00:00Z",
        "payload": payload,
    }


def _transcript(scene: Scene, extra: dict[str, object] | None = None) -> str:
    """Every case's answer, `extra` merged into each payload, as canonical JSON."""
    _seed(scene)
    service = build_service(scene.world, scene.providers)
    added = extra or {}
    transcript = json.dumps(
        {
            "list": {
                name: _answer(service, scene, Capability.REPORTS_LIST, {**payload, **added})
                for name, payload in LIST_CASES.items()
            },
            "search": {
                name: _answer(service, scene, Capability.REPORTS_SEARCH, {**payload, **added})
                for name, payload in SEARCH_CASES.items()
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    # Issued per request, never part of the answer.
    return re.sub(r"corr_[A-Za-z0-9]+", "<correlation_id>", transcript)


def test_the_legacy_list_and_search_answer_exactly_as_before_the_extension(
    scene: Scene,
) -> None:
    assert _transcript(scene) == GOLDEN


def test_an_explicit_intelligence_plane_answers_exactly_as_the_default(scene: Scene) -> None:
    """`plane: "intelligence"` is the default plane: every case, byte for byte."""
    assert _transcript(scene, {"plane": "intelligence"}) == GOLDEN
