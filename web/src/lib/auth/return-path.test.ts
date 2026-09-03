import { describe, expect, it } from "vitest";
import { safeReturnPath } from "@/lib/auth/return-path";

describe("safeReturnPath", () => {
  it("allows relative paths including query strings", () => {
    expect(safeReturnPath("/today")).toBe("/today");
    expect(safeReturnPath("/work?x=1")).toBe("/work?x=1");
    expect(safeReturnPath("/relationships/abc")).toBe("/relationships/abc");
  });

  it("rejects absolute URLs, protocol-relative, javascript, and backslash", () => {
    expect(safeReturnPath("https://evil.example")).toBeNull();
    expect(safeReturnPath("http://evil.example")).toBeNull();
    expect(safeReturnPath("//evil")).toBeNull();
    expect(safeReturnPath("javascript:alert(1)")).toBeNull();
    expect(safeReturnPath("data:text/html,hi")).toBeNull();
    expect(safeReturnPath("/\\evil")).toBeNull();
    expect(safeReturnPath("\\\\evil")).toBeNull();
  });

  it("rejects encoded slash tricks and whitespace", () => {
    expect(safeReturnPath("/%2f")).toBeNull();
    expect(safeReturnPath("/%2Fevil")).toBeNull();
    expect(safeReturnPath("/%5c")).toBeNull();
    expect(safeReturnPath("/foo bar")).toBeNull();
    expect(safeReturnPath("/foo\tbar")).toBeNull();
  });

  it("returns null for empty or missing input", () => {
    expect(safeReturnPath(undefined)).toBeNull();
    expect(safeReturnPath(null)).toBeNull();
    expect(safeReturnPath("")).toBeNull();
    expect(safeReturnPath("today")).toBeNull();
  });
});
