import type { Decoder } from "../types";
import { decodeTaskListPage, type TaskListEntry } from "./_read-helpers";

export type { TaskListEntry };

export type TasksSearchResult = { readonly tasks: readonly TaskListEntry[] };

export const decodeTasksSearch: Decoder<TasksSearchResult> = decodeTaskListPage;
