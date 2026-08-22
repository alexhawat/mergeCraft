export function load(): string {
  try {
    return readFile();
  } catch (e) {}
  return "fallback";
}
