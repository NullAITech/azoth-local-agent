#!/usr/bin/env python3
"""CLI utility for executing DuckyScript macros and zero-detection automation."""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

# Add root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.duckyscript import (
    DUCKY_PRESETS,
    get_ducky_engine,
    load_all_presets,
    parse_var_declaration,
    run_duckyscript,
)


def parse_var_args(var_list: list[str]) -> Dict[str, str]:
    """Parse list of 'KEY=VAL' strings into dictionary."""
    vars_dict = {}
    if not var_list:
        return vars_dict
    for item in var_list:
        if "=" in item:
            k, v = parse_var_declaration(item)
            vars_dict[k] = v
        else:
            vars_dict[item.strip()] = ""
    return vars_dict


def main():
    parser = argparse.ArgumentParser(
        description="🦆 a-bot DuckyScript CLI & Macro Automation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Run inline DuckyScript
  ducky_cli.py "STRING Hello World\\nENTER"

  # Run a macro preset with variable overrides
  ducky_cli.py --preset x_post --var POST_TEXT="Deploying a-bot v2 🦆✨"

  # Run from file
  ducky_cli.py --file tools/presets/linkedin_outreach.ducky -v SEARCH_QUERY="CTO Virginia Beach"

  # Validate syntax without execution
  ducky_cli.py --file tools/presets/google_scrape.ducky --validate

  # List all available presets
  ducky_cli.py --list-presets
""",
    )
    parser.add_argument(
        "script_or_text",
        nargs="?",
        default=None,
        help="DuckyScript payload, file path, or raw text to type",
    )
    parser.add_argument(
        "-f", "--file",
        help="Path to .ducky or .txt macro script file",
    )
    parser.add_argument(
        "-p", "--preset",
        help="Preset ID or macro name to execute (e.g. x_post, linkedin_outreach, google_scrape)",
    )
    parser.add_argument(
        "-v", "--var", "-D",
        action="append",
        dest="variables",
        default=[],
        help="Set macro variable in KEY=VAL format (e.g. -v POST_TEXT='Hello' -v CITY='Norfolk')",
    )
    parser.add_argument(
        "--target",
        choices=["browser", "os"],
        default="browser",
        help="Automation target: 'browser' (Sandboxed Headed Chrome) or 'os' (native desktop)",
    )
    parser.add_argument(
        "--mode",
        choices=["ducky", "tweet", "type"],
        default="ducky",
        help="Execution mode: 'ducky' (standard DuckyScript), 'tweet' (auto navigate to X and post), or 'type'",
    )
    parser.add_argument(
        "--url",
        default="https://x.com/compose/post",
        help="URL for tweet or quick navigate mode",
    )
    parser.add_argument(
        "--validate", "--dry-run",
        dest="validate_only",
        action="store_true",
        help="Perform static syntax and argument check without executing actions",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List all available DuckyScript macro presets with descriptions and parameters",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON results",
    )

    args = parser.parse_args()

    # 1. Handle --list-presets
    if args.list_presets:
        presets = load_all_presets()
        if args.json:
            print(json.dumps({"ok": True, "presets": presets}, indent=2))
        else:
            print(f"🦆 a-bot DuckyScript Presets Library ({len(presets)} macros found):\n")
            for p in presets:
                tags_str = f" [{', '.join(p.get('tags', []))}]" if p.get("tags") else ""
                vars_str = f" (vars: {', '.join(p.get('variables', []))})" if p.get("variables") else ""
                print(f"  • {p['id']} - {p['title']}{tags_str}")
                print(f"    Description: {p['description']}")
                if vars_str:
                    print(f"    Variables:   {', '.join(p.get('variables', []))}")
                print()
        sys.exit(0)

    # 2. Determine script payload
    script_content = ""
    cli_vars = parse_var_args(args.variables)
    engine = get_ducky_engine()

    if args.preset:
        try:
            _, script_content = engine.resolve_macro_content(args.preset)
        except Exception as e:
            res = {"ok": False, "error": str(e), "suggestion": "Use --list-presets to view available macros."}
            print(json.dumps(res, indent=2))
            sys.exit(1)

    elif args.file:
        file_p = Path(args.file)
        if not file_p.exists():
            res = {"ok": False, "error": f"File '{args.file}' not found."}
            print(json.dumps(res, indent=2))
            sys.exit(1)
        script_content = file_p.read_text(encoding="utf-8")

    elif args.script_or_text:
        # Check if positional argument is an existing file
        pos_path = Path(args.script_or_text)
        if pos_path.exists() and pos_path.is_file():
            script_content = pos_path.read_text(encoding="utf-8")
        elif args.mode == "tweet":
            script_content = f"""
REM Quick Tweet Mode
NAVIGATE {args.url}
WAIT_FOR [data-testid="tweetTextarea_0"], div[role="textbox"] 8000
RANDOM_DELAY 1000 2000
STRING {args.script_or_text}
RANDOM_DELAY 800 1400
CTRL+ENTER
DELAY 2500
"""
        elif args.mode == "type":
            script_content = f"STRING {args.script_or_text}\nENTER"
        else:
            script_content = args.script_or_text
    else:
        parser.print_help()
        sys.exit(1)

    if script_content and "\\n" in script_content and "\n" not in script_content:
        script_content = script_content.replace("\\n", "\n")

    # 3. Handle --validate / --dry-run
    if args.validate_only:
        val_res = engine.validate(script_content, initial_vars=cli_vars)
        if args.json or not val_res.get("valid"):
            print(json.dumps(val_res, indent=2))
        else:
            print(f"✅ DuckyScript validation passed: {val_res['total_lines']} lines checked, {len(val_res['variables_defined'])} variables detected.")
        sys.exit(0 if val_res.get("valid") else 1)

    # 4. Execute script
    res = engine.execute(
        script_content=script_content,
        target=args.target,
        vars=cli_vars,
    )

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            print(f"✅ Success: {res.get('summary', 'Executed successfully')}")
            for step in res.get("executed_steps", []):
                print(f"   ▶ {step}")
        else:
            print(f"❌ Execution Failed: {res.get('error')}")
            if "line_number" in res:
                print(f"   Line {res['line_number']}: {res.get('line_content', '')}")
            if "suggestion" in res:
                print(f"   💡 Recovery Suggestion: {res['suggestion']}")
            if res.get("executed_steps"):
                print("   Executed prior steps:")
                for step in res.get("executed_steps", []):
                    print(f"     ✓ {step}")

    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
