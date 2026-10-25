// Reads server pattern dicts (JSON array) on stdin, writes the browser's text for each (JSON array).
// Used by test_validation.py to check the editor round-trips patterns without changing them.
import { modelFromPattern, modelToText } from "../koii_studio/static/model.js";

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  const patterns = JSON.parse(input);
  process.stdout.write(JSON.stringify(patterns.map((pattern) => modelToText(modelFromPattern(pattern)))));
});
