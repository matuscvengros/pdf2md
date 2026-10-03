// Validate every $$...$$ and $...$ formula in Markdown files with KaTeX.
// Usage: node math-review/check_math.js FILE.md [...]
// Prints one line per formula that KaTeX cannot parse and exits 1 if any fail.
// Install KaTeX once with: npm install --prefix math-review
const fs = require("fs");
const katex = require("katex");

let failures = 0;
let checked = 0;
for (const file of process.argv.slice(2)) {
  const src = fs.readFileSync(file, "utf8");
  const lineAt = (offset) => src.slice(0, offset).split("\n").length;
  const check = (tex, offset, displayMode) => {
    checked += 1;
    try {
      katex.renderToString(tex, { displayMode, throwOnError: true, strict: "ignore" });
    } catch (err) {
      failures += 1;
      const kind = displayMode ? "display" : "inline";
      console.log(`${file}:${lineAt(offset)}: ${kind}: ${err.message.split("\n")[0]}\n    ${tex.trim().slice(0, 200)}`);
    }
  };
  // Display math first, then blank it out so its dollars are not read as inline delimiters.
  const masked = src.replace(/\$\$([\s\S]+?)\$\$/g, (match, tex, offset) => {
    check(tex, offset, true);
    return match.replace(/[^\n]/g, " ");
  });
  let opening = null;
  const unmatched = (offset) => {
    failures += 1;
    console.log(`${file}:${lineAt(offset)}: unbalanced $ delimiter`);
  };
  for (const m of masked.matchAll(/\$/g)) {
    const offset = m.index;
    // Unmatched display delimiters are reported separately below.
    if (masked[offset - 1] === "$" || masked[offset + 1] === "$") continue;
    let slashes = 0;
    for (let i = offset - 1; i >= 0 && masked[i] === "\\"; i--) slashes += 1;
    if (slashes % 2) continue; // Escaped literal currency or a dollar inside math.
    if (opening !== null && masked.slice(opening, offset).includes("\n")) {
      unmatched(opening);
      opening = null;
    }
    if (opening === null) {
      opening = offset;
    } else {
      check(masked.slice(opening + 1, offset), opening, false);
      opening = null;
    }
  }
  if (opening !== null) unmatched(opening);
  if (/\$\$/.test(masked)) {
    failures += 1;
    console.log(`${file}: unbalanced $$ delimiter`);
  }
}
console.log(`checked ${checked} formulas, ${failures} problem(s)`);
process.exit(failures ? 1 : 0);
