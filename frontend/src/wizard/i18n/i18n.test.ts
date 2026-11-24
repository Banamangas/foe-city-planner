import { describe, expect, it } from "vitest";
import { LANGS, detectLang, languageName, translate } from "./index";

const files = import.meta.glob("./*.json", { eager: true, import: "default" }) as Record<
  string,
  Record<string, string>
>;
const dict = (lang: string) => files[`./${lang}.json`];
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("translation files", () => {
  it("lists English first", () => {
    expect(LANGS[0]).toBe("en");
    expect(LANGS).toContain("fr");
  });
  it("every language has exactly the English keys", () => {
    const en = Object.keys(dict("en")).sort();
    for (const lang of LANGS) expect(Object.keys(dict(lang)).sort(), lang).toEqual(en);
  });
  it("placeholders match", () => {
    for (const lang of LANGS)
      for (const [k, v] of Object.entries(dict("en")))
        expect(placeholders(dict(lang)[k]), `${lang}:${k}`).toEqual(placeholders(v));
  });
  it("no forbidden words", () => {
    for (const lang of LANGS)
      for (const [k, v] of Object.entries(dict(lang)))
        expect(v, `${lang}:${k}`).not.toMatch(/\bjson\b|worker|cp-sat|k-walk/i);
  });
  it("names languages", () => {
    expect(languageName("en")).toBe("English");
    expect(languageName("fr")).toBe("Français");
  });
});

describe("detectLang", () => {
  it("picks from the system languages or the saved choice", () => {
    expect(detectLang(["fr-FR"], null)).toBe("fr");
    expect(detectLang(["de-DE", "en-US"], null)).toBe("en");
    expect(detectLang(["en-US"], "fr")).toBe("fr");
    expect(detectLang(["fr-FR"], "xx")).toBe("fr");
    expect(detectLang([], null)).toBe("en");
  });
});

describe("translate", () => {
  it("falls back to English, then the key", () => {
    expect(translate("xx", "nav.next")).toBe(translate("en", "nav.next"));
    expect(translate("en", "no.such.key")).toBe("no.such.key");
  });
  it("replaces placeholders", () => {
    const s = translate("en", "run.machine", { cpus: 16, threads: 12 });
    expect(s).toContain("16");
    expect(s).toContain("12");
    expect(s).not.toContain("{");
  });
});
