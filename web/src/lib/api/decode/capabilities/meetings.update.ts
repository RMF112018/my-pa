import type { Decoder } from "../types";
import { strictObject, checked, nullable, boolean, identifier, type Decoded } from "./continuity.projects.create";
import { meetingView } from "./meetings.read";
import { seriesView, seriesHistory, historyCore, validHistory } from "./meetings.series.update";
const history = checked(strictObject({...historyCore, history_id: identifier("mhst"), meeting_id: identifier("mtg")}), validHistory);
const result = strictObject({meeting: meetingView, history, series: nullable(seriesView), series_history: nullable(seriesHistory), replayed: boolean});
export type MeetingsUpdateResult = Decoded<typeof result>;
export const decodeMeetingsUpdate: Decoder<MeetingsUpdateResult> = result;
