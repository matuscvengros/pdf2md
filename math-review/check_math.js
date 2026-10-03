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
    return " ".repeat(match.length);
  });
  for (const m of masked.matchAll(/(?<![\\$])\$(?!\$)([^$\n]+?)(?<!\\)\$/g)) {
    check(m[1], m.index, false);
  }
  if (/\$\$/.test(masked)) {
    failures += 1;
    console.log(`${file}: unbalanced $$ delimiter`);
  }
}
console.log(`checked ${checked} formulas, ${failures} problem(s)`);
process.exit(failures ? 1 : 0);
