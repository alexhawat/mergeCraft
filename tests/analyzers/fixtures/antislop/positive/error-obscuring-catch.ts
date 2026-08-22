export function lookup(key: string): string | null {
  try {
    return fetchKey(key);
  } catch (e) {
    return null;
  }
}
