import type { Decoder } from "../types";
import { strictObject, checked, integer, boolean, enumeration, identifier, timestamp, type Decoded } from "./continuity.projects.create";
import { meetingTitle } from "./meetings.read";
export const seriesView = strictObject({meeting_series_id: identifier("mser"), title: meetingTitle, version: integer(1), created_at: timestamp, updated_at: timestamp});
export const historyCore = {
  action: enumeration(["create", "update"]), actor: enumeration(["principal", "assistant", "system"]), outcome: enumeration(["applied", "no_op"]),
  before_version: integer(0), after_version: integer(1), occurred_at: timestamp, recorded_at: timestamp,
};
type HistoryCore = Decoded<ReturnType<typeof strictObject<typeof historyCore>>>;
export function validHistory(value: HistoryCore): boolean {
  return value.action === "create" ? value.before_version === 0 && value.after_version === 1 && value.outcome === "applied" :
    value.before_version >= 1 && value.after_version === value.before_version + (value.outcome === "applied" ? 1 : 0);
}
export const seriesHistory = checked(strictObject({...historyCore, series_history_id: identifier("mshst"), meeting_series_id: identifier("mser")}), validHistory);
const result = strictObject({series: seriesView, history: seriesHistory, replayed: boolean});
export type MeetingsSeriesUpdateResult = Decoded<typeof result>;
export const decodeMeetingsSeriesUpdate: Decoder<MeetingsSeriesUpdateResult> = result;
