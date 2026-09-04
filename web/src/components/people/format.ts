/** Present a closed-vocabulary code without claiming a prettier name than the plane used. */
export function codeLabel(value: string): string {
  return value.replaceAll("_", " ");
}

/** A moment, rendered so it is legible without claiming a precision it lacks. */
export function moment(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : `${parsed.toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

export function effectiveWindow(from: string | null, to: string | null): string | null {
  if (!from && !to) return null;
  if (from && to) return `${moment(from)} – ${moment(to)}`;
  if (from) return `from ${moment(from)}`;
  return `until ${moment(to as string)}`;
}
