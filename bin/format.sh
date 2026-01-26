#!/bin/bash
set -e  # Exit on first error

echo "🎨 Formatting Python code with ruff …"
uv run ruff check --fix .
uv run ruff format .

echo "📝 Format markdown, json and yaml files with Prettier …"
npx prettier --write "**/*.{md,json,yaml}" --log-level silent

echo "📝 Sorting and deduplicating requirements.txt files …"
find ./ -type f -name "requirements.txt" -exec sort -u {} -o {} --ignore-case \;
find ./ -type f -name "requirements-dev.txt" -exec sort -u {} -o {} --ignore-case \;

echo "✅ Formatting complete!"
