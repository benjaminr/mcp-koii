// Reads arrangement texts (JSON array) on stdin and writes how the browser's arranger reads
// each one: { sections, text } or { error }. Used by test_validation.py to check the grid
// reads arrangements the way the server does.
import { arrangementText, parseArrangement } from "../koii/static/arranger.js";

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  const texts = JSON.parse(input);
  process.stdout.write(JSON.stringify(texts.map((text) => {
    const { sections, error } = parseArrangement(text);
    return error ? { error } : { sections, text: arrangementText(sections) };
  })));
});
