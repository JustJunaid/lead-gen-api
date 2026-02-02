#!/usr/bin/env python3
import pandas as pd
import re
import argparse
import sys
import os

def split_emails(cell):
    """Split on comma, semicolon, pipe or whitespace.
    Also handles Python list-like strings: "['a@b.com', 'c@d.com']"
    """
    if pd.isna(cell) or not str(cell).strip():
        return []

    text = str(cell).strip()

    # Handle Python list-like format: "['email1', 'email2']"
    if text.startswith('[') and text.endswith(']'):
        # Remove brackets and split by comma
        inner = text[1:-1]
        # Extract quoted strings (handles both single and double quotes)
        parts = re.findall(r"['\"]([^'\"]+)['\"]", inner)
        if parts:
            return [p.strip() for p in parts if p.strip()]

    # split on common delimiters
    parts = re.split(r'[;,|\s]\s*', text)
    return [p for p in parts if p]

def find_email_columns(cols):
    """Return all columns whose normalized name contains 'email'.
    Normalization lowercases and strips non-alphanumeric characters (including underscores)."""
    matches = []
    for c in cols:
        # normalize column name
        norm = re.sub(r'[^0-9a-z]+', '', c.lower())
        # matches 'email', 'emails', 'businessemail', 'business_email', etc.
        if 'email' in norm:
            matches.append(c)
    return matches


def prompt_user_choice(columns):
    """Prompt user to select one column from a list."""
    print("ℹ️  Multiple email columns detected:")
    for i, col in enumerate(columns, 1):
        print(f"   {i}. {col}")

    while True:
        try:
            choice = input(f"Enter your choice (1-{len(columns)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(columns):
                return columns[idx]
            print(f"❌ Please enter a number between 1 and {len(columns)}")
        except ValueError:
            print("❌ Please enter a valid number")
        except (EOFError, KeyboardInterrupt):
            sys.exit("\n❌ Selection cancelled.")

def main():
    parser = argparse.ArgumentParser(
        description="Split rows on multiple emails in one cell into separate rows."
    )
    parser.add_argument(
        "input_csv",
        nargs='?', default='input.csv',
        help="Filename of the input CSV (in the same directory as this script; default: input.csv)"
    )
    parser.add_argument(
        "output_csv",
        nargs='?', default='output.csv',
        help="Filename of the output CSV (written next to this script; default: output.csv)"
    )
    parser.add_argument(
        "-e", "--email-column",
        help="Name of the column containing emails (auto-detected if omitted)"
    )
    args = parser.parse_args()

    # Determine paths relative to the script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, args.input_csv)
    output_path = os.path.join(script_dir, args.output_csv)

    # Load CSV
    try:
        df = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        sys.exit(f"❌ Input file '{input_path}' not found.")
    except Exception as err:
        sys.exit(f"Error reading '{input_path}': {err}")

    # Detect or validate email column
    if args.email_column:
        email_col = args.email_column
        if email_col not in df.columns:
            sys.exit(f"❌ Column '{email_col}' not found in CSV headers.")
    else:
        email_cols = find_email_columns(df.columns)
        if not email_cols:
            sys.exit(
                "❌ Could not auto-detect an email column. "
                "Please re-run with --email-column <COLUMN_NAME>."
            )
        elif len(email_cols) == 1:
            email_col = email_cols[0]
        else:
            # Multiple email columns found - ask user to choose
            email_col = prompt_user_choice(email_cols)

    print(f"ℹ️  Using email column: '{email_col}'")

    # Skip rows where email column is empty/blank before processing
    original_count = len(df)
    df = df[df[email_col].str.strip().astype(bool)]
    skipped_empty = original_count - len(df)
    if skipped_empty > 0:
        print(f"ℹ️  Skipped {skipped_empty} rows with empty '{email_col}'")

    # Split and explode
    df['_split_emails'] = df[email_col].apply(split_emails)
    df = df.explode('_split_emails').reset_index(drop=True)
    df[email_col] = df['_split_emails']
    df = df.drop(columns=['_split_emails'])
    # Remove any rows that resulted in blank emails after splitting
    df = df[df[email_col].str.strip().astype(bool)]

    # Write output
    try:
        df.to_csv(output_path, index=False)
        print(f"✅ Wrote {len(df)} rows to '{output_path}'")
    except Exception as err:
        sys.exit(f"Error writing '{output_path}': {err}")

if __name__ == "__main__":
    main()