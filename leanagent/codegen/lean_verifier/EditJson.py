#!/usr/bin/env python3
"""
editJson.py - CLI tool for path-based JSON editing.

Usage examples:
  # Append to a list
  python editJson.py --json_path task.json --path '["parameters", 0, "predicates"]' --list_append '{"kind": "isValidFilePath"}'

  # Set a value (creates or overwrites)
  python editJson.py --json_path task.json --path '["name"]' --set '"new_name"'

  # Delete a key or list element
  python editJson.py --json_path task.json --path '["parameters", 1]' --delete

  # Insert into a list at index
  python editJson.py --json_path task.json --path '["parameters", 0, "predicates"]' --list_insert 0 '{"kind": "nonEmpty"}'

  # Remove a specific item from a list by value
  python editJson.py --json_path task.json --path '["parameters", 0, "predicates"]' --list_remove '{"kind": "isValidURL"}'

  # Pretty-print a path (for inspection)
  python editJson.py --json_path task.json --path '["parameters", 0]' --get
"""

import argparse
import json
import sys
import copy


def navigate(data, keys):
    """Navigate into nested JSON, returning (parent, last_key) for mutation."""
    current = data
    for key in keys[:-1]:
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, dict):
            current = current[key]
        else:
            raise KeyError(f"Cannot navigate into {type(current).__name__} with key {key!r}")
    return current, keys[-1] if keys else (data, None)


def resolve(data, keys):
    """Resolve full path to get the value."""
    current = data
    for key in keys:
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, dict):
            current = current[key]
        else:
            raise KeyError(f"Cannot index into {type(current).__name__} with key {key!r}")
    return current


def main():
    parser = argparse.ArgumentParser(description="Edit JSON files via CLI")
    parser.add_argument("--json_path", required=True, help="Path to the JSON file")
    parser.add_argument("--path", required=True, help='JSON array of keys, e.g. \'["parameters", 0, "predicates"]\'')
    parser.add_argument("--indent", type=int, default=2, help="JSON output indent (default: 2)")

    # Operations (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list_append", metavar="VALUE", help="Append a JSON value to the list at path")
    group.add_argument("--list_insert", nargs=2, metavar=("INDEX", "VALUE"), help="Insert a JSON value at index in the list at path")
    group.add_argument("--list_remove", metavar="VALUE", help="Remove first occurrence of JSON value from the list at path")
    group.add_argument("--set", metavar="VALUE", help="Set the value at path (create or overwrite)")
    group.add_argument("--delete", action="store_true", help="Delete the key/index at path")
    group.add_argument("--get", action="store_true", help="Print the value at path (no mutation)")

    args = parser.parse_args()

    # Load JSON
    with open(args.json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    keys = json.loads(args.path)
    if not isinstance(keys, list):
        print("Error: --path must be a JSON array", file=sys.stderr)
        sys.exit(1)

    mutated = True

    try:
        if args.get:
            val = resolve(data, keys)
            print(json.dumps(val, indent=args.indent, ensure_ascii=False))
            mutated = False

        elif args.list_append is not None:
            target = resolve(data, keys)
            if not isinstance(target, list):
                print(f"Error: value at path is {type(target).__name__}, not list", file=sys.stderr)
                sys.exit(1)
            new_val = json.loads(args.list_append)
            target.append(new_val)

        elif args.list_insert is not None:
            idx, val_str = args.list_insert
            idx = int(idx)
            target = resolve(data, keys)
            if not isinstance(target, list):
                print(f"Error: value at path is {type(target).__name__}, not list", file=sys.stderr)
                sys.exit(1)
            new_val = json.loads(val_str)
            target.insert(idx, new_val)

        elif args.list_remove is not None:
            target = resolve(data, keys)
            if not isinstance(target, list):
                print(f"Error: value at path is {type(target).__name__}, not list", file=sys.stderr)
                sys.exit(1)
            rm_val = json.loads(args.list_remove)
            try:
                target.remove(rm_val)
            except ValueError:
                print(f"Warning: value {rm_val!r} not found in list", file=sys.stderr)
                mutated = False

        elif args.set is not None:
            new_val = json.loads(args.set)
            if not keys:
                data = new_val
            else:
                parent, last_key = navigate(data, keys)
                if isinstance(parent, list):
                    parent[int(last_key)] = new_val
                else:
                    parent[last_key] = new_val

        elif args.delete:
            if not keys:
                print("Error: cannot delete root", file=sys.stderr)
                sys.exit(1)
            parent, last_key = navigate(data, keys)
            if isinstance(parent, list):
                del parent[int(last_key)]
            elif isinstance(parent, dict):
                del parent[last_key]
            else:
                print(f"Error: cannot delete from {type(parent).__name__}", file=sys.stderr)
                sys.exit(1)

    except (KeyError, IndexError, TypeError) as e:
        print(f"Error navigating path: {e}", file=sys.stderr)
        sys.exit(1)

    # Write back
    if mutated:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=args.indent, ensure_ascii=False)
            f.write("\n")
        print(f"OK: {args.json_path} updated.")


if __name__ == "__main__":
    main()