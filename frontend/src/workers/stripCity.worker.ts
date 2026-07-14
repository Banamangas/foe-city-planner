import { stripCity } from "./stripCity";

self.onmessage = async (e: MessageEvent<File>) => {
  const file = e.data;
  try {
    (self as unknown as Worker).postMessage({ phase: "parsing" });
    const text = await file.text();
    const data = JSON.parse(text);
    (self as unknown as Worker).postMessage({ phase: "stripping" });
    const slim = stripCity(data);
    (self as unknown as Worker).postMessage({ phase: "done", slim });
  } catch (err) {
    (self as unknown as Worker).postMessage({ phase: "error", message: String(err) });
  }
};
