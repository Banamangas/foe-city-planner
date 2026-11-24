// Translation files are flat objects of dotted keys. Adding a language means
// adding one <code>.json file here: no code change.
type Dict = Record<string, string>;

const modules = import.meta.glob("./*.json", { eager: true, import: "default" }) as Record<
  string,
  Dict
>;

const dicts: Record<string, Dict> = {};
for (const [path, dict] of Object.entries(modules)) {
  const code = path.replace(/^\.\//, "").replace(/\.json$/, "");
  dicts[code] = dict;
}

export const LANGS: string[] = Object.keys(dicts).sort((a, b) =>
  a === "en" ? -1 : b === "en" ? 1 : a.localeCompare(b),
);

export function languageName(lang: string): string {
  return dicts[lang]?._language ?? lang;
}

export function detectLang(navigatorLanguages: readonly string[], saved: string | null): string {
  if (saved && LANGS.includes(saved)) return saved;
  const first = navigatorLanguages[0]?.toLowerCase().split("-")[0];
  return first && LANGS.includes(first) ? first : "en";
}

export function translate(
  lang: string,
  key: string,
  vars?: Record<string, string | number>,
): string {
  const text = dicts[lang]?.[key] ?? dicts.en?.[key] ?? key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}
