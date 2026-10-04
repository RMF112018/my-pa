import type { Decoder } from "../types";
import { meetingPage } from "./meetings.list";
import type { Decoded } from "./continuity.projects.create";
export type MeetingsSearchResult = Decoded<typeof meetingPage>;
export const decodeMeetingsSearch: Decoder<MeetingsSearchResult> = meetingPage;
