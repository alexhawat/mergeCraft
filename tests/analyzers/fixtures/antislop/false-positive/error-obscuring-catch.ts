export function lookup(key: string): string {
  try {
    return fetchKey(key);
  } catch (e) {
    throw new Error(`missing ${key}`);
  }
}
