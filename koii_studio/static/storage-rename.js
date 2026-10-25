// The project was renamed koii studio: carry the page's saved settings (layouts, the open
// view, the editor draft …) over from their old "koii." keys, once. Imported first by app.js,
// before anything reads them.

/** Every key the page saves starts with this. */
export const STORAGE_PREFIX = "koii-studio.";
const OLD_PREFIX = "koii.";

try {
  const oldKeys = Object.keys(localStorage).filter((key) => key.startsWith(OLD_PREFIX));
  for (const key of oldKeys) {
    const renamed = STORAGE_PREFIX + key.slice(OLD_PREFIX.length);
    if (localStorage.getItem(renamed) === null) localStorage.setItem(renamed, localStorage.getItem(key));
    localStorage.removeItem(key);
  }
} catch {
  // Storage is blocked: there's nothing to carry over.
}
