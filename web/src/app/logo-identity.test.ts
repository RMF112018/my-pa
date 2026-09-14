// @vitest-environment node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const PNG_192 = "/icons/icon-192.png";
const PNG_512 = "/icons/icon-512.png";
const PNG_MASKABLE = "/icons/icon-maskable-512.png";

function readBytes(relativePath: string): Buffer {
  return readFileSync(join(process.cwd(), relativePath));
}

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function pngSize(bytes: Buffer): { width: number; height: number } {
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

function expectExactFile(relativePath: string, byteLength: number, digest: string): Buffer {
  const bytes = readBytes(relativePath);
  expect(bytes.byteLength, relativePath).toBe(byteLength);
  expect(sha256(bytes), relativePath).toBe(digest);
  return bytes;
}

function expectExactPng(
  relativePath: string,
  byteLength: number,
  digest: string,
  width: number,
  height: number,
): void {
  const bytes = expectExactFile(relativePath, byteLength, digest);
  expect(pngSize(bytes), relativePath).toEqual({ width, height });
}

describe("logo binary identity", () => {
  it("locks apple-icon.png bytes, hash, and 180x180 IHDR", () => {
    expectExactPng(
      "src/app/apple-icon.png",
      35125,
      "fd30fc403cb92741e2fd6e571359a573b334f7e48a77c92a3650dd05b08dc8c6",
      180,
      180,
    );
  });

  it("locks install PNG bytes, hashes, and IHDRs", () => {
    expectExactPng(
      "public/icons/icon-192.png",
      39161,
      "c13e9b54f9cda44d502fb7d440e4fad83d8d46286fda94b434009ccd1377b049",
      192,
      192,
    );
    expectExactPng(
      "public/icons/icon-512.png",
      205848,
      "e5d1f92c02ea93a0ae2fc6c3f783913d88173585041e26a3780f673bddd717ef",
      512,
      512,
    );
    expectExactPng(
      "public/icons/icon-maskable-512.png",
      205848,
      "e5d1f92c02ea93a0ae2fc6c3f783913d88173585041e26a3780f673bddd717ef",
      512,
      512,
    );
  });

  it("locks favicon.ico bytes and hash", () => {
    expectExactFile(
      "public/favicon.ico",
      101006,
      "af1b7be02ee1a3983c3ae7f45ed31d38c70c6c9474c5c4d5440905997dcbccb0",
    );
  });

  it("locks light and dark 32px favicon PNG bytes, hashes, and IHDRs", () => {
    expectExactPng(
      "public/icons/favicon-light-32.png",
      1505,
      "0e23ec91915d7dee068c6aa1219d53cfda63ecaff273c859286d95b66723bae4",
      32,
      32,
    );
    expectExactPng(
      "public/icons/favicon-dark-32.png",
      1928,
      "d3e72a20779bbf0f309a3da1eb6d7699fd396281eb174293c2a8e0ff50d9bfaa",
      32,
      32,
    );
  });
});

describe("manifest identity", () => {
  it("names My PA and lists only the three PNG install icons", () => {
    const manifest = JSON.parse(readBytes("public/manifest.webmanifest").toString("utf8")) as {
      name?: string;
      short_name?: string;
      icons?: Array<{ src?: string; type?: string; media?: string }>;
    };
    expect(manifest.name).toBe("My PA");
    expect(manifest.short_name).toBe("My PA");
    const icons = manifest.icons ?? [];
    expect(icons.map((icon) => icon.src)).toEqual([PNG_192, PNG_512, PNG_MASKABLE]);
    expect(icons.some((icon) => icon.src === "/icons/icon.svg")).toBe(false);
    expect(icons.some((icon) => icon.type === "image/svg+xml")).toBe(false);
    expect(icons.some((icon) => "media" in icon && icon.media !== undefined)).toBe(false);
  });
});

describe("layout identity", () => {
  it("declares My PA and static light/dark favicon media strings", () => {
    const source = readBytes("src/app/layout.tsx").toString("utf8");
    expect(source).toContain('title: "My PA"');
    expect(source).toContain("(prefers-color-scheme: light)");
    expect(source).toContain("(prefers-color-scheme: dark)");
    expect(source).toContain('url: "/favicon.ico"');
    expect(source).not.toContain("My-PA");
  });
});

describe("service worker identity", () => {
  it("uses mypa-static-v3 and precaches the three PNGs plus the manifest, not icon.svg", () => {
    const source = readBytes("public/sw.js").toString("utf8");
    expect(source).toContain('const CACHE_NAME = "mypa-static-v3"');
    expect(source).not.toContain("/icons/icon.svg");
    expect(source).toContain("/manifest.webmanifest");
    expect(source).toContain(PNG_192);
    expect(source).toContain(PNG_512);
    expect(source).toContain(PNG_MASKABLE);
  });
});
